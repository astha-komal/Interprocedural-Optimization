"""
pipeline.py
-----------
End-to-end driver (Review 2, Section 7.1):

    1. extract_functions()
    2. build_call_graph()
    3. demand_driven_analysis()
    4. find_sccs()
    5. optimization_analysis()
    6. print_call_graph()
    7. generate_optimized_code()   (new: rewrites the source using 1-5)

analyze_program(code) runs this exact sequence and returns a single
JSON-serializable results dict -- this is also what analyzer/api.py
hands back to a frontend.
"""
from .extraction import extract_functions
from .call_graph import build_call_graph
from .reachability import demand_driven_analysis
from .scc import find_sccs, classify_cycles
from .optimization import constant_propagation, optimization_analysis
from .codegen import generate_optimized_code


def analyze_program(code: str, entry: str = "main") -> dict:
    # 1. extract_functions()
    functions = extract_functions(code)

    # 2. build_call_graph()  (includes discover_calls / type / pointer / hybrid refinement)
    graph = build_call_graph(functions)

    # 3. demand_driven_analysis()
    reachable = demand_driven_analysis(graph, entry)

    # 4. find_sccs() & classify_cycles()
    sccs, recursive_functions = find_sccs(graph)
    cycle_analysis = classify_cycles(graph, sccs, reachable)

    # 5. optimization_analysis()  (constant_propagation runs first, feeds the heuristic)
    cp_results = constant_propagation(functions, graph)
    opt_results = optimization_analysis(functions, graph, recursive_functions, cp_results)

    all_names = set(functions.keys())

    errors = []
    if entry not in all_names:
        errors.append(
            f"Error: entry point '{entry}' was not found among the extracted "
            f"functions {sorted(all_names)}. Reachability analysis could not run."
        )

    # 7. generate_optimized_code()  (purely additive -- never affects the analysis above)
    try:
        optimized_program = generate_optimized_code(
            code, functions, opt_results, recursive_functions, reachable, entry
        )
    except Exception as exc:  # pragma: no cover - safety net
        optimized_program = {
            "code": code, "changed": False, "transformations": [],
            "removed_functions": [], "summary": {}, "error": f"Code generation failed: {exc}",
        }

    return {
        "entry_point": entry,
        "errors": errors,
        "functions": {name: f.to_dict() for name, f in functions.items()},
        "call_graph": graph.to_dict(),
        "reachable_functions": sorted(reachable),
        "unreachable_functions": sorted(all_names - reachable),
        "sccs": [sorted(s) for s in sccs],
        "recursive_functions": sorted(recursive_functions),
        "cycle_analysis": cycle_analysis,
        "constant_propagation": cp_results,
        "optimization_analysis": opt_results,
        "summary": {
            "function_count": len(functions),
            "edge_count": len(graph.edges),
            "indirect_call_edge_count": sum(
                1 for (_c, _t, ty) in graph.edges if ty != "DIRECT"
            ),
            "unresolved_indirect_calls": len(graph.unresolved),
            "reachable_count": len(reachable),
            "recursive_function_count": len(recursive_functions),
            "cycle_count": len(cycle_analysis["cycles"]),
            "dead_cycle_count": cycle_analysis["summary"]["dead_cycles"],
            "inline_recommended_count": sum(
                1 for r in opt_results.values() if r["decision"] == "INLINE"
            ),
        },
        "optimized_program": optimized_program,
    }


# 6. print_cycle_analysis()
def print_cycle_analysis(cycle_analysis: dict) -> None:
    cycles = cycle_analysis.get("cycles", []) if cycle_analysis else []
    if not cycles:
        print("\nCycle Analysis: No recursion or cycles detected (Call graph is acyclic / DAG).")
        return

    print("\n" + "=" * 70)
    print("Call Graph Cycle Analysis & Recursion Handling")
    print("=" * 70)
    for c in cycles:
        c_type = c["type"].replace("_", " ")
        print(f"  [{c_type:18s}] {c['path_display']}  [{c['status']}]")
        print(f"    Treatment: {c['treatment']}")


# 7. print_call_graph()
def print_call_graph(graph) -> None:
    print("Call Graph Edges:")
    for caller, callee, edge_type in sorted(graph.edges):
        arrow = "->"
        print(f"  {caller} {arrow} {callee} [{edge_type}]")
    if graph.unresolved:
        print("Unresolved indirect calls:")
        for caller, ptr_var in sorted(graph.unresolved):
            print(f"  {caller} -> {ptr_var}(...) [UNRESOLVED]")


# 7. print_optimized_code()
def print_optimized_code(results: dict) -> None:
    opt = results.get("optimized_program")
    if not opt:
        return
    print("\n" + "=" * 70)
    print("Optimized Code")
    print("=" * 70)
    if opt.get("error"):
        print(opt["error"])
    if opt["transformations"]:
        print("\nTransformations applied:")
        for t in opt["transformations"]:
            print(f"  [{t['type']:13s}] in {t['caller']}(): {t['before']}  ->  {t['after']}")
    else:
        print("\nNo safe transformations were applicable; code is unchanged.")
    for r in opt["removed_functions"]:
        print(f"  [REMOVED      ] {r['name']}(): {r['reason']}")
    s = opt.get("summary") or {}
    if s:
        print(f"\n{s['constant_folds']} constant fold(s), {s['inlined_calls']} inlined call(s), "
              f"{s['functions_removed']} function(s) removed "
              f"({s['original_lines']} -> {s['optimized_lines']} lines)")
    print("\n----- optimized program -----")
    print(opt["code"])