"""
pipeline_driver.py

PURPOSE
-------
This file defines
the STAGE INTERFACES (the data contracts every module must produce/consume)
and wires the stages into one runnable, end-to-end pipeline.

This is exactly what "Integration and Functional Prototype"and
the "Module integration, data exchange, end-to-end prototype execution"

Each teammate's job is to replace the body of their stage function with
their real logic WITHOUT changing its input/output types -- that is the
whole point of defining the interfaces up front.
"""

import re
import os
from dataclasses import dataclass, field
from typing import Dict, List, Set

import networkx as nx
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# STAGE INTERFACES -- the "contracts" between modules.
# Everyone codes against these shapes; this is what makes integration possible
# even when different members are at different stages of implementation.
# ---------------------------------------------------------------------------

@dataclass
class ProgramIR:
    """Output of Member 2's frontend/parser stage."""
    source_path: str
    ir_text: str  # raw LLVM IR (.ll) text


@dataclass
class CallGraph:
    """Output of the call-graph construction stage."""
    graph: nx.DiGraph
    entry_point: str = "main"


@dataclass
class AnalysisResult:
    """Output of Member 3's interprocedural analysis stage."""
    constant_args: Dict[str, Dict[str, str]] = field(default_factory=dict)
    inlinable_call_sites: List[str] = field(default_factory=list)
    unreachable_functions: Set[str] = field(default_factory=set)


@dataclass
class OptimizedIR:
    """Final output of the optimization + codegen stage."""
    ir_text: str
    stats: Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# STAGE 1 -- FRONTEND ADAPTER 
# ---------------------------------------------------------------------------

def run_frontend(source_path: str) -> ProgramIR:
    """
    Integration adapter around Member 2's frontend.
    Expects Clang to emit LLVM IR (.ll) for the given C/C++ source.
    Falls back to reading a pre-generated .ll file if Clang isn't installed
    in the current environment, so the pipeline still runs end-to-end
    during development and live demos.
    """
    ll_path = os.path.splitext(source_path)[0] + ".ll"

    if not os.path.exists(ll_path):
        exit_code = os.system(f"clang -S -emit-llvm {source_path} -o {ll_path} 2>/dev/null")
        if exit_code != 0 or not os.path.exists(ll_path):
            raise RuntimeError(
                f"Could not produce IR for {source_path}. "
                f"Member 2: confirm the frontend/Clang step is working, "
                f"or provide a pre-generated {ll_path}."
            )

    with open(ll_path, "r") as f:
        ir_text = f.read()

    return ProgramIR(source_path=source_path, ir_text=ir_text)


# ---------------------------------------------------------------------------
# STAGE 2 -- CALL GRAPH CONSTRUCTION
# Reference implementation so the pipeline is demoable NOW.
# Member 3 should replace this with the team's real call-graph algorithm,
# keeping the same input (ProgramIR) -> output (CallGraph) contract.
# ---------------------------------------------------------------------------

FUNC_DEF_RE = re.compile(r"^define\s+.*?@([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
CALL_RE = re.compile(r"call\s+[^@]*@([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def build_call_graph(program_ir: ProgramIR) -> CallGraph:
    functions = FUNC_DEF_RE.findall(program_ir.ir_text)
    graph = nx.DiGraph()
    graph.add_nodes_from(functions)

    # split IR into per-function blocks so each call is attributed to its caller
    blocks = re.split(r"(?=^define\s)", program_ir.ir_text, flags=re.MULTILINE)
    for block in blocks:
        header = FUNC_DEF_RE.search(block)
        if not header:
            continue
        caller = header.group(1)
        for callee in CALL_RE.findall(block):
            if callee in functions:
                graph.add_edge(caller, callee)

    return CallGraph(graph=graph)


# ---------------------------------------------------------------------------
# STAGE 3 -- INTERPROCEDURAL ANALYSIS
# Placeholder for Member 3's constant-propagation / inlining-candidate logic.
# Replace the BODY only -- keep the (CallGraph, ProgramIR) -> AnalysisResult
# contract identical so the rest of the pipeline keeps working unmodified.
# ---------------------------------------------------------------------------

def run_interprocedural_analysis(cg: CallGraph, program_ir: ProgramIR) -> AnalysisResult:
    reachable = nx.descendants(cg.graph, cg.entry_point) | {cg.entry_point} \
        if cg.entry_point in cg.graph else set(cg.graph.nodes)
    unreachable = set(cg.graph.nodes) - reachable

    single_caller_fns = [
        n for n in cg.graph.nodes
        if cg.graph.in_degree(n) == 1 and n != cg.entry_point
    ]

    return AnalysisResult(
        inlinable_call_sites=single_caller_fns,
        unreachable_functions=unreachable,
    )


# ---------------------------------------------------------------------------
# STAGE 4 -- OPTIMIZATION + CODEGEN
# Placeholder that reports what WOULD be optimized. Member 3/Member 2 plug
# the real IR-rewriting logic in here, keeping the same input/output types.
# ---------------------------------------------------------------------------

def run_optimization(program_ir: ProgramIR, analysis: AnalysisResult) -> OptimizedIR:
    stats = {
        "functions_marked_inlinable": len(analysis.inlinable_call_sites),
        "functions_marked_dead": len(analysis.unreachable_functions),
    }
    return OptimizedIR(ir_text=program_ir.ir_text, stats=stats)


# ---------------------------------------------------------------------------
# INTEGRATION DIAGRAM -- auto-generate the call-graph visualization.
# ---------------------------------------------------------------------------

def visualize_call_graph(cg: CallGraph, out_path: str = "call_graph.png") -> str:
    pos = nx.spring_layout(cg.graph, seed=42)
    plt.figure(figsize=(7, 5))
    nx.draw(
        cg.graph, pos, with_labels=True, node_color="#1F3864",
        font_color="white", node_size=1600, arrowsize=20, font_size=9,
    )
    plt.title("Call Graph — auto-generated by integration pipeline")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    return out_path


# ---------------------------------------------------------------------------
# END-TO-END PIPELINE -- this function IS the "functional prototype".
# ---------------------------------------------------------------------------

def run_pipeline(source_path: str) -> OptimizedIR:
    print(f"[1/4] Frontend: parsing {source_path}")
    program_ir = run_frontend(source_path)

    print("[2/4] Building call graph")
    cg = build_call_graph(program_ir)
    print(f"       functions found: {list(cg.graph.nodes)}")
    print(f"       call edges:      {list(cg.graph.edges)}")

    print("[3/4] Running interprocedural analysis")
    analysis = run_interprocedural_analysis(cg, program_ir)
    print(f"       inlinable candidates:   {analysis.inlinable_call_sites}")
    print(f"       unreachable functions:  {analysis.unreachable_functions}")

    print("[4/4] Applying optimizations + generating output")
    result = run_optimization(program_ir, analysis)
    print(f"       stats: {result.stats}")

    img_path = visualize_call_graph(cg)
    print(f"Call graph diagram saved to: {img_path}")

    return result


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "sample.c"
    run_pipeline(src)
