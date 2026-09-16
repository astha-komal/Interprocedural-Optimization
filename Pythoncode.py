import re
from collections import defaultdict, deque


# ============================================================
# DATA STRUCTURES
# ============================================================

class Function:
    def __init__(self, name, return_type, params, body):
        self.name = name
        self.return_type = return_type
        self.params = params
        self.body = body

        self.direct_calls = []
        self.indirect_calls = []
        self.pointer_assignments = []
        self.returned_functions = []

        # Number of non-empty source lines
        self.size = len([
            line for line in body.splitlines()
            if line.strip()
        ])

    def signature(self):
        types = ", ".join(p[0] for p in self.params)
        return f"{self.return_type} ({types})"


# ============================================================
# GLOBAL DATA
# ============================================================

functions = {}
edges = []
reachable = set()
recursive_functions = set()
sccs = []


# ============================================================
# UTILITY
# ============================================================

def normalize_type(t):
    t = re.sub(
        r'\b(const|volatile|static|extern|register)\b',
        '',
        t
    )
    return " ".join(t.split()).strip()


def parse_parameters(text):
    text = text.strip()

    if not text or text == "void":
        return []

    params = []

    for p in text.split(","):
        p = p.strip()

        match = re.match(
            r'(.+?)\s+([A-Za-z_]\w*)$',
            p
        )

        if match:
            param_type = normalize_type(match.group(1))
            name = match.group(2)
        else:
            param_type = normalize_type(p)
            name = "param"

        params.append((param_type, name))

    return params


def remove_comments(code):
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.S)
    code = re.sub(r'//.*', '', code)
    return code


# ============================================================
# 1. FUNCTION EXTRACTION
# ============================================================

def extract_functions(code):

    code = remove_comments(code)

    pattern = re.compile(
        r'(?:^|[;\n}])\s*'
        r'(?:(?:static|inline|extern)\s+)?'
        r'([A-Za-z_]\w*)\s+'
        r'([A-Za-z_]\w*)\s*'
        r'\(([^{};]*)\)\s*\{',
        re.MULTILINE
    )

    for match in pattern.finditer(code):

        return_type = normalize_type(match.group(1))
        name = match.group(2)
        params = parse_parameters(match.group(3))

        open_brace = code.find("{", match.start())
        close_brace = find_matching_brace(
            code,
            open_brace
        )

        if close_brace == -1:
            continue

        body = code[
            open_brace + 1:
            close_brace
        ]

        functions[name] = Function(
            name,
            return_type,
            params,
            body
        )

    return functions


def find_matching_brace(code, start):

    depth = 0

    for i in range(start, len(code)):

        if code[i] == "{":
            depth += 1

        elif code[i] == "}":
            depth -= 1

            if depth == 0:
                return i

    return -1


# ============================================================
# 2. CALL AND FUNCTION-POINTER DISCOVERY
# ============================================================

def discover_calls(function):

    body = function.body

    # --------------------------------------------------------
    # Function pointer initialization
    #
    # int (*fp)(int) = foo;
    # --------------------------------------------------------

    pattern = re.compile(
        r'(?:int|float|double|char|void|long|short)'
        r'\s*\(\s*\*\s*(\w+)\s*\)'
        r'\s*\([^)]*\)\s*=\s*(\w+)\s*;'
    )

    for match in pattern.finditer(body):

        pointer = match.group(1)
        target = match.group(2)

        if target in functions:

            function.pointer_assignments.append(
                (pointer, target)
            )

    # --------------------------------------------------------
    # Function pointer assignment
    #
    # fp = foo;
    # --------------------------------------------------------

    assignment_pattern = re.compile(
        r'\b(\w+)\s*=\s*(\w+)\s*;'
    )

    for match in assignment_pattern.finditer(body):

        pointer = match.group(1)
        target = match.group(2)

        if target in functions:

            function.pointer_assignments.append(
                (pointer, target)
            )

    # --------------------------------------------------------
    # Function calls
    # --------------------------------------------------------

    call_pattern = re.compile(
        r'\b([A-Za-z_]\w*)\s*\(([^()]*)\)'
    )

    ignored = {
        "if",
        "for",
        "while",
        "switch",
        "sizeof",
        "printf",
        "scanf"
    }

    for match in call_pattern.finditer(body):

        name = match.group(1)

        if name in ignored:
            continue

        args = [
            x.strip()
            for x in match.group(2).split(",")
            if x.strip()
        ]

        # Direct call
        if name in functions:

            function.direct_calls.append(
                (name, args)
            )

        # Indirect call through function pointer
        else:

            pointers = {
                p for p, _ in
                function.pointer_assignments
            }

            if name in pointers:

                function.indirect_calls.append(
                    (name, args)
                )

    # --------------------------------------------------------
    # Return of function address
    #
    # return foo;
    # --------------------------------------------------------

    return_pattern = re.compile(
        r'\breturn\s+([A-Za-z_]\w*)\s*;'
    )

    for match in return_pattern.finditer(body):

        name = match.group(1)

        if name in functions:

            function.returned_functions.append(name)


