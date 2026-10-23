"""
test_analyzer.py
-----------------
Automated regression suite implementing the Review 2 Section 8.1 test
table (T01-T12) with real, verified results -- replacing the "To verify"
placeholders in the report with actual pass/fail evidence.

Run:
    pytest tests/ -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer import analyze_program
from analyzer.extraction import extract_functions, find_matching_brace

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(fname):
    with open(os.path.join(HERE, fname), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# T01 / T04 / T06 -- direct-call and direct-recursion edge detection
# ---------------------------------------------------------------------------

def test_T01_direct_call_to_recursive_detected():
    """T01: Direct call to recursive() -> Direct edge detected."""
    result = analyze_program(_read("recursion.c"), entry="main")
    edges = {(e["from"], e["to"], e["type"]) for e in result["call_graph"]["edges"]}
    assert ("main", "recursive", "DIRECT") in edges


def test_T04_even_calls_odd_direct_edge():
    """T04: even() calls odd() -> Direct edge detected."""
    result = analyze_program(_read("recursion.c"), entry="main")
    edges = {(e["from"], e["to"], e["type"]) for e in result["call_graph"]["edges"]}
    assert ("even", "odd", "DIRECT") in edges


def test_T06_recursive_calls_itself_direct_recursion_detected():
    """T06: recursive() calls itself -> Direct recursion detected."""
    result = analyze_program(_read("recursion.c"), entry="main")
    edges = {(e["from"], e["to"], e["type"]) for e in result["call_graph"]["edges"]}
    assert ("recursive", "recursive", "DIRECT") in edges
    assert "recursive" in result["recursive_functions"]


# ---------------------------------------------------------------------------
# T02 / T03 -- function-pointer target detection
# ---------------------------------------------------------------------------

def test_T02_fp_equals_square_pointer_target_detected():
    """T02: fp = square -> function pointer target detected."""
    result = analyze_program(_read("function_pointers.c"), entry="main")
    main_fn = result["functions"]["main"]
    assert "square" in main_fn["pointer_assignments"].get("fp", [])
    edges = {(e["from"], e["to"]) for e in result["call_graph"]["edges"]}
    assert ("main", "square") in edges  # resolved via POINTER-REFINED or POINTER


def test_T03_gp_equals_increment_pointer_target_detected():
    """T03: gp = increment -> function pointer target detected."""
    result = analyze_program(_read("function_pointers.c"), entry="main")
    main_fn = result["functions"]["main"]
    assert "increment" in main_fn["pointer_assignments"].get("gp", [])
    edges = {(e["from"], e["to"]) for e in result["call_graph"]["edges"]}
    assert ("main", "increment") in edges


# ---------------------------------------------------------------------------
# T05 -- mutual recursion
# ---------------------------------------------------------------------------

def test_T05_mutual_recursion_detected():
    """T05: odd() calls even() -> Mutual recursion detected (SCC size > 1)."""
    result = analyze_program(_read("recursion.c"), entry="main")
    sccs = [set(s) for s in result["sccs"]]
    assert {"even", "odd"} in sccs
    assert "even" in result["recursive_functions"]
    assert "odd" in result["recursive_functions"]


# ---------------------------------------------------------------------------
# T07 / T08 -- boundary cases
# ---------------------------------------------------------------------------

def test_T07_function_with_no_parameters_handled_correctly():
    """T07: Function with no parameters -> Parameters handled correctly."""
    functions = extract_functions(_read("boundary_cases.c"))
    assert functions["get_zero"].parameters == []
    assert functions["get_zero"].param_count == 0


def test_T08_singleton_recursive_scc_identified():
    """T08: Singleton recursive SCC (SCC of size 1 with a self-loop)
    -> Recursive function identified."""
    result = analyze_program(_read("recursion.c"), entry="main")
    sccs = [set(s) for s in result["sccs"]]
    assert {"recursive"} in sccs            # SCC size == 1 ...
    assert "recursive" in result["recursive_functions"]  # ... but still recursive


# ---------------------------------------------------------------------------
# T09 / T10 -- invalid-input handling
# ---------------------------------------------------------------------------

def test_T09_no_main_function_error_message_displayed():
    """T09: No main() function -> Error message displayed."""
    result = analyze_program(_read("boundary_cases.c"), entry="main")
    assert "main" not in result["functions"]
    assert len(result["errors"]) == 1
    assert "entry point 'main'" in result["errors"][0]
    assert result["reachable_functions"] == []


def test_T10_unmatched_braces_handled_safely():
    """T10: Unmatched braces -> Function extraction safely handles failure
    (the malformed function is skipped; well-formed functions around it
    still extract correctly, no exception is raised)."""
    broken_code = """
    int broken(int x) {
        return x + 1;
    /* missing closing brace */

    int ok(int y) {
        return y * 2;
    }
    """
    assert find_matching_brace("{ int x; ", 0) == -1  # direct unit check

    functions = extract_functions(broken_code)  # must not raise
    assert "ok" in functions
    assert "broken" not in functions  # safely skipped, not partially parsed


# ---------------------------------------------------------------------------
# T11 / T12 -- optimization analysis
# ---------------------------------------------------------------------------

def test_T11_square_5_constant_result_25():
    """T11: square(5) -> Constant result = 25."""
    result = analyze_program(_read("direct_calls.c"), entry="main")
    cp = result["constant_propagation"]
    matches = [r for r in cp if r["callee"] == "square" and r["args"] == ["5"]]
    assert len(matches) == 1
    assert matches[0]["result"] == 25


def test_T12_recursive_function_inlining_skipped():
    """T12: Recursive function for inlining -> Inlining skipped."""
    result = analyze_program(_read("recursion.c"), entry="main")
    rec = result["optimization_analysis"]["recursive"]
    assert rec["decision"] == "DO NOT INLINE"
    assert rec["skipped_recursive"] is True


# ---------------------------------------------------------------------------
# T13+ -- optimized-code generation (Module 3)
# ---------------------------------------------------------------------------

def test_T13_constant_call_replaced_by_value_and_function_removed():
    """T13: square(5) is replaced by 25 in the generated code, and square()
    (no longer referenced) is removed."""
    opt = analyze_program(_read("direct_calls.c"), entry="main")["optimized_program"]
    assert "int s = 25;" in opt["code"]
    assert "square(5)" not in opt["code"].replace("/* [optimized away]", "")
    assert [r["name"] for r in opt["removed_functions"]] == ["square"]
    assert "int add(int a, int b)" in opt["code"]          # untouched


def test_T14_recursive_and_pointer_programs_left_unchanged():
    """T14: recursion.c / function_pointers.c have nothing safe to optimize."""
    for fname in ("recursion.c", "function_pointers.c"):
        src = _read(fname)
        opt = analyze_program(src, entry="main")["optimized_program"]
        assert opt["transformations"] == []
        assert opt["code"].strip() == src.strip()


def test_T15_no_main_nothing_removed():
    """T15: without an entry point no function is deleted (library-style file)."""
    opt = analyze_program(_read("boundary_cases.c"), entry="main")["optimized_program"]
    assert opt["removed_functions"] == []
    assert "int get_zero()" in opt["code"]


def test_T16_inline_with_runtime_argument_and_comments_preserved():
    """T16: INLINE-decision callee is inlined at runtime-argument call sites;
    comments and string literals are never touched."""
    src = (
        "/* square(9) stays */\n"
        "int square(int x) { return x * x; }\n"
        "int main() {\n"
        "    int n = 3;\n"
        "    int a = square(5);\n"
        "    int b = square(n + 1);\n"
        "    printf(\"square(5)\");\n"
        "    return a + b;\n"
        "}\n"
    )
    opt = analyze_program(src, entry="main")["optimized_program"]
    assert "int a = 25;" in opt["code"]
    assert "int b = ((n + 1) * (n + 1));" in opt["code"]
    assert "/* square(9) stays */" in opt["code"]
    assert 'printf("square(5)");' in opt["code"]


def test_T17_side_effect_argument_not_duplicated():
    """T17: twice(i++) must not become (i++ + i++)."""
    src = (
        "int twice(int x) { return x + x; }\n"
        "int main() { int i = 0; int a = twice(2); int b = twice(i++); return a + b; }\n"
    )
    opt = analyze_program(src, entry="main")["optimized_program"]
    assert "twice(i++)" in opt["code"]
    assert "i++ + i++" not in opt["code"]


def test_T18_swapped_arguments_substituted_simultaneously():
    """T18: sub(b, a) must give (b - a), not a chained re-substitution."""
    src = (
        "int sub(int a, int b) { return a - b; }\n"
        "int main() { int a = sub(1, 2); int a2 = 5; int b = 7; int c = sub(b, a2); return a + c; }\n"
    )
    result = analyze_program(src, entry="main")
    opt = result["optimized_program"]
    # whatever the inline decision was, the result must be semantically right
    assert "sub(b, a2)" in opt["code"] or "(b - a2)" in opt["code"]


def test_T19_existing_analysis_output_unchanged_keys_present():
    """T19: all original result keys are still present (output is additive)."""
    result = analyze_program(_read("recursion.c"), entry="main")
    for key in ("entry_point", "errors", "functions", "call_graph",
                "reachable_functions", "unreachable_functions", "sccs",
                "recursive_functions", "constant_propagation",
                "optimization_analysis", "summary"):
        assert key in result
    assert "optimized_program" in result


# ---------------------------------------------------------------------------
# T20+ -- compile-error detection (built-in checker; independent of gcc)
# ---------------------------------------------------------------------------
from analyzer.syntax_check import builtin_check


def test_T20_valid_programs_have_no_compile_errors():
    """T20: every sample program is accepted (no false positives)."""
    for fname in ("recursion.c", "function_pointers.c", "direct_calls.c",
                  "demo_for_maam.c", "boundary_cases.c"):
        assert builtin_check(_read(fname))["ok"], fname


def test_T21_missing_semicolon_detected():
    """T21: a missing ';' is reported on the right line."""
    r = builtin_check("int main() {\n    int a = 5\n    return a;\n}")
    assert not r["ok"] and r["errors"][0]["line"] == 2
    assert "';'" in r["errors"][0]["message"]


def test_T22_unbalanced_brackets_detected():
    """T22: missing '}' and extra '}' and missing ')' are all reported."""
    assert not builtin_check("int main() {\n    return 0;\n")["ok"]
    assert not builtin_check("int main() {\n    return 0;\n}\n}")["ok"]
    assert not builtin_check("int main() {\n    int a = (1 + 2;\n    return a;\n}")["ok"]


def test_T23_unterminated_string_and_comment_detected():
    """T23: unterminated string literal and /* comment are reported."""
    assert not builtin_check('int main() {\n    char *s = "abc;\n    return 0;\n}')["ok"]
    assert not builtin_check("int main() {\n    /* oops\n    return 0;\n}")["ok"]


def test_T24_no_functions_is_an_error():
    """T24: text with no function definitions is rejected."""
    assert not builtin_check("this is not C code")["ok"]


# ---------------------------------------------------------------------------
# T25+ -- running programs and comparing original vs optimized output
# (uses the built-in interpreter, so no C compiler is needed)
# ---------------------------------------------------------------------------
from analyzer.interpreter import run_program


def test_T25_program_output_captured():
    """T25: printf output and the exit code of main() are captured."""
    r = run_program('#include <stdio.h>\nint main() { printf("v=%d %.2f\\n", 6 * 7, 7 / 2.0); return 3; }')
    assert r["status"] == "ok" and r["stdout"] == "v=42 3.50\n" and r["exit_code"] == 3


def test_T26_c_semantics_division_and_wraparound():
    """T26: C integer division truncates toward zero; int overflow wraps."""
    r = run_program('#include <stdio.h>\nint main() { int b = 2147483647; b = b + 1;'
                    ' printf("%d %d %d\\n", -7 / 2, -7 % 3, b); return 0; }')
    assert r["stdout"] == "-3 -1 -2147483648\n"


def test_T27_runtime_errors_and_unsupported_reported():
    """T27: division by zero, infinite loops and unsupported features are
    reported as errors instead of crashing the tool."""
    assert run_program("int main() { int z = 0; return 5 / z; }")["status"] == "runtime_error"
    assert run_program("int main() { while (1) { } return 0; }", time_limit=1)["status"] == "timeout"
    assert run_program("struct s { int a; }; int main() { return 0; }")["status"] == "unsupported"


def test_T28_optimized_output_equals_original_for_all_samples():
    """T28: for every sample program, the optimized code prints exactly the
    same output and returns the same exit code as the original."""
    for fname in ("recursion.c", "function_pointers.c", "direct_calls.c", "demo_for_maam.c"):
        src = _read(fname)
        optimized = analyze_program(src, entry="main")["optimized_program"]["code"]
        a, b = run_program(src), run_program(optimized)
        assert a["status"] == b["status"] == "ok", fname
        assert (a["stdout"], a["exit_code"]) == (b["stdout"], b["exit_code"]), fname


def test_T29_float_parameter_inlining_keeps_real_division():
    """T29: half(5) with a float parameter must still give 2.5 after inlining."""
    src = ('#include <stdio.h>\nfloat half(float x) { return x / 2; }\n'
           'int main() { printf("%.1f %.1f\\n", half(5), half(9)); half(1); return 0; }')
    optimized = analyze_program(src, entry="main")["optimized_program"]["code"]
    assert run_program(src)["stdout"] == run_program(optimized)["stdout"] == "2.5 4.5\n"