"""
syntax_check.py
---------------
Compile-error detection that runs BEFORE any analysis or optimization.

    check_syntax(code) -> {"ok": bool, "checker": str, "errors": [ {line, message, snippet} ]}

Two checkers, used in this order:

  1. A real C compiler (gcc or clang), if one is on the PATH:
        gcc -fsyntax-only
     This is authoritative: it catches undeclared variables, type errors,
     missing headers, and everything else a compiler would.

  2. A built-in checker (no installation needed), used when no compiler is
     found. It catches the most common mistakes:
        - missing ';' at the end of a statement
        - unbalanced / mismatched  { }  ( )  [ ]
        - missing ')' before ';' or '{'
        - unterminated string / character literal and unterminated /* comment
        - code with no function definitions at all
     It is deliberately conservative: it would rather miss an error than
     reject valid code. It cannot catch semantic errors (undeclared names,
     wrong types) -- install gcc to catch those too.
"""
import re
import shutil
import subprocess

from .extraction import extract_functions

MAX_ERRORS = 10


# ---------------------------------------------------------------------------
# 1. real compiler
# ---------------------------------------------------------------------------
_COMPILER_LINE_RE = re.compile(
    r"^(?:<stdin>|-):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?:fatal )?error:\s*(?P<msg>.*)$"
)


def _compiler_check(code: str):
    """Returns a list of (line, message) or None if no usable compiler."""
    exe = shutil.which("gcc") or shutil.which("clang")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-fsyntax-only", "-x", "c", "-"],
            input=code, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
    except Exception:
        return None
    errors = []
    for ln in proc.stderr.splitlines():
        m = _COMPILER_LINE_RE.match(ln.strip())
        if m:
            msg = m.group("msg").replace("\u2018", "'").replace("\u2019", "'")
            errors.append((int(m.group("line")), msg))
    if proc.returncode != 0 and not errors:
        return None          # failed for a reason we cannot read -> fall back
    return errors


# ---------------------------------------------------------------------------
# 2. built-in checker
# ---------------------------------------------------------------------------
def _clean(code: str):
    """Blank out comments / strings / preprocessor lines, keeping line
    structure. Returns (clean_text, [(line, message)])."""
    out, errors = [], []
    i, n, line = 0, len(code), 1
    at_line_start = True
    while i < n:
        c = code[i]
        nx = code[i + 1] if i + 1 < n else ""
        if c == "\n":
            out.append("\n"); line += 1; i += 1; at_line_start = True
            continue
        if c in " \t\r":
            out.append(c); i += 1
            continue
        if c == "#" and at_line_start:                       # preprocessor line
            while i < n and code[i] != "\n":
                if code[i] == "\\" and i + 1 < n and code[i + 1] == "\n":
                    out.append("\n"); line += 1; i += 2
                    continue
                i += 1
            continue
        at_line_start = False
        if c == "/" and nx == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if c == "/" and nx == "*":
            start, i, closed = line, i + 2, False
            while i < n:
                if code[i] == "*" and i + 1 < n and code[i + 1] == "/":
                    i += 2; closed = True
                    break
                if code[i] == "\n":
                    out.append("\n"); line += 1
                i += 1
            if not closed:
                errors.append((start, "unterminated /* comment"))
            out.append(" ")
            continue
        if c in "\"'":
            j, closed = i + 1, False
            while j < n:
                if code[j] == "\\":
                    j += 2
                    continue
                if code[j] == c:
                    closed = True
                    break
                if code[j] == "\n":
                    break
                j += 1
            if not closed:
                kind = "string" if c == '"' else "character"
                errors.append((line, f"missing terminating {c} character ({kind} literal is not closed)"))
                out.append(c + c)
                i = j
                continue
            out.append(c + c)
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out), errors


_CLOSER = {"(": ")", "[": "]", "{": "}"}
_OPENER = {")": "(", "]": "[", "}": "{"}


