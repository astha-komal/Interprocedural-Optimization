"""
runner.py
---------
Glue used by api.py (no web framework needed, so it can also be tested alone):

    run_tests()                 -> runs tests/test_analyzer.py, returns counts
    run_report(code, entry)     -> the exact text analyze_file.py prints in the
                                   terminal, plus the structured results
"""
import contextlib
import importlib.util
import io
import os
import threading
import time
import traceback

from analyze_file import human_readable_report
from analyzer import analyze_program
from analyzer.executor import compare_runs, run_c
from analyzer.syntax_check import check_syntax

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_FILE = os.path.join(BASE, "tests", "test_analyzer.py")
_stdout_lock = threading.Lock()   # redirect_stdout is process-wide
_run_lock = threading.Lock()      # one program execution at a time


def run_tests() -> dict:
    """Run every test_* function in tests/test_analyzer.py (no pytest needed)."""
    start = time.time()
    results = []
    try:
        spec = importlib.util.spec_from_file_location("test_analyzer_dyn", TEST_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return {"passed": 0, "failed": 1, "total": 1, "summary": "could not load tests",
                "results": [{"name": "load tests/test_analyzer.py", "status": "failed",
                             "message": traceback.format_exc()}]}

    for name in sorted(n for n in dir(module) if n.startswith("test_")):
        try:
            getattr(module, name)()
            results.append({"name": name, "status": "passed", "message": ""})
        except Exception:
            results.append({"name": name, "status": "failed", "message": traceback.format_exc()})

    passed = sum(r["status"] == "passed" for r in results)
    failed = len(results) - passed
    summary = f"{passed} passed" + (f", {failed} failed" if failed else "") + f" in {time.time() - start:.2f}s"
    return {"passed": passed, "failed": failed, "total": len(results),
            "summary": summary, "results": results}


def run_report(code: str, entry: str = "main") -> dict:
    """Capture the same text analyze_file.py prints, and return it with the data."""
    buf = io.StringIO()
    with _stdout_lock:
        with contextlib.redirect_stdout(buf):
            try:
                human_readable_report(code, entry)
            except SystemExit:      # "no functions could be extracted"
                pass
    results = analyze_program(code, entry=entry)
    return {"report": buf.getvalue(), "analysis": results}


def run_checked(code: str, entry: str = "main") -> dict:
    """Compile-check first. Only error-free code is tested, analyzed and optimized."""
    check = check_syntax(code)
    if not check["ok"]:
        return {"ok": False, "checker": check["checker"], "errors": check["errors"]}
    out = run_report(code, entry)
    return {
        "ok": True,
        "checker": check["checker"],
        "tests": run_tests(),
        "report": out["report"],
        "optimized_code": out["analysis"]["optimized_program"]["code"],
        "analysis": out["analysis"],
    }


def _compile_failed(check: dict) -> dict:
    return {"ok": False, "checker": check["checker"], "errors": check["errors"]}


def execute_checked(code: str) -> dict:
    """Run the user's program and return its output (compile-checked first)."""
    check = check_syntax(code)
    if not check["ok"]:
        return _compile_failed(check)
    with _run_lock:
        return {"ok": True, "run": run_c(code)}


def compare_checked(code: str, entry: str = "main") -> dict:
    """Run the original AND the optimized program and compare their behaviour."""
    check = check_syntax(code)
    if not check["ok"]:
        return _compile_failed(check)
    optimized = analyze_program(code, entry=entry)["optimized_program"]
    with _run_lock:
        original_run = run_c(code)
        optimized_run = run_c(optimized["code"])
    verdict = compare_runs(original_run, optimized_run)
    return {
        "ok": True,
        "original": original_run,
        "optimized": optimized_run,
        "optimized_code": optimized["code"],
        "changed": optimized["changed"],
        **verdict,
    }