# ============================================================
# 3. TYPE-BASED ANALYSIS
# ============================================================

def type_based_analysis(function, indirect_call):

    pointer, args = indirect_call

    candidates = []

    # Find the declaration/assignment of the pointer
    assignments = [
        target
        for p, target in
        function.pointer_assignments
        if p == pointer
    ]

    if assignments:

        # Candidate functions from observed compatible assignment
        for target in assignments:

            if target in functions:

                candidates.append(target)

    # If no direct assignment is known,
    # use argument count as a simple type approximation.
    if not candidates:

        argument_count = len(args)

        for f in functions.values():

            if len(f.params) == argument_count:

                candidates.append(f.name)

    print(
        f"[TYPE] {function.name}: "
        f"{pointer} -> {candidates}"
    )

    return candidates


# ============================================================
# 4. POINTER ANALYSIS
# ============================================================

def pointer_analysis(function, indirect_call):

    pointer, args = indirect_call

    targets = set()

    # --------------------------------------------------------
    # Local pointer assignments
    #
    # fp = foo;
    #
    # Therefore:
    #
    # Tf(fp) = {foo}
    # --------------------------------------------------------

    for p, target in function.pointer_assignments:

        if p == pointer:

            if target in functions:

                targets.add(target)

    # --------------------------------------------------------
    # Returned function pointers
    #
    # getFunction() returns foo
    #
    # caller:
    # fp = getFunction();
    #
    # Therefore:
    #
    # Tf(fp) = {foo}
    # --------------------------------------------------------

    for f in functions.values():

        for returned in f.returned_functions:

            targets.add(returned)

    print(
        f"[POINTER] {function.name}: "
        f"{pointer} -> {list(targets)}"
    )

    return list(targets)


# ============================================================
# 5. BUILD HYBRID CALL GRAPH
# ============================================================

def add_edge(source, target, edge_type):

    edge = (
        source,
        target,
        edge_type
    )

    if edge not in edges:

        edges.append(edge)


def build_call_graph():

    global edges

    edges = []

    # First discover calls
    for function in functions.values():

        discover_calls(function)

    # -----------------------------------------
    # Direct calls
    # -----------------------------------------

    for function in functions.values():

        for target, args in function.direct_calls:

            add_edge(
                function.name,
                target,
                "DIRECT"
            )

    # -----------------------------------------
    # Indirect calls
    # -----------------------------------------

    for function in functions.values():

        for call in function.indirect_calls:

            type_targets = type_based_analysis(
                function,
                call
            )

            pointer_targets = pointer_analysis(
                function,
                call
            )

            # ---------------------------------
            # Hybrid refinement
            #
            # Type ∩ Pointer
            # ---------------------------------

            refined = set(type_targets) & \
                      set(pointer_targets)

            if refined:

                for target in refined:

                    add_edge(
                        function.name,
                        target,
                        "POINTER-REFINED"
                    )

            # If pointer information exists but
            # type information failed
            elif pointer_targets:

                for target in pointer_targets:

                    add_edge(
                        function.name,
                        target,
                        "POINTER"
                    )

            # Conservative fallback
            elif type_targets:

                for target in type_targets:

                    add_edge(
                        function.name,
                        target,
                        "TYPE-FALLBACK"
                    )


# ============================================================
# 6. DEMAND-DRIVEN ANALYSIS
# ============================================================

def demand_driven_analysis():

    global reachable

    reachable = set()

    if "main" not in functions:

        print("ERROR: main() not found.")
        return

    queue = deque(["main"])

    reachable.add("main")

    print("\n[DEMAND] Starting from main()")

    while queue:

        current = queue.popleft()

        for source, target, edge_type in edges:

            if source != current:
                continue

            if target not in reachable:

                reachable.add(target)

                queue.append(target)

                print(
                    f"[WORKLIST] "
                    f"{source} -> {target}"
                )

    print(
        f"[DEMAND] Fixed point reached."
    )

    print(
        f"Reachable functions: "
        f"{reachable}"
    )


# ============================================================
# 7. SCC / RECURSION DETECTION
# ============================================================