def _bracket_errors(clean: str):
    errors, stack, line = [], [], 1
    for idx, ch in enumerate(clean):
        if ch == "\n":
            line += 1
        elif ch in "([{":
            if ch == "{" and stack and stack[-1][0] == "(":
                errors.append((line, "expected ')' before '{' token"))
                stack.pop()
            is_for = ch == "(" and re.search(r"\bfor\s*$", clean[max(0, idx - 12):idx]) is not None
            stack.append((ch, line, is_for))
        elif ch in ")]}":
            if not stack:
                errors.append((line, f"unexpected '{ch}' (no matching '{_OPENER[ch]}')"))
            elif stack[-1][0] == _OPENER[ch]:
                stack.pop()
            else:
                top = stack[-1]
                errors.append((line, f"expected '{_CLOSER[top[0]]}' before '{ch}' "
                                     f"('{top[0]}' opened on line {top[1]} is not closed)"))
                if any(s[0] == _OPENER[ch] for s in stack):
                    while stack[-1][0] != _OPENER[ch]:
                        stack.pop()
                    stack.pop()
        elif ch == ";" and stack and stack[-1][0] == "(" and not stack[-1][2]:
            errors.append((line, "expected ')' before ';' token"))
            stack.pop()
    for ch, ln, _f in stack:
        errors.append((ln, f"'{ch}' opened here is never closed (expected '{_CLOSER[ch]}')"))
    return errors


_CONTROL_RE = re.compile(r"(if|for|while|switch)\s*\(")
_MACRO_CALL_RE = re.compile(r"[A-Z_][A-Z0-9_]*\s*\(.*\)")
_CONTINUATION_START = tuple("+-*/%&|^=<>?:,.)]{")


def _needs_semicolon(text: str, nxt: str) -> bool:
    """True if this logical line should end with ';' but does not."""
    s = text.strip()
    if not s:
        return False
    last = s[-1]
    if last in ";{}:,":
        return False
    # several statements on one line: judge only the last one
    depth, cut = 0, -1
    for k, ch in enumerate(s):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and ch in ";{}":
            cut = k
    if cut != -1:
        tail = s[cut + 1:].strip()
        if not tail:
            return False
        s = ("} " if s[cut] == "}" else "") + tail
        last = s[-1]
    if last in "+-*/%&|^=<>?!~(." and not s.endswith(("++", "--")):
        return False                                     # expression continues
    core = s.lstrip("}").strip()
    if not core:
        return False
    if last == ")":
        tmp = core[4:].lstrip() if core.startswith("else") else core
        m = _CONTROL_RE.match(tmp)
        if m:
            depth, close = 0, -1
            for k in range(m.end() - 1, len(tmp)):
                depth += tmp[k] == "("
                depth -= tmp[k] == ")"
                if depth == 0:
                    close = k
                    break
            if close == -1:
                return False
            rest = tmp[close + 1:].strip()
            if rest == "":
                # `} while (x)` closes a do-while and needs ';'; any other header is fine
                return m.group(1) == "while" and s.startswith("}") and not core.startswith("else")
            if any(ch in rest for ch in ";{}"):
                return False                             # cannot judge reliably
            return _needs_semicolon(rest, nxt)
        return not _MACRO_CALL_RE.fullmatch(core)        # `foo(x)` / `x = f(y)` without ';'
    # line ends with an operand (identifier, number, ], string, char, i++ ...)
    if re.search(r"(^|\s)(else|do)$", core):
        return False
    if nxt and (nxt.startswith(_CONTINUATION_START) or nxt.startswith("->")):
        return False                                     # expression continues on next line
    return True


