"""
api.py
------
Thin REST wrapper around analyzer.analyze_program(), so a frontend
(React, plain JS, whatever your teammate is building) can call this
backend over HTTP instead of importing Python directly.

Run:
    uvicorn api:app --reload --port 8000

Then:
    POST http://localhost:8000/analyze   { "source_code": "...", "entry": "main" }
    GET  http://localhost:8000/sample    -> the demo C program + its analysis
    GET  http://localhost:8000/health

CORS is wide open (allow_origins=["*"]) so your frontend teammate can hit
this from any dev server (localhost:3000, 5173, etc.) with zero extra
config. Tighten this before any real deployment.
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from analyzer import analyze_program
from analyzer_demo import source_code as DEMO_SOURCE
from analyzer.syntax_check import format_errors
from runner import compare_checked, execute_checked, run_checked

app = FastAPI(
    title="Hybrid Interprocedural Call Graph Analyzer API",
    description="BCSE307 Compiler Design Project (A16) -- backend for the "
                 "call-graph / optimization-analysis frontend.",
    version="1.0.0",
)

# The server can now RUN code, so only pages served from this machine may call it.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    source_code: str
    entry: str = "main"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    if not req.source_code or not req.source_code.strip():
        raise HTTPException(status_code=400, detail="source_code must not be empty")
    try:
        return analyze_program(req.source_code, entry=req.entry)
    except Exception as exc:  # pragma: no cover - safety net for malformed input
        raise HTTPException(status_code=422, detail=f"Could not analyze program: {exc}")


@app.get("/sample")
def sample():
    """Returns the Review 2 demonstration program together with its full
    analysis -- handy for a frontend dev to build against before the real
    analyzer integration is wired up."""
    return {
        "source_code": DEMO_SOURCE,
        "analysis": analyze_program(DEMO_SOURCE, entry="main"),
    }


# ---------------------------------------------------------------------------
# Frontend support (added): one call returns everything the dashboard shows
# ---------------------------------------------------------------------------
FRONTEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "index.html")


@app.get("/")
def home():
    """Serves the dashboard, so http://localhost:8000 is all you need to open."""
    return FileResponse(FRONTEND)


@app.post("/run")
def run(req: AnalyzeRequest):
    """Compile-check, then test results ("N passed") + terminal report + optimized code.
    Code with errors returns {"ok": false, "errors": [...]} and nothing else.
    Everything is also printed in the terminal that is running uvicorn."""
    if not req.source_code or not req.source_code.strip():
        raise HTTPException(status_code=400, detail="source_code must not be empty")
    try:
        out = run_checked(req.source_code, req.entry)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=422, detail=f"Could not analyze program: {exc}")

    print("\n" + "=" * 70)
    if not out["ok"]:
        print(format_errors(out))
        return out
    tests = out["tests"]
    print(f"tests: {tests['summary']}")
    for t in tests["results"]:
        print(f"  {t['status'].upper():6s} {t['name']}")
    print(out["report"])
    return out


def _print_run(title: str, run: dict) -> None:
    print(f"--- {title} (via {run['runner']}) ---")
    print(run["stdout"], end="" if run["stdout"].endswith("\n") else "\n")
    print(f"[exit code: {run['exit_code']}]" + (f"  {run['error']}" if run["error"] else ""))


@app.post("/execute")
def execute(req: AnalyzeRequest):
    """Run the user's program and return what it prints."""
    if not req.source_code or not req.source_code.strip():
        raise HTTPException(status_code=400, detail="source_code must not be empty")
    out = execute_checked(req.source_code)
    print("\n" + "=" * 70)
    if not out["ok"]:
        print(format_errors(out))
    else:
        _print_run("program output", out["run"])
    return out


@app.post("/compare")
def compare(req: AnalyzeRequest):
    """Run original and optimized code; report whether the behaviour is identical."""
    if not req.source_code or not req.source_code.strip():
        raise HTTPException(status_code=400, detail="source_code must not be empty")
    out = compare_checked(req.source_code, req.entry)
    print("\n" + "=" * 70)
    if not out["ok"]:
        print(format_errors(out))
        return out
    _print_run("original output", out["original"])
    _print_run("optimized output", out["optimized"])
    print(out["verdict"])
    return out