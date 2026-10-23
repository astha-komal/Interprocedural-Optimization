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
