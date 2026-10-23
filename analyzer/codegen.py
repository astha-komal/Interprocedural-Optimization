"""
codegen.py
----------
Module 3: optimized-code generation.

Takes the results of the existing analysis (call graph, recursion info,
reachability, constant-propagation and inline decisions) and rewrites the
ORIGINAL C source accordingly. The analysis itself is not changed.

Transformations, in order:

  1. CONSTANT_FOLD  a direct call whose arguments are all numeric literals and
                    whose callee is a single `return <expr>;` function is
                    replaced by its computed value:   square(5)  ->  25
  2. INLINE         a direct call to a function the analyzer marked INLINE
                    (and whose body is a single pure `return <expr>;`) is
                    replaced by the callee's expression with the arguments
                    substituted:                      add(n, 2)  ->  (n + 2)
  3. DEAD CODE      functions that are unreachable from the entry point, or
                    that no longer have any reference after (1) and (2), are
                    removed (only when the entry point exists).

Steps 1-2 are repeated until nothing changes, so folded results can expose
further folds/inlines.

Safety rules (the generator is deliberately conservative):
  * recursive functions are never inlined or folded;
  * only single-`return` functions with side-effect-free expressions that use
    nothing but their own parameters are touched;
  * an argument with side effects (i++, f(), x = 1) is only inlined if the
    parameter is used exactly once in the callee;
  * division / modulo are never constant-folded (C integer semantics differ
    from Python's); they can still be inlined as C expressions;
  * a function is only removed if no reference to it remains in the code
    (so functions used through pointers or tables are kept);
  * comments and string literals are never modified.
"""
import re
from dataclasses import dataclass

from .extraction import _FUNC_SIG_RE, _CONTROL_KEYWORDS, find_matching_brace
from .optimization import (
    _NUMERIC_LITERAL_RE,
    _UnsupportedExpression,
    _extract_simple_return_expr,
    _safe_eval_arithmetic,
)

# ---------------------------------------------------------------------------
# Masking: hide comments / strings / char literals so regex rewriting can
# never touch them.  They are restored at the very end.
# ---------------------------------------------------------------------------
_MASK_RE = re.compile(
    r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.DOTALL
)
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")


def _mask(code: str):
    table = []

    def rep(m):
        table.append(m.group(0))
        return f"\x00{len(table) - 1}\x00"

    return _MASK_RE.sub(rep, code), table


def _unmask(text: str, table) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: table[int(m.group(1))], text)


# ---------------------------------------------------------------------------
# Locating function definitions in (masked) source
# ---------------------------------------------------------------------------
@dataclass
class _Span:
    name: str
    start: int       # start of the whole definition (incl. return type)
    body_start: int  # index of '{'
    body_end: int    # index just past the matching '}'
    end: int         # body_end plus a trailing newline, if any


