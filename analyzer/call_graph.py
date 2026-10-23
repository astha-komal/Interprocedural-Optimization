"""
call_graph.py
-------------
Module 1 (Review 2, Section 5.6): hybrid call-graph construction.

    Refined Targets = Type-Based Targets ∩ Pointer-Based Targets

If the intersection is non-empty the edge is classified POINTER-REFINED.
Otherwise the system falls back to pointer or type information when
available. Edge types, exactly as specified in the report:
    DIRECT | POINTER-REFINED | POINTER | TYPE-FALLBACK
"""
from .call_discovery import discover_calls
from .type_analysis import type_based_analysis
from .pointer_analysis import pointer_analysis


class CallGraph:
    def __init__(self):
        self.nodes = set()
        self.edges = set()       # {(caller, callee, edge_type)}
        self.unresolved = set()  # {(caller, pointer_var)} indirect calls we could not resolve at all

    def add_edge(self, caller: str, callee: str, edge_type: str) -> None:
        self.nodes.add(caller)
        self.nodes.add(callee)
        self.edges.add((caller, callee, edge_type))

    def successors(self, name: str):
        return sorted({callee for (c, callee, _t) in self.edges if c == name})

    def successors_with_type(self, name: str):
        return sorted({(callee, t) for (c, callee, t) in self.edges if c == name})

    def to_dict(self) -> dict:
        return {
            "nodes": sorted(self.nodes),
            "edges": sorted(
                [{"from": c, "to": t, "type": ty} for (c, t, ty) in self.edges],
                key=lambda e: (e["from"], e["to"], e["type"]),
            ),
            "unresolved": sorted(
                [{"from": c, "pointer_var": v} for (c, v) in self.unresolved],
                key=lambda e: (e["from"], e["pointer_var"]),
            ),
        }


# alias matching the Review 2 function name used for a single edge insertion
def add_edge(graph: CallGraph, caller: str, callee: str, edge_type: str) -> None:
    graph.add_edge(caller, callee, edge_type)


def build_call_graph(functions: dict) -> CallGraph:
    """Module 1 orchestration: discover calls for every function, run the
    type-based and pointer-based analyses, hybrid-refine them, and build
    the resulting CallGraph (Review 2, Sections 5.1-5.6)."""
    known_names = set(functions.keys())

    for func in functions.values():
        discover_calls(func, known_names)

    type_candidates = type_based_analysis(functions)
    pointer_candidates = pointer_analysis(functions)

    graph = CallGraph()
    graph.nodes = set(functions.keys())

    for func in functions.values():
        # direct calls
        for callee in func.direct_calls:
            add_edge(graph, func.name, callee, "DIRECT")

        # indirect calls -> hybrid refinement
        for ptr_var in func.indirect_calls:
            type_set = type_candidates.get(func.name, {}).get(ptr_var, set())
            ptr_set = pointer_candidates.get(func.name, {}).get(ptr_var, set())
            refined = type_set & ptr_set

            if refined:
                for t in refined:
                    add_edge(graph, func.name, t, "POINTER-REFINED")
            elif ptr_set:
                for t in ptr_set:
                    add_edge(graph, func.name, t, "POINTER")
            elif type_set:
                for t in type_set:
                    add_edge(graph, func.name, t, "TYPE-FALLBACK")
            else:
                graph.unresolved.add((func.name, ptr_var))

    return graph
