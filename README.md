# Hybrid Interprocedural Call Graph Analyzer with Optimization Analysis

BCSE307 Compiler Design Project (A16)

Paste or load a C or C++ program (.c / .cpp) and the tool will:

1. **Check it for compile errors.** Code with errors is rejected and nothing else is shown.
2. **Build the call graph** (direct calls, function pointers, recursion and mutual recursion).
3. **Analyze it:** reachability from `main`, strongly connected components, constant propagation and inline recommendations.
4. **Generate optimized C code:** constant folding, inlining and dead-function removal.
5. **Run the original and the optimized program** and compare their output, to prove the optimization did not change the behaviour.

It works as a web dashboard, as a command-line tool and as a REST API.

---

## 1. Requirements

| What | Needed? | Notes |
|---|---|---|
| **Python 3.9 or newer** | Yes | Check with `python --version` |
| **fastapi**, **uvicorn** | Yes (dashboard / API) | Installed by `requirements.txt` |
| **pytest** | Only to run the tests with pytest | Installed by `requirements.txt` |
| **gcc / g++ or clang / clang++** | Optional | If installed, the tool uses it to check and run programs (full C/C++ support). If not, the built-in checker and interpreter are used automatically. |

The analyzer itself uses only the Python standard library.

---

## 2. Setup (do this once)

Open a terminal in the project folder (the one containing `api.py`).

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

(If `python` is not recognized, use `py` instead: `py -m venv .venv` and `py -m pip install -r requirements.txt`.
You can also install just the two needed packages directly: `python -m pip install fastapi uvicorn`
or `py -m pip install fastapi uvicorn`.)

If PowerShell blocks the activate script, run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and try again.

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

> Tip: always use `python -m pip ...` instead of plain `pip ...`. It avoids the
> "pip is not recognized" error on Windows.

---

## 3. Run the dashboard

```bash
python -m uvicorn api:app --reload --port 8000
```

(If `python` is not recognized, or you get an error with the command above, use the Windows launcher instead:
`py -m uvicorn api:app --reload --port 8000`)

Then open **http://localhost:8000** in your browser. Keep the terminal open while you use the page.

In the dashboard:

| Button | What it does |
|---|---|
| **Analyze and optimize** | Compile-checks the code, then shows the test results ("N passed"), the full analysis report and the optimized code |
| **Run code** | Runs your program and shows what it prints, plus its exit code |
| **Run optimized & compare outputs** | (after analyzing) Runs the original and the optimized code side by side and shows whether the outputs match |
| **Load sample** | Fills the box with a demo program |
| **Open .c file** | Loads a `.c` file from your computer into the box |
| **Entry function** | Where the analysis starts (default `main`) |

Everything shown on the page is also printed in the terminal where uvicorn is running.

The `404 /favicon.ico` line in the terminal is harmless: browsers ask for a tab icon and the server has none.

---

## 4. Run from the command line (no browser)

```bash
python analyzer_demo.py                          # built-in demo program
python analyze_file.py tests/direct_calls.c      # any C file
python analyze_file.py tests/recursion.c --entry main
python analyze_file.py tests/cpp_cases.cpp
python analyze_file.py tests/direct_calls.c -o optimized.c     # save the optimized code
python analyze_file.py tests/direct_calls.c --json out.json    # save the results as JSON
```

If the file has compile errors, the errors are printed and nothing else runs.

---

## 5. Run the tests

The regression suite is `tests/test_analyzer.py` (34 tests: call-graph detection, direct/mutual/indirect recursion cycles, dead cycle elimination, pointers,
constant propagation, inlining in and around cycles, compile-error detection, C++ syntax checking and optimization, running programs and output comparison).

```bash
python -m pytest tests -v
```

(or `py -m pytest tests -v` on Windows if `python` is not recognized)

Expected ending: `34 passed`.

No pytest? This runs the same tests without it:

```bash
python -c "from runner import run_tests; r = run_tests(); print(r['summary'])"
```

---

## 6. Project structure

