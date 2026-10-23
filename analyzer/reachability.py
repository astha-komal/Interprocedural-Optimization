"""
reachability.py
----------------
Module 2 (Review 2, Section 6.2): demand-driven reachability analysis.

"The analysis begins from main(). A queue is used as a worklist. The
algorithm repeatedly: removes a function from the queue, checks its
outgoing edges, adds previously unseen target functions, continues
until the queue becomes empty." Implemented with Python's deque,
exactly as described.
"""
from collections import deque


def demand_driven_analysis(graph, entry: str = "main") -> set:
    """Breadth-first worklist reachability from `entry`.
    Returns the set of function names reachable from `entry` (entry included,
    if it exists in the graph)."""
    if entry not in graph.nodes:
        return set()

    reachable = {entry}
    worklist = deque([entry])

    while worklist:
        current = worklist.popleft()
        for callee in graph.successors(current):
            if callee not in reachable:
                reachable.add(callee)
                worklist.append(callee)

    return reachable
