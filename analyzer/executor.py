"""
executor.py
-----------
Run a C program and capture its output.

    run_c(code)               -> run one program
    compare_runs(a, b)        -> did two runs behave identically?

Uses gcc/clang when installed (full C); otherwise the built-in interpreter
(analyzer/interpreter.py), so it works on any machine.
"""
import os
import shutil
import subprocess
import tempfile

from .interpreter import run_program
from .syntax_check import is_cpp

MAX_OUTPUT = 100_000


def _find_compiler(cpp: bool = False):
    if cpp:
        return shutil.which("g++") or shutil.which("clang++") or shutil.which("gcc") or shutil.which("clang")
    return shutil.which("gcc") or shutil.which("clang")


def _clip(text: str) -> str:
    text = text.replace("\r\n", "\n")
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + "\n...[output truncated]"


def _run_with_compiler(code: str, exe: str, timeout: float, cpp: bool = False) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        ext = ".cpp" if cpp else ".c"
        lang = "c++" if cpp else "c"
        src = os.path.join(tmp, "prog" + ext)
        binary = os.path.join(tmp, "prog.exe" if os.name == "nt" else "prog")
        with open(src, "w", encoding="utf-8") as f:
            f.write(code)
        cmd = [exe, "-O0", "-w", "-x", lang, src, "-o", binary]
        if not cpp:
            cmd.append("-lm")
        build = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if build.returncode != 0:
            # If C compilation failed, try with g++ if available
            if not cpp:
                cpp_exe = _find_compiler(cpp=True)
                if cpp_exe and cpp_exe != exe:
                    return _run_with_compiler(code, cpp_exe, timeout, cpp=True)
            msg = build.stderr.strip() or "build failed"
            if "main" in msg and "undefined" in msg:
                msg = "The program has no main() function, so it cannot be run."
            return {"status": "build_error", "stdout": "", "exit_code": None, "error": msg[:600]}
        try:
            proc = subprocess.run([binary], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as e:
            partial = (e.stdout or b"").decode("utf-8", errors="replace")
            return {"status": "timeout", "stdout": partial, "exit_code": None,
                    "error": f"The program ran longer than {timeout:.0f} seconds and was stopped (possible infinite loop)."}
        out = proc.stdout.decode("utf-8", errors="replace")
        status, err = "ok", None
        if proc.returncode < 0 or proc.returncode > 255:
            status, err = "runtime_error", f"The program crashed (exit code {proc.returncode})."
        return {"status": status, "stdout": out, "exit_code": proc.returncode, "error": err}


def run_c(code: str, timeout: float = 5.0) -> dict:
    """Run a C or C++ program. Result keys: status, stdout, exit_code, error, runner."""
    cpp = is_cpp(code)
    exe = _find_compiler(cpp)
    if exe:
        try:
            result = _run_with_compiler(code, exe, timeout, cpp)
            result["runner"] = "g++/clang++" if cpp else "gcc/clang"
            result["stdout"] = _clip(result["stdout"])
            return result
        except Exception:
            pass                                   # fall back to the interpreter
    result = run_program(code, timeout)
    result["runner"] = "built-in interpreter"
    result["stdout"] = _clip(result.get("stdout", ""))
    return result


def compare_runs(a: dict, b: dict) -> dict:
    """match: True / False, or None when a run could not complete."""
    if a["status"] != "ok" or b["status"] != "ok":
        return {"match": None, "verdict": "Could not compare: at least one program did not run to completion."}
    same_out = a["stdout"] == b["stdout"]
    same_code = a["exit_code"] == b["exit_code"]
    if same_out and same_code:
        return {"match": True, "verdict": "Outputs match: the optimized code behaves exactly like the original."}
    parts = []
    if not same_out:
        parts.append("the printed output differs")
    if not same_code:
        parts.append(f"the exit code differs ({a['exit_code']} vs {b['exit_code']})")
    return {"match": False, "verdict": "Outputs differ: " + " and ".join(parts) + "."}