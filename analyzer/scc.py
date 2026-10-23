"""
scc.py
------
Module 2 (Review 2, Section 6.3): SCC-based recursion detection.

Tarjan's algorithm, using the exact state names named in the report:
    indices, lowlink, stack, on_stack

Identifies:
    Direct recursion    : recursive -> recursive   (self-loop)
    Mutual recursion     : even -> odd, odd -> even (multi-node SCC)

Functions belonging to recursive SCCs are returned in `recursive_functions`.
"""
from collections import deque


def find_sccs(graph):
    """Tarjan's strongly-connected-components algorithm.

    Returns (sccs, recursive_functions):
        sccs                -- list of sets, each set one SCC
        recursive_functions -- set of function names that are recursive
                                (SCC size > 1, i.e. mutual recursion, OR
                                 a direct self-loop, i.e. simple recursion)
    """
    indices = {}
    lowlink = {}
    on_stack = {}
    stack = []
    sccs = []
    index_counter = [0]

    # iterative Tarjan to avoid Python recursion-depth limits on larger graphs
    def strongconnect(start):
        work = [(start, iter(graph.successors(start)))]
        indices[start] = lowlink[start] = index_counter[0]
        index_counter[0] += 1
        stack.append(start)
        on_stack[start] = True

        while work:
            node, succ_iter = work[-1]
            advanced = False
            for succ in succ_iter:
                if succ not in indices:
                    indices[succ] = lowlink[succ] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(succ)
                    on_stack[succ] = True
                    work.append((succ, iter(graph.successors(succ))))
                    advanced = True
                    break
                elif on_stack.get(succ):
                    lowlink[node] = min(lowlink[node], indices[succ])
            if advanced:
                continue

            # all successors of `node` processed
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])

            if lowlink[node] == indices[node]:
                component = set()
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    component.add(w)
                    if w == node:
                        break
                sccs.append(component)

    for node in sorted(graph.nodes):
        if node not in indices:
            strongconnect(node)

    # direct self-loop check (simple recursion: f -> f)
    self_loop = {c for (c, t, _ty) in graph.edges if c == t}

    recursive_functions = set(self_loop)
    for component in sccs:
        if len(component) > 1:
            recursive_functions |= component

    return sccs, recursive_functions


def _find_cycle_path(graph, component):
    if len(component) == 1:
        node = next(iter(component))
        return [node, node]
    start = min(component)
    queue = deque([[start]])
    while queue:
        path = queue.popleft()
        curr = path[-1]
        for succ in graph.successors(curr):
            if succ not in component:
                continue
            if succ == start and len(path) >= 1:
                return path + [start]
            if succ not in path:
                queue.append(path + [succ])
    return sorted(component) + [min(component)]


def classify_cycles(graph, sccs, reachable=None) -> dict:
    """Classifies cycles in the call graph into:
        - DIRECT_RECURSION   (self-loop: f -> f)
        - MUTUAL_RECURSION   (cycle of size 2: f1 <-> f2)
        - INDIRECT_RECURSION (cycle of size >= 3: f1 -> f2 -> f3 -> f1)

    Determines if each cycle is REACHABLE (live code, protected against self-inlining)
    or DEAD_CODE (unreachable, candidate for elimination).
    """
    self_loop = {c for (c, t, _ty) in graph.edges if c == t}
    cycles = []
    direct_count = 0
    mutual_count = 0
    indirect_count = 0
    reachable_count = 0
    dead_count = 0

    # 1. Process multi-node SCCs
    for component in sorted(sccs, key=lambda c: sorted(c)):
        if len(component) > 1:
            size = len(component)
            c_type = "MUTUAL_RECURSION" if size == 2 else "INDIRECT_RECURSION"
            if size == 2:
                mutual_count += 1
            else:
                indirect_count += 1

            path = _find_cycle_path(graph, component)
            path_display = " -> ".join(path)
            is_reachable = any(fn in reachable for fn in component) if reachable is not None else True

            if is_reachable:
                status = "REACHABLE"
                reachable_count += 1
                treatment = (
                    "Reachable cycle preserved; inlining blocked on recursive edges to prevent "
                    "infinite expansion; callee inlining inside cycle remains active."
                )
            else:
                status = "DEAD_CODE"
                dead_count += 1
                treatment = "Unreachable recursive cycle eliminated by dead-function removal."

            cycles.append({
                "type": c_type,
                "size": size,
                "functions": sorted(component),
                "path": path,
                "path_display": path_display,
                "status": status,
                "treatment": treatment,
            })

    # 2. Process self-loops (direct recursion)
    for node in sorted(self_loop):
        direct_count += 1
        path = [node, node]
        path_display = f"{node} -> {node}"
        is_reachable = (node in reachable) if reachable is not None else True

        if is_reachable:
            status = "REACHABLE"
            reachable_count += 1
            treatment = (
                "Reachable self-loop preserved; self-inlining blocked to prevent infinite expansion; "
                "callee inlining inside function remains active."
            )
        else:
            status = "DEAD_CODE"
            dead_count += 1
            treatment = "Unreachable recursive function eliminated by dead-function removal."

        cycles.append({
            "type": "DIRECT_RECURSION",
            "size": 1,
            "functions": [node],
            "path": path,
            "path_display": path_display,
            "status": status,
            "treatment": treatment,
        })

    return {
        "cycles": cycles,
        "summary": {
            "total_cycles": len(cycles),
            "direct_recursion_count": direct_count,
            "mutual_recursion_count": mutual_count,
            "indirect_recursion_count": indirect_count,
            "reachable_cycles": reachable_count,
            "dead_cycles": dead_count,
        },
    }
