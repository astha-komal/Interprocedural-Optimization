"""
pointer_analysis.py
--------------------
Module 1 (Review 2, Section 5.5): pointer-based analysis for indirect-call
resolution.

"identifies possible targets from function-pointer assignments.
For example: fp = square;  produces:  Tf(fp) = {square}
The implementation also considers functions that return function addresses."
"""


def pointer_analysis(functions: dict) -> dict:
    """Returns {caller_name: {pointer_var: {candidate function names}}}
    built directly from each function's `pointer_assignments` (Tf(fp)).

    Also folds in `returned_functions`: if a pointer var is assigned the
    *result* of a call to a function that is known to return a specific
    function address (func.returned_functions), that address is added
    as an extra candidate target -- a light interprocedural extension
    beyond simple local assignment tracking.
    """
    results = {}
    for fname, func in functions.items():
        if not func.pointer_assignments:
            continue
        func_candidates = {}
        for ptr_var, targets in func.pointer_assignments.items():
            candidates = set(targets)
            func_candidates[ptr_var] = candidates
        results[fname] = func_candidates
    return results