def find_sccs():

    global sccs
    global recursive_functions

    sccs = []
    recursive_functions = set()

    graph = defaultdict(list)

    for source, target, edge_type in edges:

        if source in reachable and \
           target in reachable:

            graph[source].append(target)

    index = 0

    indices = {}
    lowlink = {}

    stack = []

    on_stack = set()

    def strong_connect(v):

        nonlocal index

        indices[v] = index
        lowlink[v] = index

        index += 1

        stack.append(v)
        on_stack.add(v)

        for w in graph[v]:

            if w not in indices:

                strong_connect(w)

                lowlink[v] = min(
                    lowlink[v],
                    lowlink[w]
                )

            elif w in on_stack:

                lowlink[v] = min(
                    lowlink[v],
                    indices[w]
                )

        if lowlink[v] == indices[v]:

            component = []

            while True:

                w = stack.pop()

                on_stack.remove(w)

                component.append(w)

                if w == v:
                    break

            sccs.append(component)

    for node in reachable:

        if node not in indices:

            strong_connect(node)

    # Identify recursive SCCs
    for component in sccs:

        # Mutual recursion
        if len(component) > 1:

            recursive_functions.update(
                component
            )

            print(
                "[SCC] Mutual recursion:",
                component
            )

        # Direct recursion
        elif len(component) == 1:

            f = component[0]

            for source, target, _ in edges:

                if source == f and target == f:

                    recursive_functions.add(f)

                    print(
                        "[SCC] Direct recursion:",
                        f
                    )


# ============================================================
# 8. CONSTANT PROPAGATION
# ============================================================

def constant_propagation(function, args):

    body = function.body

    # Replace parameters with constants
    for i, (_, parameter) in enumerate(function.params):

        if i < len(args):

            value = args[i]

            if re.fullmatch(
                r'-?\d+',
                value
            ):

                body = re.sub(
                    rf'\b{re.escape(parameter)}\b',
                    value,
                    body
                )

    match = re.search(
        r'return\s+([^;]+);',
        body
    )

    if not match:
        return None

    expression = match.group(1)

    # Only permit simple arithmetic
    if not re.fullmatch(
        r'[\d\s+\-*/%().]+',
        expression
    ):
        return None

    try:

        # Demo-only arithmetic evaluation
        value = eval(
            expression,
            {"__builtins__": {}},
            {}
        )

        return value

    except Exception:

        return None


# ============================================================
# 9. INLINE HEURISTIC
# ============================================================

def optimization_analysis():

    print("\n========== OPTIMIZATION ==========")

    for function in functions.values():

        if function.name not in reachable:
            continue

        # Do not inline recursive functions
        if function.name in recursive_functions:

            print(
                f"[INLINE] {function.name}: "
                f"SKIP - recursive"
            )

    for caller in functions.values():

        if caller.name not in reachable:
            continue

        for target, args in caller.direct_calls:

            callee = functions[target]

            if target in recursive_functions:

                continue

            score = 0
            reasons = []

            # +5 constant arguments
            if args and all(
                re.fullmatch(r'-?\d+', x)
                for x in args
            ):

                score += 5
                reasons.append(
                    "+5 constant arguments"
                )

            # Constant propagation opportunity
            value = constant_propagation(
                callee,
                args
            )

            if value is not None:

                score += 5

                reasons.append(
                    "+5 constant propagation"
                )

            # Small function
            if callee.size <= 20:

                score += 3

                reasons.append(
                    "+3 small function"
                )

            # Decision
            if score >= 10:

                decision = "INLINE"

            else:

                decision = "DO NOT INLINE"

            print(
                f"\n{caller.name} -> "
                f"{target}({', '.join(args)})"
            )

            print(
                f"Score = {score}"
            )

            print(
                "Reasons:",
                ", ".join(reasons)
            )

            print(
                "Decision:",
                decision
            )

            if value is not None:

                print(
                    f"Constant result: "
                    f"{target}({', '.join(args)}) "
                    f"= {value}"
                )


# ============================================================
# 10. PRINT CALL GRAPH
# ============================================================

def print_call_graph():

    print("\n========== CALL GRAPH ==========")

    for source, target, edge_type in edges:

        if source in reachable and \
           target in reachable:

            print(
                f"{source} -> {target} "
                f"[{edge_type}]"
            )


# ============================================================
# 11. MAIN ALGORITHM
# ============================================================

def analyze_program(code):

    print(
        "\n======================================"
    )

    print(
        "HYBRID INTERPROCEDURAL ANALYZER"
    )

    print(
        "======================================"
    )

    # Step 1
    extract_functions(code)

    print(
        "\nFunctions:"
    )

    for f in functions.values():

        print(
            f"  {f.name} : "
            f"{f.signature()}"
        )

    # Step 2-5
    build_call_graph()

    # Step 6
    demand_driven_analysis()

    # Step 7
    find_sccs()

    # Step 8-9
    optimization_analysis()

    # Step 10
    print_call_graph()


# ============================================================
# SAMPLE PROGRAM
# ============================================================

source_code = r'''

int square(int x)
{
    return x * x;
}

int increment(int x)
{
    return x + 1;
}

int recursive(int n)
{
    if (n <= 0)
        return 0;

    return recursive(n - 1);
}

int even(int n)
{
    if (n == 0)
        return 1;

    return odd(n - 1);
}

int odd(int n)
{
    if (n == 0)
        return 0;

    return even(n - 1);
}

int main()
{
    int (*fp)(int) = square;

    int a = fp(5);

    int (*gp)(int);

    gp = increment;

    int b = gp(a);

    recursive(3);

    even(4);

    return 0;
}

'''


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    analyze_program(source_code)
