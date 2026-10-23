"""
interpreter.py
--------------
A small C interpreter, used to RUN programs when no C compiler (gcc/clang)
is installed. It lets the dashboard show a program's output and compare
the original against the optimized version on any machine.

Supported subset (what typical teaching programs use):
    types        int, char, short, long, long long, unsigned, float, double, void
    statements   if/else, while, do-while, for, switch/case, break, continue, return
    expressions  all C operators, casts, ternary, ++/--, compound assignment, sizeof
    data         scalars, 1-D/2-D arrays, strings, pointers (&x, *p, p+1, p[i]),
                 function pointers, global variables, static locals, enum, #define NAME value
    library      printf, puts, putchar, strlen, strcmp, abs, sqrt, pow, floor, ceil, ...

Not supported (reported clearly instead of guessing): struct/union/typedef,
malloc/free, scanf/file I/O, function-like macros, goto. Install gcc to run those.
"""
import math
import re
import struct
import sys
import threading
import time

from .extraction import remove_comments


class Unsupported(Exception):
    """A C feature outside the supported subset."""


class CRuntimeError(Exception):
    """The C program did something that would crash or misbehave."""


class _Timeout(Exception):
    pass


class _Exit(Exception):
    def __init__(self, code):
        self.code = code


class _Return(Exception):
    def __init__(self, value):
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


# ---------------------------------------------------------------------------
# values
# ---------------------------------------------------------------------------
class Arr(list):
    """A C array / variable cell. `et` is the element type used for conversions."""
    et = "int"


class Ptr:
    __slots__ = ("cont", "idx")

    def __init__(self, cont, idx):
        self.cont, self.idx = cont, idx

    def __eq__(self, other):
        return isinstance(other, Ptr) and other.cont is self.cont and other.idx == self.idx

    def __hash__(self):
        return hash((id(self.cont), self.idx))


class FuncRef:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, FuncRef) and other.name == self.name

    def __hash__(self):
        return hash(self.name)


INT_INFO = {
    "char": (8, True), "uchar": (8, False), "short": (16, True), "ushort": (16, False),
    "int": (32, True), "uint": (32, False), "long": (64, True), "ulong": (64, False),
    "llong": (64, True), "ullong": (64, False),
}
SIZEOF = {"char": 1, "uchar": 1, "short": 2, "ushort": 2, "int": 4, "uint": 4, "long": 8,
          "ulong": 8, "llong": 8, "ullong": 8, "float": 4, "double": 8, "ptr": 8}


def _wrap(v, bits, signed):
    v &= (1 << bits) - 1
    if signed and v >> (bits - 1):
        v -= 1 << bits
    return v


def _to_f32(v):
    try:
        return struct.unpack("f", struct.pack("f", v))[0]
    except OverflowError:
        return math.copysign(math.inf, v)


def coerce(v, t):
    info = INT_INFO.get(t)
    if info:
        if isinstance(v, float):
            if v != v or v in (math.inf, -math.inf):
                return 0
            v = int(v)
        elif not isinstance(v, int):
            return v
        return _wrap(v, info[0], info[1])
    if t == "double":
        return float(v) if isinstance(v, (int, float)) else v
    if t == "float":
        return _to_f32(float(v)) if isinstance(v, (int, float)) else v
    return v


def truth(v):
    if isinstance(v, (int, float)):
        return v != 0
    return True          # pointers, arrays, function references


# ---------------------------------------------------------------------------
# tokenizer / parser
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<float>(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?[fFlL]?|\d+[eE][+-]?\d+[fFlL]?)
  | (?P<int>0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*)
  | (?P<id>[A-Za-z_]\w*)
  | (?P<str>"(?:\\.|[^"\\\n])*")
  | (?P<chr>'(?:\\.|[^'\\\n])+')
  | (?P<op><<=|>>=|\.\.\.|->|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||\+=|-=|\*=|/=|%=|&=|\|=|\^=|[-+*/%&|^~!<>=?:;,.(){}\[\]])
