"""
extraction.py
-------------
Module 1 (Review 2, Section 5.2): function extraction from C source.

Implements, with the exact names used in the Review 2 report:
    remove_comments(code)
    normalize_type(t)
    parse_parameters(param_str)
    find_matching_brace(code, start_index)
    extract_functions(code) -> dict[str, Function]

This is a regex/brace-matching based prototype, not a full C parser
(documented limitation, Review 2 Section 5.7 / 6.6).
"""
import re
from .models import Function

# C keywords that can precede a function definition but are not types
_CONTROL_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof"}

_FUNC_SIG_RE = re.compile(
    r"""
    (?P<ret>[A-Za-z_][\w\s\*]*?)        # return type (greedy-ish, non-capturing of name)
    \s+
    (?P<name>[A-Za-z_]\w*)              # function name
    \s*\(\s*
    (?P<params>[^;{}()]*)               # parameter list (no nested parens handled for prototype)
    \)\s*
    \{                                  # opening brace of the body (definitions only, not prototypes)
    """,
    re.VERBOSE,
)


def remove_comments(code: str) -> str:
    """Strip // line comments and /* */ block comments without touching
    string/char literals' contents in the common case."""
    out = []
    i, n = 0, len(code)
    in_string = in_char = False
    while i < n:
        c = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if in_string:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(code[i + 1]); i += 2; continue
            elif c == '"':
                in_string = False
            i += 1
            continue
        if in_char:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(code[i + 1]); i += 2; continue
            elif c == "'":
                in_char = False
            i += 1
            continue
        if c == '"':
            in_string = True; out.append(c); i += 1; continue
        if c == "'":
            in_char = True; out.append(c); i += 1; continue
        if c == "/" and nxt == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if c == "/" and nxt == "*":
            i += 2
            while i < n - 1 and not (code[i] == "*" and code[i + 1] == "/"):
                if code[i] == "\n":
                    out.append("\n")  # preserve line numbers
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def normalize_type(t: str) -> str:
    """Collapse internal whitespace in a type string, e.g. 'int   *' -> 'int *'."""
    t = t.strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*\*\s*", " *", t)
    return t.strip()


def parse_parameters(param_str: str):
    """Parse a C parameter list string into [(type, name), ...].

    Handles simple scalar/pointer parameters (int x, char *s, float a[]).
    'void' or an empty list yields [].
    """
    param_str = param_str.strip()
    if param_str == "" or param_str == "void":
        return []

    params = []
    for raw in param_str.split(","):
        raw = raw.strip()
        if not raw:
            continue
        raw = raw.replace("[]", " *")  # treat array params like pointers
        # function-pointer parameter: int (*cb)(int)
        fp_match = re.match(r"^(?P<ret>[\w\s]+?)\(\s*\*\s*(?P<pname>\w+)\s*\)\s*\((?P<params>[^)]*)\)$", raw)
        if fp_match:
            params.append((f"{normalize_type(fp_match.group('ret'))} (*)({fp_match.group('params').strip()})",
                            fp_match.group("pname")))
            continue
        tokens = raw.split()
        if len(tokens) == 1:
            # type only (prototype-style) or a bare name — treat whole as type, name unknown
            params.append((normalize_type(tokens[0]), f"_arg{len(params)}"))
            continue
        name = tokens[-1].lstrip("*")
        star_count = tokens[-1].count("*") + sum(t.count("*") for t in tokens[:-1])
        base_type = " ".join(tokens[:-1])
        type_str = base_type + (" " + "*" * star_count if star_count else "")
        params.append((normalize_type(type_str), name))
    return params


def find_matching_brace(code: str, start_index: int) -> int:
    """Given the index of an opening '{', return the index of its matching '}'.
    Returns -1 if unmatched (handled gracefully per Review 2 T10)."""
    if start_index >= len(code) or code[start_index] != "{":
        return -1
    depth = 0
    i = start_index
    in_string = in_char = False
    n = len(code)
    while i < n:
        c = code[i]
        if in_string:
            if c == "\\":
                i += 2; continue
            if c == '"':
                in_string = False
            i += 1; continue
        if in_char:
            if c == "\\":
                i += 2; continue
            if c == "'":
                in_char = False
            i += 1; continue
        if c == '"':
            in_string = True; i += 1; continue
        if c == "'":
            in_char = True; i += 1; continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1  # unmatched braces -> caller handles the failure safely


def extract_functions(code: str) -> dict:
    """Extract all function definitions from C source code.

    Returns a dict: function_name -> Function
    """
    clean = remove_comments(code)
    functions = {}

    for m in _FUNC_SIG_RE.finditer(clean):
        ret_type = normalize_type(m.group("ret"))
        name = m.group("name")
        params_raw = m.group("params")
        brace_start = m.end() - 1  # points at the '{'

        if name in _CONTROL_KEYWORDS:
            continue
        if ret_type.split()[-1] in _CONTROL_KEYWORDS if ret_type else False:
            continue

        brace_end = find_matching_brace(clean, brace_start)
        if brace_end == -1:
            # Unmatched braces: skip this (malformed) function safely (Review 2, T10)
            continue

        body = clean[brace_start:brace_end + 1]
        start_line = clean.count("\n", 0, m.start()) + 1
        params = parse_parameters(params_raw)

        functions[name] = Function(
            name=name,
            return_type=ret_type,
            parameters=params,
            body=body,
            start_line=start_line,
        )

    return functions
