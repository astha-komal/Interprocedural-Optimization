"""
Hybrid Interprocedural Call Graph Analyzer with Optimization Analysis
BCSE307 - Compiler Design Project (Project ID A16)

Public API re-exported here so callers can do:
    from analyzer import analyze_program
"""
from .pipeline import analyze_program, print_call_graph, print_optimized_code

__all__ = ["analyze_program", "print_call_graph", "print_optimized_code"]