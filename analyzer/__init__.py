"""
Hybrid Interprocedural Call Graph Analyzer with Optimization Analysis
BCSE307 - Compiler Design Project (Project ID A16)

Public API re-exported here so callers can do:
    from analyzer import analyze_program
"""
from .pipeline import analyze_program, print_call_graph, print_optimized_code, print_cycle_analysis
from .scc import classify_cycles, find_sccs
from .syntax_check import is_cpp

__all__ = ["analyze_program", "print_call_graph", "print_optimized_code", "print_cycle_analysis", "classify_cycles", "find_sccs", "is_cpp"]