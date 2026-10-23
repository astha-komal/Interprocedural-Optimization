"""
call_discovery.py
------------------
Module 1 (Review 2, Section 5.3): direct-call and function-pointer discovery.

discover_calls(func, known_names) populates, on the given Function object:
    func.direct_calls        -- names of functions called directly: foo(...)
    func.indirect_calls      -- names of local pointer variables called: fp(...)
    func.pointer_assignments -- {pointer_var: {candidate target function names}}
    func.returned_functions  -- function names returned as values: return foo;

`known_names` is the set of all function names extracted from the program,
used to decide whether an identifier is a real function or just a local
variable / parameter.
"""
import re

_CONTROL_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof"}

# int (*fp)(int) = square;
_PTR_DECL_ASSIGN_RE = re.compile(
    r"\b[\w\s]+?\(\s*\*\s*(?P<var>\w+)\s*\)\s*\(\s*[^)]*\s*\)\s*=\s*(?P<target>\w+)\s*;"
)
# int (*fp)(int);
_PTR_DECL_ONLY_RE = re.compile(
    r"\b[\w\s]+?\(\s*\*\s*(?P<var>\w+)\s*\)\s*\(\s*[^)]*\s*\)\s*;"
)
# fp = square;
_ASSIGN_RE = re.compile(r"\b(?P<var>\w+)\s*=\s*(?P<target>\w+)\s*;")
# some_name(
_CALL_RE = re.compile(r"\b(?P<name>\w+)\s*\(")
# return foo;
_RETURN_RE = re.compile(r"\breturn\s+(?P<name>\w+)\s*;")


def discover_calls(func, known_names: set) -> None:
    body = func.body
    ptr_vars = set()

    # 1. explicit pointer declaration + immediate assignment
    for m in _PTR_DECL_ASSIGN_RE.finditer(body):
        var, target = m.group("var"), m.group("target")
        ptr_vars.add(var)
        if target in known_names:
            func.pointer_assignments.setdefault(var, set()).add(target)

    # 2. pointer declaration without assignment (assigned later)
    for m in _PTR_DECL_ONLY_RE.finditer(body):
        ptr_vars.add(m.group("var"))

    # 3. later plain assignment of a known function to a declared pointer var
    for m in _ASSIGN_RE.finditer(body):
        var, target = m.group("var"), m.group("target")
        if var in ptr_vars and target in known_names:
            func.pointer_assignments.setdefault(var, set()).add(target)

    # 4. call sites: classify as direct / indirect
    for m in _CALL_RE.finditer(body):
        name = m.group("name")
        if name in _CONTROL_KEYWORDS:
            continue
        # a genuine self-call (direct recursion, e.g. recursive() calling
        # recursive()) must be kept; `body` never contains the function's
        # own signature line (it starts at the opening brace), so any
        # occurrence of func.name here is a real recursive call site.
        if name in ptr_vars:
            func.indirect_calls.add(name)
        elif name in known_names:
            func.direct_calls.add(name)
        # else: call to an unknown/external function (e.g. printf) -> ignored

    # 5. returned function addresses
    for m in _RETURN_RE.finditer(body):
        name = m.group("name")
        if name in known_names:
            func.returned_functions.add(name)

    # make sure every pointer variable is at least present in the dict,
    # even with an empty candidate set, so downstream analysis sees it
    for var in ptr_vars:
        func.pointer_assignments.setdefault(var, set())


def get_call_site_arg_counts(func, ptr_var: str):
    """Return the list of argument counts seen at each call site `ptr_var(...)`
    inside `func`. Used by type_based_analysis for its parameter-count
    approximation."""
    counts = []
    for m in re.finditer(rf"\b{re.escape(ptr_var)}\s*\(\s*([^)]*)\s*\)", func.body):
        args = m.group(1).strip()
        counts.append(0 if args == "" else len(args.split(",")))
    return counts