def _statement_errors(clean: str):
    """Missing-semicolon detection inside function bodies."""
    stack, prefix, pdepth, infos, errors = [], "", 0, [], []
    for lineno, text in enumerate(clean.split("\n"), 1):
        in_code = bool(stack) and stack[-1] in ("func", "block")
        at_top = not stack
        for pos, ch in enumerate(text):
            if ch in "([":
                pdepth += 1
            elif ch in ")]":
                pdepth = max(0, pdepth - 1)
            if ch == "{":
                p = prefix.rstrip()
                if stack and stack[-1] in ("init", "type"):
                    kind = stack[-1]
                elif p.endswith("="):
                    kind = "init"
                elif not stack:
                    kind = "func" if p.endswith(")") else "type"
                else:
                    kind = "block"
                stack.append(kind)
                prefix = ""
            elif ch == "}":
                # `{ return x }` : '}' right after an operand on the same line
                before = text[:pos].rstrip()
                if (stack and stack[-1] in ("func", "block") and before
                        and (before[-1].isalnum() or before[-1] in "_)]\"'")
                        and re.search(r"(^|[\s{};])(else|do)$", before) is None):
                    errors.append((lineno, "expected ';' before '}' token"))
                if stack:
                    stack.pop()
                prefix = ""
            elif ch == ";":
                prefix = ""
            else:
                prefix += ch
        prefix += " "
        if text.strip():
            infos.append((lineno, text.strip(), in_code, at_top, pdepth))

    logical, cur, first = [], [], (False, False)
    for lineno, text, in_code, at_top, pd in infos:
        if not cur:
            first = (in_code, at_top)
        cur.append(text)
        if pd == 0:
            logical.append((lineno, " ".join(cur), first[0], first[1]))
            cur = []

    for i, (lineno, text, in_code, at_top) in enumerate(logical):
        nxt = logical[i + 1][1] if i + 1 < len(logical) else ""
        if in_code:
            if _needs_semicolon(text, nxt):
                errors.append((lineno, "expected ';' at end of statement"))
        elif at_top and text.endswith(")") and not nxt.startswith("{"):
            # top level: a prototype / declaration ending in ')' must end with ';'
            # (a function header is followed by '{').  Macros and attributes are exempt.
            if not _MACRO_CALL_RE.fullmatch(text) and "__" not in text:
                errors.append((lineno, "expected ';' after declaration"))
    return errors


def _builtin_errors(code: str):
    code = code.replace("\r\n", "\n")
    clean, errors = _clean(code)
    errors += _bracket_errors(clean)
    if not errors:                       # statement checks are meaningless if brackets are broken
        errors += _statement_errors(clean)
    if not errors and not extract_functions(code):
        errors.append((1, "no function definitions were found (expected something like "
                          "`int foo(int x) { ... }`)"))
    return errors


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def _package(code: str, raw_errors, checker: str) -> dict:
    src_lines = code.replace("\r\n", "\n").split("\n")
    seen, errors = set(), []
    for line, msg in sorted(raw_errors, key=lambda e: e[0]):
        if (line, msg) in seen:
            continue
        seen.add((line, msg))
        snippet = src_lines[line - 1].rstrip() if 1 <= line <= len(src_lines) else ""
        errors.append({"line": line, "message": msg, "snippet": snippet})
    return {"ok": not errors, "checker": checker, "errors": errors[:MAX_ERRORS]}


def builtin_check(code: str) -> dict:
    """The built-in checker only (never calls a compiler)."""
    return _package(code, _builtin_errors(code), "built-in checker")


def check_syntax(code: str) -> dict:
    """Compiler if available, otherwise the built-in checker."""
    compiler_errors = _compiler_check(code)
    if compiler_errors is not None:
        result = _package(code, compiler_errors, "gcc/clang")
        if result["ok"] and not extract_functions(code):
            return _package(code, [(1, "no function definitions were found")], "gcc/clang")
        return result
    return builtin_check(code)


def format_errors(check: dict) -> str:
    """Terminal-style text for a failed check."""
    n = len(check["errors"])
    lines = [f"Compilation failed: {n} error{'s' if n != 1 else ''} found "
             f"(checked with {check['checker']}).",
             "No analysis or optimization was performed.", ""]
    for e in check["errors"]:
        lines.append(f"  line {e['line']}: error: {e['message']}")
        if e["snippet"].strip():
            lines.append(f"      {e['snippet'].strip()}")
    return "\n".join(lines)