```
.
├── api.py                 FastAPI server: dashboard + REST API
├── runner.py              Glue used by the API (tests, report, run, compare)
├── analyze_file.py        Command-line tool for any C file
├── analyzer_demo.py       Demo program (also used by "Load sample")
├── requirements.txt       Python packages
├── frontend/
│   └── index.html         The dashboard (plain HTML/CSS/JS, no build step)
├── analyzer/              The analyzer package
│   ├── pipeline.py        End-to-end driver: analyze_program()
│   ├── extraction.py      Function extraction from C source
│   ├── call_discovery.py  Direct calls and function-pointer discovery
│   ├── type_analysis.py   Type-based indirect-call resolution
│   ├── pointer_analysis.py Pointer-based indirect-call resolution
│   ├── call_graph.py      Hybrid call-graph construction
│   ├── reachability.py    Demand-driven reachability (worklist)
│   ├── scc.py             Tarjan SCC / recursion detection
│   ├── optimization.py    Constant propagation and inline heuristic
│   ├── codegen.py         Optimized-code generation
│   ├── syntax_check.py    Compile-error detection (gcc/clang or built-in)
│   ├── interpreter.py     Built-in C interpreter (used when no compiler)
│   ├── executor.py        Runs programs and compares two runs
│   └── models.py          Function data model
└── tests/
    ├── test_analyzer.py   Regression tests
    └── *.c                Sample C programs used by the tests
```

---

## 7. How it works

```
C source
  │
  ├─ syntax_check      compile errors?  → stop and show the errors
  │
  ├─ extract_functions → build_call_graph (DIRECT / POINTER-REFINED / POINTER / TYPE-FALLBACK edges)
  ├─ demand_driven_analysis (reachability)  → find_sccs & classify_cycles (direct/mutual/indirect cycles)
  ├─ constant_propagation → optimization_analysis (INLINE / DO NOT INLINE with cycle-breaking rule)
  └─ generate_optimized_code
        1. constant-fold calls with constant arguments      square(5)  →  25
        2. inline functions marked INLINE                   add(n, 2)  →  (n + 2)
        3. inline non-recursive helpers inside recursive functions
        4. remove unreachable functions (including dead recursive cycles)

Cycle Handling Policy:
- Cycle Detection: Tarjan's SCC classifies cycles into DIRECT (self-loop), MUTUAL (2-node), and INDIRECT (3+ node) recursion.
- Reachability Filter: Live cycles reachable from `main()` are preserved. Unreachable dead cycles are eliminated completely.
- Cycle-Breaking Inlining: Recursive calls are never inlined into themselves or their mutual recursion partners, preventing infinite compile-time expansion. Non-recursive helpers called inside recursive functions remain fully eligible for inlining.
- Safety: Comments, strings, and referenced function pointers are always preserved.

## 8. REST API

All endpoints take JSON `{"source_code": "...", "entry": "main"}` unless noted.

| Method and path | Purpose |
|---|---|
| `GET /` | The dashboard |
| `GET /health` | Health check |
| `GET /sample` | Demo program and its analysis |
| `POST /analyze` | Analysis result as JSON, including `optimized_program` |
| `POST /run` | Compile check, then test results, report and optimized code |
| `POST /execute` | Run the program and return its output |
| `POST /compare` | Run original and optimized code and compare them |

Interactive API docs are at **http://localhost:8000/docs** while the server is running.

---

## 9. Limitations

- Function extraction and analysis use regular expressions and brace matching, not a full C parser.
- Only functions with a single `return <expression>;` and `int`/`long`/`float`/`double` parameters are folded or inlined.
- The built-in compile checker catches syntax mistakes (missing `;`, unbalanced brackets, unterminated strings or comments). It cannot catch semantic errors such as undeclared variables. Install gcc to catch those too.
- The built-in interpreter does not support `struct`, `union`, `typedef`, `malloc`/`free`, `scanf`, file I/O, function-like macros or `goto`. It tells you when a program uses one. With gcc installed, such programs run normally.
- The server runs the programs you submit on your own computer. Use it locally, and do not expose it to the internet.

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| `pip is not recognized` | Use `python -m pip install ...` (or `py -m pip ...`) |
| `python is not recognized` | Try `py` instead of `python` (for example `py -m uvicorn api:app --reload --port 8000`). If that fails too, install Python from python.org and tick **Add python.exe to PATH**, then reopen the terminal |
| `uvicorn is not recognized` | Do not type `uvicorn` on its own. Use `python -m uvicorn api:app --reload --port 8000` (or `py -m uvicorn ...`) |
| `Could not import module "api"` | You are in the wrong folder. `cd` into the folder that contains `api.py` |
| `Address already in use` | Another server is using the port. Stop it, or run with `--port 8001` and open that port instead |
| Page says "Cannot reach the backend" | The uvicorn server is not running. Start it (section 3) |
| `ModuleNotFoundError: fastapi` | Activate the virtual environment and run `python -m pip install -r requirements.txt` |

## 11. Team workflow (Git)

```bash
git pull                      # get the latest changes before you start
# ... make your changes, run the tests ...
git add .
git commit -m "Describe what you changed"
git push
```

Run `python -m pytest tests -v` before every push.