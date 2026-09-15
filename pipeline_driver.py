"""
pipeline_driver.py

PURPOSE
-------
This file defines the STAGE INTERFACES (the data contracts every module must produce/consume)
and wires the stages into one runnable, end-to-end pipeline.
"""

import re
import os
from dataclasses import dataclass, field
from typing import Dict, List, Set

import networkx as nx
import matplotlib.pyplot as plt

# Import our advanced real-world optimization engine
from ipo_engine import (
    dead_procedure_elimination, 
    whole_program_inlining, 
    interprocedural_constant_propagation, 
    interprocedural_pointer_analysis
)


# ---------------------------------------------------------------------------
# STAGE INTERFACES -- the "contracts" between modules.
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
# ---------------------------------------------------------------------------

FUNC_DEF_RE = re.compile(r"^define\s+.*?@([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
CALL_RE = re.compile(r"call\s+[^@]*@([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def build_call_graph(program_ir: ProgramIR) -> CallGraph:
    functions = FUNC_DEF_RE.findall(program_ir.ir_text)
    graph = nx.DiGraph()
    graph.add_nodes_from(functions)

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
# STAGE 4 -- OPTIMIZATION + CODEGEN (Updated with Real-World DPE Pass)
# ---------------------------------------------------------------------------

def run_optimization(program_ir: ProgramIR, analysis: AnalysisResult) -> OptimizedIR:
    # 1. Dead Procedure Elimination
    dpe_result = dead_procedure_elimination(program_ir.ir_text, analysis.unreachable_functions)
    
    # 2. Whole-Program Inlining
    inlining_result = whole_program_inlining(dpe_result.ir_text, analysis.inlinable_call_sites)
    
    # 3. Interprocedural Constant Propagation
    icp_result = interprocedural_constant_propagation(inlining_result.ir_text)
    
    # 4. Interprocedural Pointer Analysis
    ptr_result = interprocedural_pointer_analysis(icp_result.ir_text)
    
    stats = {
        "functions_marked_inlinable": len(analysis.inlinable_call_sites),
        "functions_marked_dead": len(analysis.unreachable_functions),
        "dead_procedures_eliminated": dpe_result.stats["dead_procedures_eliminated"],
        "functions_inlined": inlining_result.stats["functions_inlined"],
        "constants_propagated": icp_result.stats["constants_propagated"],
        "pointers_tracked": ptr_result.stats["pointers_tracked"],
        "alias_relations_analyzed": ptr_result.stats["alias_relations_analyzed"]
    }
    
    return OptimizedIR(ir_text=ptr_result.ir_text, stats=stats)


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
# END-TO-END PIPELINE
# ---------------------------------------------------------------------------

def run_pipeline(source_path: str) -> OptimizedIR:
    print(f"[1/4] Frontend: parsing {source_path}")
    program_ir = run_frontend(source_path)

    print("[2/4] Building call graph")
    cg = build_call_graph(program_ir)
    print(f"        functions found: {list(cg.graph.nodes)}")
    print(f"        call edges:      {list(cg.graph.edges)}")

    print("[3/4] Running interprocedural analysis")
    analysis = run_interprocedural_analysis(cg, program_ir)
    print(f"        inlinable candidates:   {analysis.inlinable_call_sites}")
    print(f"        unreachable functions:  {analysis.unreachable_functions}")

    print("[4/4] Applying optimizations + generating output")
    result = run_optimization(program_ir, analysis)
    print(f"        stats: {result.stats}")

    img_path = visualize_call_graph(cg)
    print(f"Call graph diagram saved to: {img_path}")

    return result


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "sample.c"
    run_pipeline(src)