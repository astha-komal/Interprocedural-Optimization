"""
type_analysis.py
-----------------
Module 1 (Review 2, Section 5.4): type-based analysis for indirect-call
resolution.

Per the Review 2 report: "If no direct assignment is available, the
current prototype uses the number of arguments as a simplified type
approximation. This is intentionally a prototype-level analysis and is
one of the areas planned for improvement" (documented limitation).
"""
from .call_discovery import get_call_site_arg_counts


def type_based_analysis(functions: dict) -> dict:
    """Returns {caller_name: {pointer_var: {candidate function names}}}

    For every indirect call site `ptr_var(...)` found in a function, the
    candidate set is every known function whose parameter count matches
    the number of arguments supplied at that call site.
    """
    results = {}
    for fname, func in functions.items():
        func_candidates = {}
        for ptr_var in func.indirect_calls:
            arg_counts = get_call_site_arg_counts(func, ptr_var)
            candidates = set()
            for n in arg_counts:
                candidates |= {
                    other.name for other in functions.values() if other.param_count == n
                }
            func_candidates[ptr_var] = candidates
        if func_candidates:
            results[fname] = func_candidates
    return results
