"""
analyzer_demo.py
-----------------
Standalone demonstration driver, matching Review 2 Section 7.2 / 7.3 exactly:
a sample C program covering direct calls, function pointers, recursion and
mutual recursion, run through the full pipeline when this file is executed
directly.

Run:
    python analyzer_demo.py
"""
from analyzer import analyze_program, print_call_graph, print_optimized_code
from analyzer.call_graph import build_call_graph
from analyzer.extraction import extract_functions

# Demonstration program (Review 2, Section 7.2): square, increment,
# recursive, even, odd, main -- with direct calls, function pointers,
# recursion and mutual recursion, and a constant-argument call site.
source_code = r"""
#include <stdio.h>

int square(int x) {
    return x * x;
}

int increment(int x) {
    return x + 1;
}

int recursive(int n) {
    if (n <= 0) {
        return 0;
    }
    return recursive(n - 1);
}

int even(int n);
int odd(int n);

int even(int n) {
    if (n == 0) {
        return 1;
    }
    return odd(n - 1);
}

int odd(int n) {
    if (n == 0) {
        return 0;
    }
    return even(n - 1);
}

int main() {
    int (*fp)(int) = square;
    int a = fp(5);

    int (*gp)(int);
    gp = increment;
    int b = gp(a);

    int r = recursive(3);
    int e = even(4);
    int s = square(5);

    printf("%d %d %d %d %d\n", a, b, r, e, s);
    return 0;
}
"""


def main():
    print("=" * 70)
    print("Hybrid Interprocedural Call Graph Analyzer -- Demonstration Run")
    print("=" * 70)

    functions = extract_functions(source_code)
    print(f"\nExtracted {len(functions)} functions: {sorted(functions)}\n")

    graph = build_call_graph(functions)
    print_call_graph(graph)

    results = analyze_program(source_code, entry="main")

    print("\nReachable from main():", results["reachable_functions"])
    print("Unreachable functions:", results["unreachable_functions"])

    print("\nStrongly Connected Components:")
    for scc in results["sccs"]:
        print(" ", sorted(scc))
    print("Recursive functions:", results["recursive_functions"])

    print("\nConstant Propagation Results:")
    for r in results["constant_propagation"]:
        print(f"  {r['caller']} calls {r['callee']}({', '.join(r['args'])})"
              f"  =>  {r['substituted_expression']} = {r['result']}")

    print("\nInline Recommendations:")
    for name, rec in sorted(results["optimization_analysis"].items()):
        reasons = "; ".join(rec["reasons"]) if rec["reasons"] else "no score"
        print(f"  {name:12s} score={rec['score']:<3d} -> {rec['decision']:14s} ({reasons})")

    print("\nSummary:", results["summary"])

    print_optimized_code(results)


if __name__ == "__main__":
    main()