def _locate_functions(text: str):
    spans = []
    last_end = 0
    for m in _FUNC_SIG_RE.finditer(text):
        if m.start() < last_end:
            continue  # match inside an already-accepted function body
        name = m.group("name")
        ret = m.group("ret").strip()
        if name in _CONTROL_KEYWORDS:
            continue
        if ret and ret.split()[-1] in _CONTROL_KEYWORDS:
            continue
        brace_start = m.end() - 1
        brace_end = find_matching_brace(text, brace_start)
        if brace_end == -1:
            continue

        # definition start = start of the line holding the name (the regex's
        # own start can swallow preprocessor lines, so it is not used)
        name_start = m.start("name")
        start = text.rfind("\n", 0, name_start) + 1
        cut = max(text.rfind(";", start, name_start), text.rfind("}", start, name_start))
        if cut != -1:
            start = cut + 1
        else:
            # return type alone on the previous line ("static int\nfoo(...)")
            prev_end = start - 1
            if prev_end > 0:
                prev_start = text.rfind("\n", 0, prev_end) + 1
                prev = text[prev_start:prev_end].strip()
                if prev and re.fullmatch(r"[A-Za-z_][\w\s\*]*", prev):
                    start = prev_start
        start = max(start, last_end)

        body_end = brace_end + 1
        end = body_end + 1 if text[body_end:body_end + 1] == "\n" else body_end
        spans.append(_Span(name, start, brace_start, body_end, end))
        last_end = end
    return spans


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------
def _find_close_paren(text: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_args(inner: str):
    pieces, depth, cur = [], 0, []
    for ch in inner:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            pieces.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    pieces.append("".join(cur))
    return pieces


_ATOM_RE = re.compile(r"[A-Za-z_]\w*|\d+(\.\d+)?|\x00\d+\x00")


def _wrap(s: str) -> str:
    """Parenthesize an expression unless it is already atomic."""
    s = s.strip()
    if _ATOM_RE.fullmatch(s):
        return s
    if s.startswith("(") and _find_close_paren(s, 0) == len(s) - 1:
        return s
    return f"({s})"


def _subst(expr: str, mapping: dict) -> str:
    """Simultaneous (not sequential) identifier substitution."""
    return re.sub(r"[A-Za-z_]\w*", lambda m: mapping.get(m.group(0), m.group(0)), expr)


def _has_side_effects(arg: str) -> bool:
    return bool(re.search(r"\+\+|--|(?<![=!<>])=(?!=)|[A-Za-z_]\w*\s*\(", arg))


# ---------------------------------------------------------------------------
# Which functions are simple enough to fold / inline?
# ---------------------------------------------------------------------------
_TYPE_WORDS = {"int", "float", "double", "long", "short", "char", "unsigned", "signed"}
_QUALIFIERS = {"static", "inline", "extern", "const", "register", "volatile"}
_INT_TYPES = {"int", "long", "long int", "long long", "long long int"}
_FLOAT_TYPES = {"float", "double"}


def _clean_type(t: str) -> str:
    return " ".join(w for w in t.split() if w not in _QUALIFIERS)


def _is_pure_expr(expr: str, params) -> bool:
    if "++" in expr or "--" in expr or "->" in expr:
        return False
    if re.search(r"(?<![=!<>])=(?!=)", expr):          # assignment
        return False
    if re.search(r"(?<!&)&(?!&)", expr):                # address-of
        return False
    if re.search(r"[\[\]{};,]", expr):                  # indexing, comma operator
        return False
    if re.search(r"[A-Za-z_\)\]]\s*\.", expr):          # member access
        return False
    free = set(re.findall(r"[A-Za-z_]\w*", expr)) - set(params) - _TYPE_WORDS
    return not free                                     # nothing but own params


def _collect_simple_functions(functions: dict, recursive_functions: set) -> dict:
    """name -> (param_names, param_types, expr, return_kind, return_type)"""
    simple = {}
    for name, func in functions.items():
        if name in recursive_functions:
            continue
        expr = _extract_simple_return_expr(func.body)
        if expr is None:
            continue
        expr = re.sub(r"\s+", " ", expr).strip()
        ptypes = [_clean_type(t) for t, _n in func.parameters]
        pnames = [n for _t, n in func.parameters]
        if any(t not in _INT_TYPES | _FLOAT_TYPES for t in ptypes):
            continue
        ret = _clean_type(func.return_type)
        if ret in _INT_TYPES:
            rkind = "int"
        elif ret in _FLOAT_TYPES:
            rkind = "float"
        else:
            continue
        if not _is_pure_expr(expr, pnames):
            continue
        simple[name] = (pnames, ptypes, expr, rkind, ret)
    return simple


# ---------------------------------------------------------------------------
# Call-site rewriting
# ---------------------------------------------------------------------------
def _rewrite_calls(text: str, name: str, handler, record) -> str:
    """Replace calls `name(...)` in `text` using handler(args) -> str | None.
    Arguments are rewritten first, so nested calls work."""
    pat = re.compile(rf"(?<![\w.>]){re.escape(name)}\s*\(")
    out, pos = [], 0
    while True:
        m = pat.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        open_idx = m.end() - 1
        close_idx = _find_close_paren(text, open_idx)
        if close_idx == -1:
            out.append(text[pos:])
            break
        inner = text[open_idx + 1:close_idx]
        pieces = [_rewrite_calls(p, name, handler, record) for p in _split_args(inner)]
        args = [p.strip() for p in pieces] if inner.strip() else []

        repl = handler(args)
        out.append(text[pos:m.start()])
        if repl is None:
            out.append(text[m.start():open_idx + 1] + ",".join(pieces) + ")")
        else:
            record(text[m.start():close_idx + 1].strip(), repl)
            out.append(repl)
        pos = close_idx + 1
    return "".join(out)


def _make_fold_handler(info):
    pnames, ptypes, expr, rkind, rtype = info

    def handler(args):
        if len(args) != len(pnames):
            return None
        if "float" in ptypes or rtype == "float":   # single-precision rounding: leave to the compiler
            return None
        if not all(_NUMERIC_LITERAL_RE.match(a) for a in args):
            return None
        if re.search(r"[/%]|\*\*", expr):      # C vs Python division semantics
            return None
        for t, a in zip(ptypes, args):
            if "." in a and t not in _FLOAT_TYPES:
                return None
        try:
            value = _safe_eval_arithmetic(_subst(expr, dict(zip(pnames, args))))
        except (_UnsupportedExpression, SyntaxError, ZeroDivisionError, OverflowError):
            return None
        if rkind == "int":
            if not isinstance(value, int) or abs(value) > 2**31 - 1:
                return None
            text = str(value)
        else:
            text = repr(float(value))
        return f"({text})" if value < 0 else text

    return handler


def _make_inline_handler(info):
    pnames, ptypes, expr, rkind, rtype = info
    uses_float = rkind == "float" or any(t in _FLOAT_TYPES for t in ptypes)

    def handler(args):
        if len(args) != len(pnames):
            return None
        mapping = {}
        for p, t, a in zip(pnames, ptypes, args):
            if a == "":
                return None
            uses = len(re.findall(rf"\b{re.escape(p)}\b", expr))
            if _has_side_effects(a) and uses != 1:
                return None
            if t in _FLOAT_TYPES and not (t == "double" and "." in a and _NUMERIC_LITERAL_RE.match(a)):
                # the call converts the argument to float/double first (e.g. 5 -> 5.0),
                # so int/int division inside the callee stays a real division
                mapping[p] = f"(({t}){_wrap(a)})"
            else:
                mapping[p] = _wrap(a)
        inner = _wrap(_subst(expr, mapping))
        if uses_float:
            return f"(({rtype})({inner}))"       # result is converted to the return type
        return inner

    return handler


# ---------------------------------------------------------------------------
# Dead-function removal
# ---------------------------------------------------------------------------
def _strip_prototypes(gap: str, names) -> str:
    for n in sorted(names):
        gap = re.sub(
            rf"(?:(?<=^)|(?<=[;\n]))[ \t]*[A-Za-z_][\w \t\*]*?\b{re.escape(n)}\s*\([^;{{}}]*\)\s*;[ \t]*\n?",
            "", gap, flags=re.M,
        )
    return gap


def _rebuild(text: str, remove: set, annotate: bool = False, reasons: dict = None) -> str:
    """Return `text` with the definitions and prototypes of `remove` deleted."""
    out, pos = [], 0
    for sp in _locate_functions(text):
        out.append(_strip_prototypes(text[pos:sp.start], remove))
        if sp.name in remove:
            if annotate:
                out.append(f"/* [optimized away] {sp.name}(): {reasons[sp.name]} */\n")
        else:
            out.append(text[sp.start:sp.end])
        pos = sp.end
    out.append(_strip_prototypes(text[pos:], remove))
    return "".join(out)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def generate_optimized_code(code: str, functions: dict, opt_results: dict,
                            recursive_functions: set, reachable: set,
                            entry: str = "main", remove_dead_code: bool = True,
                            max_passes: int = 6) -> dict:
    text, table = _mask(code)
    simple = _collect_simple_functions(functions, recursive_functions)
    fold_handlers = {n: _make_fold_handler(i) for n, i in simple.items()}
    inline_handlers = {
        n: _make_inline_handler(i) for n, i in simple.items()
        if opt_results.get(n, {}).get("decision") == "INLINE"
    }

    transformations = []
    folded, inlined = set(), set()

    def make_recorder(kind, caller, callee):
        def record(before, after):
            transformations.append({
                "type": kind, "caller": caller, "callee": callee,
                "before": before, "after": after,
            })
            (folded if kind == "CONSTANT_FOLD" else inlined).add(callee)
        return record

    # -- 1 & 2: fold constants, inline calls, repeat until stable -----------
    for _ in range(max_passes):
        changed = False
        for sp in reversed(_locate_functions(text)):
            func = functions.get(sp.name)
            if func is None:
                continue
            body = text[sp.body_start:sp.body_end]
            new_body = body
            for callee in sorted(fold_handlers):
                if callee in func.direct_calls:
                    new_body = _rewrite_calls(new_body, callee, fold_handlers[callee],
                                              make_recorder("CONSTANT_FOLD", sp.name, callee))
            for callee in sorted(inline_handlers):
                if callee in func.direct_calls:
                    new_body = _rewrite_calls(new_body, callee, inline_handlers[callee],
                                              make_recorder("INLINE", sp.name, callee))
            if new_body != body:
                text = text[:sp.body_start] + new_body + text[sp.body_end:]
                changed = True
        if not changed:
            break

    # -- 3: remove dead / fully-inlined functions ---------------------------
    removed = []
    if remove_dead_code and entry in functions:
        reasons = {}
        for n in functions:
            if n not in reachable:
                reasons[n] = f"unreachable from {entry}()"
        for n in (folded | inlined):
            if n != entry and n not in reasons:
                reasons[n] = "all calls were inlined / constant-folded"
        candidates = set(reasons)
        while True:  # keep anything that is still referenced (e.g. via a pointer)
            stripped = _rebuild(text, candidates)
            referenced = {n for n in candidates if re.search(rf"\b{re.escape(n)}\b", stripped)}
            if not referenced:
                break
            candidates -= referenced
        if candidates:
            text = _rebuild(text, candidates, annotate=True, reasons=reasons)
            removed = [{"name": n, "reason": reasons[n]} for n in sorted(candidates)]

    text = re.sub(r"\n{3,}", "\n\n", text)
    optimized = _unmask(text, table)
    if not optimized.endswith("\n"):
        optimized += "\n"

    for t in transformations:
        t["before"] = _unmask(t["before"], table)
        t["after"] = _unmask(t["after"], table)

    return {
        "code": optimized,
        "changed": optimized.strip() != code.strip(),
        "transformations": transformations,
        "removed_functions": removed,
        "summary": {
            "constant_folds": sum(1 for t in transformations if t["type"] == "CONSTANT_FOLD"),
            "inlined_calls": sum(1 for t in transformations if t["type"] == "INLINE"),
            "functions_removed": len(removed),
            "original_lines": len(code.strip().splitlines()),
            "optimized_lines": len(optimized.strip().splitlines()),
        },
    }