# Interprocedural Whole-Program Optimizer

BCSE307 — Compiler Design | Review 2

Builds a call graph for a program and applies interprocedural optimizations
(function inlining, constant propagation across calls) guided by a
cost-benefit heuristic.

## Project structure

```
.
├── pipeline_driver.py   # end-to-end pipeline + integration interfaces (Member 1)
├── sample.c             # example test program
├── sample.ll            # pre-generated LLVM IR for sample.c (fallback if Clang isn't installed)
└── call_graph.png       # auto-generated on run — visual call graph output
```

## Setup

Requires Python 3.8+.

```bash
python -m pip install networkx matplotlib
```

Clang is optional. If it's installed, the pipeline compiles `.c` files fresh.
If not, it automatically falls back to the matching pre-generated `.ll` file.

## Running the pipeline

```bash
python pipeline_driver.py sample.c
```

Expected output:

```
[1/4] Frontend: parsing sample.c
[2/4] Building call graph
       functions found: ['square', 'unused', 'calculate', 'main']
       call edges:      [('calculate', 'square'), ('main', 'calculate')]
[3/4] Running interprocedural analysis
       inlinable candidates:   ['square', 'calculate']
       unreachable functions:  {'unused'}
[4/4] Applying optimizations + generating output
       stats: {'functions_marked_inlinable': 2, 'functions_marked_dead': 1}
Call graph diagram saved to: call_graph.png
```

A `call_graph.png` image is generated showing the caller → callee graph.

## How the pipeline is organized

The pipeline has 4 stages, connected through fixed data interfaces
(`ProgramIR` → `CallGraph` → `AnalysisResult` → `OptimizedIR`, defined at the
top of `pipeline_driver.py`). Anyone can replace a stage's internal logic
without breaking the others, as long as the input/output shape stays the same.

| Stage | Function | Status | Owner |
|---|---|---|---|
| Frontend / parser | `run_frontend()` | Working (Clang + `.ll` fallback) | Member 2 |
| Call graph construction | `build_call_graph()` | Working reference implementation | Member 3 |
| Interprocedural analysis | `run_interprocedural_analysis()` | Partial — dead-function & single-caller detection done; constant-value propagation not yet implemented | Member 3 |
| Optimization + codegen | `run_optimization()` | Stub — reports what *would* be optimized, does not yet rewrite IR | Member 2 / Member 3 |
| Integration + visualization | `run_pipeline()`, `visualize_call_graph()` | Working | Member 1 |

## Current limitations (expected at this stage)

- Only direct function calls are handled (no function pointers / indirect calls)
- Constant propagation across calls is not yet implemented — the interface
  (`AnalysisResult.constant_args`) is reserved for it
- The optimization stage reports decisions but does not yet rewrite the IR

## For teammates extending a stage

Replace only the body of your stage's function — keep the same parameter
types and return type so the rest of the pipeline keeps working. If you need
a different data shape, update the relevant dataclass at the top of the file
and flag the change to the team, since other stages may depend on it.