""", re.X)

_QUALS = {"const", "static", "extern", "register", "volatile", "inline", "auto", "restrict"}
_TYPE_KW = _QUALS | {"int", "char", "short", "long", "float", "double", "void", "unsigned", "signed"}
_ESC = {"n": 10, "t": 9, "r": 13, "0": 0, "a": 7, "b": 8, "f": 12, "v": 11,
        "\\": 92, "'": 39, '"': 34, "?": 63}
_BIN_LEVELS = [["||"], ["&&"], ["|"], ["^"], ["&"], ["==", "!="], ["<", ">", "<=", ">="],
               ["<<", ">>"], ["+", "-"], ["*", "/", "%"]]
_ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}


def _decode_string(body: str):
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.append(ord(c))
            i += 1
            continue
        i += 1
        c = body[i] if i < len(body) else "\\"
        if c == "x":
            m = re.match(r"[0-9a-fA-F]+", body[i + 1:])
            out.append(int(m.group(0), 16) & 0xFF if m else ord("x"))
            i += 1 + (len(m.group(0)) if m else 0)
        elif c in "01234567":
            m = re.match(r"[0-7]{1,3}", body[i:])
            out.append(int(m.group(0), 8) & 0xFF)
            i += len(m.group(0))
        else:
            out.append(_ESC.get(c, ord(c)))
            i += 1
    return out


class Parser:
    def __init__(self, code: str):
        self.macros = {}
        src = self._preprocess(remove_comments(code))
        self.toks = self._expand(self._tokenize(src), 0)
        self.pos = 0
        self.enums = {}
        self.static_flag = False

    # -- preprocessing / tokens ---------------------------------------------
    def _preprocess(self, src):
        lines = []
        for line in src.split("\n"):
            if line.lstrip().startswith("#"):
                m = re.match(r"\s*#\s*define\s+(\w+)(\()?\s*(.*)$", line)
                if m:
                    if m.group(2):
                        raise Unsupported("function-like #define macros")
                    self.macros[m.group(1)] = m.group(3).strip()
                line = ""
            lines.append(line)
        return "\n".join(lines)

    def _tokenize(self, src):
        toks, pos, line = [], 0, 1
        while pos < len(src):
            m = _TOKEN_RE.match(src, pos)
            if not m:
                raise Unsupported(f"line {line}: unexpected character {src[pos]!r}")
            kind = m.lastgroup
            if kind == "ws":
                line += m.group(0).count("\n")
            else:
                toks.append((kind, m.group(0), line))
            pos = m.end()
        return toks

    def _expand(self, toks, depth):
        if not self.macros or depth > 8:
            return toks
        out, changed = [], False
        for kind, text, line in toks:
            if kind == "id" and text in self.macros:
                out += [(k, t, line) for k, t, _l in self._tokenize(self.macros[text])]
                changed = True
            else:
                out.append((kind, text, line))
        return self._expand(out, depth + 1) if changed else out

    # -- helpers --------------------------------------------------------------
    def t(self, k=0):
        i = self.pos + k
        return self.toks[i][1] if i < len(self.toks) else ""

    def kind(self, k=0):
        i = self.pos + k
        return self.toks[i][0] if i < len(self.toks) else "eof"

    def line(self):
        i = min(self.pos, len(self.toks) - 1)
        return self.toks[i][2] if self.toks else 0

    def next(self):
        tok = self.toks[self.pos]
        self.pos += 1
        return tok

    def accept(self, text):
        if self.t() == text and self.kind() in ("op", "id"):
            self.pos += 1
            return True
        return False

    def expect(self, text):
        if not self.accept(text):
            raise Unsupported(f"line {self.line()}: expected '{text}' near '{self.t()}'")

    def expect_id(self):
        if self.kind() != "id":
            raise Unsupported(f"line {self.line()}: expected a name near '{self.t()}'")
        return self.next()[1]

    # -- types / declarators ----------------------------------------------------
    def parse_type_spec(self):
        if self.t() in ("struct", "union", "typedef"):
            raise Unsupported(f"'{self.t()}' (struct / union / typedef)")
        words = []
        while self.t() in _TYPE_KW and self.kind() == "id":
            words.append(self.next()[1])
        if not words:
            raise Unsupported(f"line {self.line()}: unknown type near '{self.t()}'")
        self.static_flag = "static" in words
        ws = [w for w in words if w not in _QUALS]
        if "double" in ws:
            return "double"
        if "float" in ws:
            return "float"
        if "void" in ws:
            return "void"
        if "char" in ws:
            base = "char"
        elif "short" in ws:
            base = "short"
        elif ws.count("long") >= 2:
            base = "llong"
        elif "long" in ws:
            base = "long"
        else:
            base = "int"
        return ("u" + base) if "unsigned" in ws else base

    def parse_declarator(self):
        stars = 0
        while self.accept("*"):
            stars += 1
            while self.t() in ("const", "volatile", "restrict"):
                self.next()
        if self.t() in (",", ")"):                                # unnamed parameter: int *
            return {"name": "_anon", "stars": stars, "dims": [], "fptr": False}
        if self.t() == "(" and self.t(1) == "*":                 # int (*fp)(int)
            self.next(); self.next()
            name = self.expect_id()
            self.expect(")")
            self.skip_parens()
            return {"name": name, "stars": 1, "dims": [], "fptr": True}
        name = self.expect_id()
        dims = []
        while self.accept("["):
            dims.append(None if self.t() == "]" else self.parse_ternary())
            self.expect("]")
        return {"name": name, "stars": stars, "dims": dims, "fptr": False}

    def skip_parens(self):
        self.expect("(")
        depth = 1
        while depth:
            tok = self.next()[1]
            depth += tok == "("
            depth -= tok == ")"

    def parse_initializer(self):
        if self.accept("{"):
            items = []
            while self.t() != "}":
                items.append(self.parse_initializer())
                if not self.accept(","):
                    break
            self.expect("}")
            return ("initlist", items)
        return self.parse_assign()

    def parse_decl(self):
        base = self.parse_type_spec()
        static = self.static_flag
        items = []
        while True:
            d = self.parse_declarator()
            vtype = "ptr" if (d["stars"] or d["fptr"]) else base
            init = self.parse_initializer() if self.accept("=") else None
            items.append((d["name"], vtype, d["dims"], init))
            if not self.accept(","):
                break
        self.expect(";")
        return ("decl", static, items)

    def parse_enum(self):
        self.next()
        if self.kind() == "id":
            self.next()
        self.expect("{")
        value = 0
        while self.t() != "}":
            name = self.expect_id()
            if self.accept("="):
                node = self.parse_ternary()
                value = Interp({}, {}, self.enums).ev(node, None)
            self.enums[name] = value
            value += 1
            if not self.accept(","):
                break
        self.expect("}")
        self.accept(";")

    def parse_params(self):
        self.expect("(")
        params = []
        if self.t() == "void" and self.t(1) == ")":
            self.next()
        while self.t() != ")":
            if self.t() == "...":
                raise Unsupported("variadic functions")
            base = self.parse_type_spec()
            d = self.parse_declarator() if self.t() not in (",", ")") else {"name": f"_p{len(params)}", "stars": 0, "dims": [], "fptr": False}
            ptype = "ptr" if (d["stars"] or d["fptr"] or d["dims"]) else base
            params.append((d["name"], ptype))
            if not self.accept(","):
                break
        self.expect(")")
        return params

    # -- program ------------------------------------------------------------------
    def parse_program(self):
        funcs, globals_ = {}, []
        while self.pos < len(self.toks):
            if self.accept(";"):
                continue
            if self.t() == "enum":
                self.parse_enum()
                continue
            save = self.pos
            base = self.parse_type_spec()
            stars = 0
            while self.t() == "*":
                self.next(); stars += 1
            if self.kind() == "id" and self.t(1) == "(":
                name = self.next()[1]
                params = self.parse_params()
                if self.t() == "{":
                    funcs[name] = ("ptr" if stars else base, params, self.parse_block())
                else:
                    self.expect(";")                       # prototype
                continue
            self.pos = save
            globals_.append(self.parse_decl())
        return funcs, globals_, self.enums

    # -- statements -----------------------------------------------------------------
    def parse_block(self):
        self.expect("{")
        stmts = []
        while self.t() != "}":
            if self.pos >= len(self.toks):
                raise Unsupported("unexpected end of file")
            stmts.append(self.parse_stmt())
        self.expect("}")
        return ("block", stmts)

    def parse_stmt(self):
        t = self.t()
        if self.kind() == "op":
            if t == "{":
                return self.parse_block()
            if t == ";":
                self.next()
                return ("empty",)
        if self.kind() == "id":
            if t == "if":
                self.next(); self.expect("(")
                cond = self.parse_comma(); self.expect(")")
                then = self.parse_stmt()
                other = self.parse_stmt() if self.accept("else") else None
                return ("if", cond, then, other)
            if t == "while":
                self.next(); self.expect("(")
                cond = self.parse_comma(); self.expect(")")
                return ("while", cond, self.parse_stmt())
            if t == "do":
                self.next()
                body = self.parse_stmt()
                self.expect("while"); self.expect("(")
                cond = self.parse_comma(); self.expect(")"); self.expect(";")
                return ("dowhile", body, cond)
            if t == "for":
                self.next(); self.expect("(")
                if self.accept(";"):
                    init = None
                elif self.t() in _TYPE_KW:
                    init = self.parse_decl()
                else:
                    init = ("expr", self.parse_comma()); self.expect(";")
                cond = None if self.t() == ";" else self.parse_comma()
                self.expect(";")
                incr = None if self.t() == ")" else self.parse_comma()
                self.expect(")")
                return ("for", init, cond, incr, self.parse_stmt())
            if t == "return":
                self.next()
                e = None if self.t() == ";" else self.parse_comma()
                self.expect(";")
                return ("return", e)
            if t in ("break", "continue"):
                self.next(); self.expect(";")
                return (t,)
            if t == "switch":
                self.next(); self.expect("(")
                e = self.parse_comma(); self.expect(")"); self.expect("{")
                items = []
                while self.t() != "}":
                    if self.accept("case"):
                        v = self.parse_ternary(); self.expect(":")
                        items.append(("case", v))
                    elif self.accept("default"):
                        self.expect(":")
                        items.append(("default",))
                    else:
                        items.append(self.parse_stmt())
                self.expect("}")
                return ("switch", e, items)
            if t == "goto":
                raise Unsupported("goto")
            if t == "enum":
                self.parse_enum()
                return ("empty",)
            if t in _TYPE_KW or t in ("struct", "union", "typedef"):
                return self.parse_decl()
        e = self.parse_comma()
        self.expect(";")
        return ("expr", e)

    # -- expressions ----------------------------------------------------------------------
    def parse_comma(self):
        e = self.parse_assign()
        if self.t() == ",":
            parts = [e]
            while self.accept(","):
                parts.append(self.parse_assign())
            return ("comma", parts)
        return e

    def parse_assign(self):
        left = self.parse_ternary()
        if self.kind() == "op" and self.t() in _ASSIGN_OPS:
            op = self.next()[1]
            return ("assign", op, left, self.parse_assign())
        return left

    def parse_ternary(self):
        cond = self.parse_binary(0)
        if self.kind() == "op" and self.t() == "?":
            self.next()
            a = self.parse_comma()
            self.expect(":")
            return ("tern", cond, a, self.parse_ternary())
        return cond

    def parse_binary(self, level):
        if level == len(_BIN_LEVELS):
            return self.parse_unary()
        left = self.parse_binary(level + 1)
        while self.kind() == "op" and self.t() in _BIN_LEVELS[level]:
            op = self.next()[1]
            right = self.parse_binary(level + 1)
            left = ("logic" if op in ("&&", "||") else "bin", op, left, right)
        return left

    def parse_unary(self):
        t = self.t()
        if self.kind() == "op":
            if t in ("-", "+", "!", "~"):
                self.next()
                return ("unary", t, self.parse_unary())
            if t == "*":
                self.next()
                return ("deref", self.parse_unary())
            if t == "&":
                self.next()
                return ("addr", self.parse_unary())
            if t in ("++", "--"):
                self.next()
                return ("incdec", t, True, self.parse_unary())
            if t == "(" and (self.t(1) in _TYPE_KW or self.t(1) in ("struct", "union")) and self.kind(1) == "id":
                self.next()
                base = self.parse_type_spec()
                stars = 0
                while self.accept("*"):
                    stars += 1
                self.expect(")")
                return ("cast", "ptr" if stars else base, self.parse_unary())
        if self.kind() == "id" and t == "sizeof":
            self.next()
            if self.t() == "(" and self.t(1) in _TYPE_KW and self.kind(1) == "id":
                self.next()
                base = self.parse_type_spec()
                stars = 0
                while self.accept("*"):
                    stars += 1
                self.expect(")")
                return ("num", SIZEOF["ptr" if stars else base] if (stars or base in SIZEOF) else 1)
            return ("sizeof", self.parse_unary())
        return self.parse_postfix()

    def parse_postfix(self):
        e = self.parse_primary()
        while self.kind() == "op":
            t = self.t()
            if t == "[":
                self.next()
                idx = self.parse_comma()
                self.expect("]")
                e = ("index", e, idx)
            elif t == "(":
                self.next()
                args = []
                while self.t() != ")":
                    args.append(self.parse_assign())
                    if not self.accept(","):
                        break
                self.expect(")")
                e = ("call", e, args)
            elif t in ("++", "--"):
                self.next()
                e = ("incdec", t, False, e)
            elif t in (".", "->"):
                raise Unsupported("struct member access")
            else:
                break
        return e

    def parse_primary(self):
        if self.pos >= len(self.toks):
            raise Unsupported("unexpected end of file")
        kind, text, _line = self.toks[self.pos]
        if kind == "int":
            self.next()
            digits = text.rstrip("uUlL")
            if digits[:2] in ("0x", "0X"):
                return ("num", int(digits, 16))
            return ("num", int(digits, 8) if len(digits) > 1 and digits[0] == "0" else int(digits))
        if kind == "float":
            self.next()
            return ("num", float(text.rstrip("fFlL")))
        if kind == "chr":
            self.next()
            return ("num", _decode_string(text[1:-1])[0])
        if kind == "str":
            codes = []
            while self.kind() == "str":
                codes += _decode_string(self.next()[1][1:-1])
            return ("str", codes)
        if kind == "id":
            self.next()
            return ("var", text)
        if text == "(":
            self.next()
            e = self.parse_comma()
            self.expect(")")
            return e
        raise Unsupported(f"line {self.line()}: unexpected '{text}'")


# ---------------------------------------------------------------------------
# evaluator
# ---------------------------------------------------------------------------
class Frame:
    __slots__ = ("scopes",)

    def __init__(self):
        self.scopes = [{}]


_FMT_RE = re.compile(r"%([-+ 0#]*)(\*|\d+)?(?:\.(\*|\d+))?(hh|h|ll|l|z|j|t|L)?([diouxXcsfFeEgGp%])")


class Interp:
    MAX_STEPS = 30_000_000
    MAX_OUTPUT = 100_000
    MAX_DEPTH = 2500

    def __init__(self, funcs, globals_, enums, deadline=None):
        self.funcs, self.enums, self.deadline = funcs, enums, deadline
        self.globals = {}
        self.statics = {}
        self.out = []
        self.out_len = 0
        self.steps = 0
        self.depth = 0
        self.global_decls = globals_

    # -- running ---------------------------------------------------------------------
    def run_main(self):
        fr = Frame()
        for decl in self.global_decls:
            self.exec(decl, fr, glob=True)
        if "main" not in self.funcs:
            raise CRuntimeError("no main() function to run")
        try:
            return self.call("main", [])
        except _Exit as e:
            return e.code

    def emit(self, s):
        if self.out_len < self.MAX_OUTPUT:
            self.out.append(s)
            self.out_len += len(s)
            if self.out_len >= self.MAX_OUTPUT:
                self.out.append("\n...[output truncated]")

    def tick(self):
        self.steps += 1
        if self.steps & 1023 == 0:
            if self.steps > self.MAX_STEPS or (self.deadline and time.time() > self.deadline):
                raise _Timeout()

    # -- variables ---------------------------------------------------------------------
    def lookup(self, name, fr):
        if fr is not None:
            for scope in reversed(fr.scopes):
                if name in scope:
                    return scope[name]
        return self.globals.get(name)

    def declare(self, name, vtype, dims, init, fr, glob):
        if dims:
            sizes = [None if d is None else self.ev(d, fr) for d in dims]
            if sizes[0] is None:
                if init is None:
                    raise CRuntimeError(f"array '{name}' has no size")
                sizes[0] = len(self._str_codes(init)) + 1 if self._is_str(init) else len(init[1])
            if any(s is None or s < 0 or s > 5_000_000 for s in sizes):
                raise CRuntimeError(f"bad array size for '{name}'")
            arr = self.make_array(sizes, vtype)
            if init is not None:
                self.fill(arr, init, fr)
            cell = Arr([arr])
            cell.et = "ptr"
        else:
            cell = Arr([0.0 if vtype in ("float", "double") else 0])
            cell.et = vtype
            if init is not None:
                cell[0] = coerce(self.ev(init, fr), vtype)
        (self.globals if glob else fr.scopes[-1])[name] = cell
        return cell

    def make_array(self, sizes, et):
        if len(sizes) == 1:
            a = Arr([0.0 if et in ("float", "double") else 0] * sizes[0])
            a.et = et
            return a
        a = Arr(self.make_array(sizes[1:], et) for _ in range(sizes[0]))
        a.et = "ptr"
        return a

    @staticmethod
    def _is_str(init):
        return init[0] == "str"

    @staticmethod
    def _str_codes(init):
        return init[1]

    def fill(self, arr, init, fr):
        if init[0] == "str":
            for i, c in enumerate(init[1] + [0]):
                if i < len(arr):
                    arr[i] = c
            return
        for i, item in enumerate(init[1]):
            if i >= len(arr):
                break
            if isinstance(arr[i], Arr) and item[0] in ("initlist", "str"):
                self.fill(arr[i], item, fr)
            else:
                arr[i] = coerce(self.ev(item, fr), arr.et)

    # -- calls ---------------------------------------------------------------------------------
    def call(self, name, args):
        ret_type, params, body = self.funcs[name]
        if len(args) != len(params):
            raise CRuntimeError(f"wrong number of arguments in call to {name}()")
        self.depth += 1
        if self.depth > self.MAX_DEPTH:
            raise CRuntimeError("stack overflow (recursion is too deep)")
        self.tick()
        fr = Frame()
        for (pname, ptype), val in zip(params, args):
            cell = Arr([coerce(val, ptype)])
            cell.et = ptype
            fr.scopes[0][pname] = cell
        try:
            self.exec(body, fr)
            result = 0
        except _Return as r:
            result = r.value
        finally:
            self.depth -= 1
        return result if ret_type == "void" else coerce(result, ret_type)

    # -- statements ---------------------------------------------------------------------------------
    def exec(self, node, fr, glob=False):
        self.tick()
        k = node[0]
        if k == "expr":
            self.ev(node[1], fr)
        elif k == "decl":
            for name, vtype, dims, init in node[2]:
                if node[1] and not glob:                      # static local
                    key = (id(node), name)
                    if key not in self.statics:
                        self.statics[key] = self.declare(name, vtype, dims, init, fr, False)
                    else:
                        fr.scopes[-1][name] = self.statics[key]
                else:
                    self.declare(name, vtype, dims, init, fr, glob)
        elif k == "block":
            fr.scopes.append({})
            try:
                for s in node[1]:
                    self.exec(s, fr)
            finally:
                fr.scopes.pop()
        elif k == "if":
            if truth(self.ev(node[1], fr)):
                self.exec(node[2], fr)
            elif node[3] is not None:
                self.exec(node[3], fr)
        elif k == "while":
            while truth(self.ev(node[1], fr)):
                try:
                    self.exec(node[2], fr)
                except _Break:
                    break
                except _Continue:
                    pass
        elif k == "dowhile":
            while True:
                try:
                    self.exec(node[1], fr)
                except _Break:
                    break
                except _Continue:
                    pass
                if not truth(self.ev(node[2], fr)):
                    break
        elif k == "for":
            fr.scopes.append({})
            try:
                if node[1] is not None:
                    self.exec(node[1], fr)
                while node[2] is None or truth(self.ev(node[2], fr)):
                    try:
                        self.exec(node[4], fr)
                    except _Break:
                        break
                    except _Continue:
                        pass
                    if node[3] is not None:
                        self.ev(node[3], fr)
            finally:
                fr.scopes.pop()
        elif k == "return":
            raise _Return(0 if node[1] is None else self.ev(node[1], fr))
        elif k == "break":
            raise _Break()
        elif k == "continue":
            raise _Continue()
        elif k == "switch":
            self.exec_switch(node, fr)
        elif k == "empty":
            pass
        else:
            raise Unsupported(f"statement '{k}'")

    def exec_switch(self, node, fr):
        value = self.ev(node[1], fr)
        items, start = node[2], None
        for i, it in enumerate(items):
            if it[0] == "case" and self.ev(it[1], fr) == value:
                start = i
                break
        if start is None:
            start = next((i for i, it in enumerate(items) if it[0] == "default"), None)
        if start is None:
            return
        fr.scopes.append({})
        try:
            for it in items[start:]:
                if it[0] not in ("case", "default"):
                    self.exec(it, fr)
        except _Break:
            pass
        finally:
            fr.scopes.pop()

    # -- expressions ---------------------------------------------------------------------------------
    def ev(self, node, fr):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "var":
            return self.read_var(node[1], fr)
        if k == "bin":
            return self.binop(node[1], self.ev(node[2], fr), self.ev(node[3], fr))
        if k == "assign":
            return self.assign(node, fr)
        if k == "call":
            return self.eval_call(node, fr)
        if k == "index":
            cont, key = self.lval(node, fr)
            return cont[key]
        if k == "logic":
            left = truth(self.ev(node[2], fr))
            if node[1] == "&&":
                return int(left and truth(self.ev(node[3], fr)))
            return int(left or truth(self.ev(node[3], fr)))
        if k == "unary":
            v = self.ev(node[2], fr)
            op = node[1]
            if op == "-":
                return -v
            if op == "+":
                return v
            if op == "!":
                return int(not truth(v))
            return ~v
        if k == "incdec":
            cont, key = self.lval(node[3], fr)
            old = cont[key]
            step = 1 if node[1] == "++" else -1
            if isinstance(old, (Ptr, Arr)):
                pc, po = self.ptr_parts(old)
                new = Ptr(pc, po + step)
            else:
                new = old + step
            cont[key] = coerce(new, cont.et)
            return cont[key] if node[2] else old
        if k == "tern":
            return self.ev(node[2] if truth(self.ev(node[1], fr)) else node[3], fr)
        if k == "str":
            a = Arr(node[1] + [0])
            a.et = "char"
            return a
        if k == "cast":
            return coerce(self.ev(node[2], fr), node[1])
        if k == "deref":
            v = self.ev(node[1], fr)
            if isinstance(v, FuncRef):
                return v
            cont, key = self.ptr_parts(v)
            self.check_bounds(cont, key)
            return cont[key]
        if k == "addr":
            target = node[1]
            if target[0] == "var" and self.lookup(target[1], fr) is None and target[1] in self.funcs:
                return FuncRef(target[1])
            cont, key = self.lval(target, fr)
            return Ptr(cont, key)
        if k == "comma":
            v = 0
            for part in node[1]:
                v = self.ev(part, fr)
            return v
        if k == "sizeof":
            target = node[1]
            if target[0] == "var":
                cell = self.lookup(target[1], fr)
                if cell is not None:
                    v = cell[0]
                    if isinstance(v, Arr):
                        return len(v) * SIZEOF.get(v.et, 8)
                    return SIZEOF.get(cell.et, 8)
            return 4
        raise Unsupported(f"expression '{k}'")

    def read_var(self, name, fr):
        cell = self.lookup(name, fr)
        if cell is not None:
            return cell[0]
        if name in self.enums:
            return self.enums[name]
        if name in self.funcs:
            return FuncRef(name)
        if name == "NULL":
            return 0
        raise CRuntimeError(f"'{name}' is not declared")

    @staticmethod
    def ptr_parts(v):
        if isinstance(v, Arr):
            return v, 0
        if isinstance(v, Ptr):
            return v.cont, v.idx
        raise CRuntimeError("invalid pointer / array access (null or non-pointer value)")

    @staticmethod
    def check_bounds(cont, key):
        if key < 0 or key >= len(cont):
            raise CRuntimeError("out-of-bounds memory access")

    def lval(self, node, fr):
        k = node[0]
        if k == "var":
            cell = self.lookup(node[1], fr)
            if cell is None:
                raise CRuntimeError(f"'{node[1]}' is not declared")
            return cell, 0
        if k == "index":
            base, idx = self.ev(node[1], fr), self.ev(node[2], fr)
            cont, off = self.ptr_parts(base)
            key = off + int(idx)
            self.check_bounds(cont, key)
            return cont, key
        if k == "deref":
            cont, key = self.ptr_parts(self.ev(node[1], fr))
            self.check_bounds(cont, key)
            return cont, key
        raise CRuntimeError("invalid assignment target")

    def assign(self, node, fr):
        op, target, rhs = node[1], node[2], node[3]
        value = self.ev(rhs, fr)
        cont, key = self.lval(target, fr)
        if op != "=":
            value = self.binop(op[:-1], cont[key], value)
        cont[key] = coerce(value, cont.et)
        return cont[key]

    def binop(self, op, a, b):
        pa, pb = isinstance(a, (Ptr, Arr)), isinstance(b, (Ptr, Arr))
        if pa or pb:
            if op == "+" and pa and not pb:
                cont, off = self.ptr_parts(a); return Ptr(cont, off + int(b))
            if op == "+" and pb and not pa:
                cont, off = self.ptr_parts(b); return Ptr(cont, off + int(a))
            if op == "-" and pa and not pb:
                cont, off = self.ptr_parts(a); return Ptr(cont, off - int(b))
            if op == "-" and pa and pb:
                return self.ptr_parts(a)[1] - self.ptr_parts(b)[1]
            if op in ("==", "!="):
                same = (a == b) if not (isinstance(a, Arr) or isinstance(b, Arr)) else (a is b)
                return int(same == (op == "=="))
            if op in ("<", ">", "<=", ">=") and pa and pb:
                a, b = self.ptr_parts(a)[1], self.ptr_parts(b)[1]
            else:
                raise CRuntimeError("unsupported pointer arithmetic")
        if op == "+": return a + b
        if op == "-": return a - b
        if op == "*": return a * b
        if op == "/": return self.divide(a, b)
        if op == "%": return self.modulo(a, b)
        if op == "==": return int(a == b)
        if op == "!=": return int(a != b)
        if op == "<": return int(a < b)
        if op == ">": return int(a > b)
        if op == "<=": return int(a <= b)
        if op == ">=": return int(a >= b)
        if op == "&": return a & b
        if op == "|": return a | b
        if op == "^": return a ^ b
        if op == "<<": return a << b if 0 <= b < 64 else 0
        if op == ">>": return a >> b if 0 <= b < 64 else 0
        raise Unsupported(f"operator {op}")

    @staticmethod
    def divide(a, b):
        if isinstance(a, float) or isinstance(b, float):
            if b == 0:
                return math.nan if a == 0 or a != a else math.copysign(math.inf, a)
            return a / b
        if b == 0:
            raise CRuntimeError("division by zero")
        q = abs(a) // abs(b)
        return q if (a < 0) == (b < 0) else -q

    @staticmethod
    def modulo(a, b):
        if isinstance(a, float) or isinstance(b, float):
            return math.fmod(a, b) if b != 0 else math.nan
        if b == 0:
            raise CRuntimeError("division by zero")
        return a - b * Interp.divide(a, b)

    # -- calls (user functions and library) -------------------------------------------------------------------
    def eval_call(self, node, fr):
        fnode, argnodes = node[1], node[2]
        name = None
        if fnode[0] == "var" and self.lookup(fnode[1], fr) is None:
            name = fnode[1]
        else:
            f = self.ev(fnode, fr)
            if isinstance(f, FuncRef):
                name = f.name
            else:
                raise CRuntimeError("call through an invalid function pointer")
        args = [self.ev(a, fr) for a in argnodes]
        if name in self.funcs:
            return self.call(name, args)
        return self.library(name, args)

    def library(self, name, a):
        if name == "printf":
            self.emit(self.format(a))
            return 0
        if name == "puts":
            self.emit(self.cstr(a[0]) + "\n"); return 0
        if name == "putchar":
            self.emit(chr(a[0] & 0xFF)); return a[0]
        if name == "strlen":
            return len(self.cstr(a[0]))
        if name == "strcmp":
            x, y = self.cstr(a[0]), self.cstr(a[1])
            return (x > y) - (x < y)
        if name in ("abs", "labs", "llabs"):
            return abs(a[0])
        if name == "exit":
            raise _Exit(a[0] if a else 0)
        math_funcs = {"sqrt": math.sqrt, "pow": math.pow, "fabs": math.fabs, "floor": math.floor,
                      "ceil": math.ceil, "sin": math.sin, "cos": math.cos, "tan": math.tan,
                      "exp": math.exp, "log": math.log, "log10": math.log10, "fmod": math.fmod}
        if name in math_funcs:
            try:
                r = math_funcs[name](*[float(x) for x in a])
            except (ValueError, OverflowError):
                return math.nan
            return float(r)
        raise Unsupported(f"library function '{name}()'")

    def cstr(self, v):
        cont, off = self.ptr_parts(v)
        chars = []
        for c in cont[off:]:
            if c == 0:
                break
            chars.append(chr(c & 0xFF))
        return "".join(chars)

    def format(self, args):
        fmt, rest, pos = self.cstr(args[0]), args[1:], [0]

        def take():
            if pos[0] >= len(rest):
                raise CRuntimeError("printf: not enough arguments for format string")
            pos[0] += 1
            return rest[pos[0] - 1]

        def repl(m):
            flags, width, prec, length, conv = m.groups()
            if conv == "%":
                return "%"
            if width == "*":
                width = str(take())
            if prec == "*":
                prec = str(take())
            spec = "%" + flags + (width or "") + ("." + prec if prec is not None else "")
            v = take()
            wide = length in ("l", "ll", "z", "j", "t")
            if conv in "di":
                return (spec + "d") % _wrap(int(v), 64 if wide else 32, True)
            if conv in "uxXo":
                return (spec + ("d" if conv == "u" else conv)) % _wrap(int(v), 64 if wide else 32, False)
            if conv == "c":
                return (spec + "s") % chr(int(v) & 0xFF)
            if conv == "s":
                return (spec + "s") % self.cstr(v)
            if conv == "p":
                return "0x%x" % (id(v) & 0xFFFFFFFF)
            f = float(v)
            if f != f or f in (math.inf, -math.inf):
                text = "nan" if f != f else ("inf" if f > 0 else "-inf")
                return (spec.split(".")[0].replace("0", "") + "s") % text
            return (spec + conv) % f

        return _FMT_RE.sub(repl, fmt)


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def run_program(code: str, time_limit: float = 5.0) -> dict:
    """Run C source with the built-in interpreter.

    Returns {"status": "ok" | "runtime_error" | "unsupported" | "timeout",
             "stdout": str, "exit_code": int | None, "error": str | None}
    """
    box = {}

    def target():
        interp = None
        try:
            funcs, globals_, enums = Parser(code).parse_program()
            interp = Interp(funcs, globals_, enums, time.time() + time_limit)
            interp.enums = enums
            exit_code = interp.run_main()
            box.update(status="ok", exit_code=int(exit_code) if isinstance(exit_code, (int, float)) else 0,
                       error=None)
        except Unsupported as e:
            box.update(status="unsupported", exit_code=None,
                       error=f"The built-in runner does not support: {e}. Install gcc to run this program.")
        except CRuntimeError as e:
            box.update(status="runtime_error", exit_code=None, error=f"Runtime error: {e}")
        except _Timeout:
            box.update(status="timeout", exit_code=None,
                       error=f"The program ran longer than {time_limit:.0f} seconds and was stopped "
                             "(possible infinite loop).")
        except RecursionError:
            box.update(status="runtime_error", exit_code=None, error="Runtime error: stack overflow")
        except Exception as e:  # pragma: no cover - safety net
            box.update(status="runtime_error", exit_code=None, error=f"Internal runner error: {e}")
        box["stdout"] = "".join(interp.out) if interp else ""

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(120000)
    try:
        threading.stack_size(256 * 1024 * 1024)
    except (ValueError, RuntimeError):
        try:
            threading.stack_size(64 * 1024 * 1024)
        except (ValueError, RuntimeError):
            pass
    try:
        th = threading.Thread(target=target, daemon=True)
        th.start()
        th.join(time_limit + 3)
    finally:
        sys.setrecursionlimit(old_limit)
        try:
            threading.stack_size(0)
        except (ValueError, RuntimeError):
            pass
    if th.is_alive():
        return {"status": "timeout", "stdout": "", "exit_code": None,
                "error": f"The program ran longer than {time_limit:.0f} seconds and was stopped."}
    return box