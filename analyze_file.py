"""
analyze_file.py
----------------
Command-line tool to run the full analyzer on ANY C source file the user
provides -- this is how a real user "submits code to optimize."

Usage:
    python analyze_file.py path/to/program.c
    python analyze_file.py path/to/program.c --entry main
    python analyze_file.py path/to/program.c --json            (raw JSON output)
    python analyze_file.py path/to/program.c --json out.json   (save JSON to a file)
    python analyze_file.py path/to/program.c -o optimized.c    (save optimized C code)

Examples (use the sample programs already in tests/):
    python analyze_file.py tests/recursion.c
    python analyze_file.py tests/function_pointers.c
    python analyze_file.py tests/direct_calls.c
"""
import argparse
import json
import sys

from analyzer import analyze_program, print_call_graph, print_optimized_code, print_cycle_analysis
from analyzer.call_graph import build_call_graph
from analyzer.extraction import extract_functions
from analyzer.syntax_check import check_syntax, format_errors


def human_readable_report(code: str, entry: str) -> dict:
    functions = extract_functions(code)
    if not functions:
        print("No functions could be extracted from this file. Check that it "
              "contains valid C function definitions (e.g. `int foo(int x) { ... }`).")
        sys.exit(1)

    print("=" * 70)
    print("Hybrid Interprocedural Call Graph Analyzer (C / C++)")
    print("=" * 70)
    print(f"\nExtracted {len(functions)} function(s): {sorted(functions)}\n")

    graph = build_call_graph(functions)
    print_call_graph(graph)

    results = analyze_program(code, entry=entry)

    if results["errors"]:
        for err in results["errors"]:
            print(f"\n{err}")

    print("\nReachable from", f"{entry}():", results["reachable_functions"])
    print("Unreachable functions:", results["unreachable_functions"])

    print("\nStrongly Connected Components:")
    for scc in results["sccs"]:
        print(" ", sorted(scc))
    print("Recursive functions:", results["recursive_functions"])

    print_cycle_analysis(results.get("cycle_analysis", {}))

    print("\nConstant Propagation Results:")
    if results["constant_propagation"]:
        for r in results["constant_propagation"]:
            print(f"  {r['caller']} calls {r['callee']}({', '.join(r['args'])})"
                  f"  =>  {r['substituted_expression']} = {r['result']}")
    else:
        print("  (no call sites with purely constant arguments were found)")

    print("\nInline Recommendations:")
    for name, rec in sorted(results["optimization_analysis"].items()):
        reasons = "; ".join(rec["reasons"]) if rec["reasons"] else "no score"
        print(f"  {name:15s} score={rec['score']:<3d} -> {rec['decision']:14s} ({reasons})")

    print("\nSummary:", results["summary"])

    # new: optimized code (everything above is unchanged)
    print_optimized_code(results)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Run the interprocedural call-graph + optimization analyzer on a C or C++ file."
    )
    parser.add_argument("source_file", help="Path to the .c or .cpp file to analyze")
    parser.add_argument("--entry", default="main", help="Entry-point function name (default: main)")
    parser.add_argument(
        "--output", "-o", default=None, metavar="OPT_FILE",
        help="Write the optimized C/C++ code to this file.",
    )
    parser.add_argument(
        "--json", nargs="?", const="-", default=None, metavar="OUT_FILE",
        help="Also output raw JSON. With no value, prints JSON to stdout; "
             "with a filename, writes JSON to that file instead.",
    )
    args = parser.parse_args()

    try:
        with open(args.source_file, encoding="utf-8") as f:
            code = f.read()
    except OSError as exc:
        print(f"Could not read '{args.source_file}': {exc}")
        sys.exit(1)

    check = check_syntax(code)
    if not check["ok"]:
        print(format_errors(check))
        sys.exit(1)

    results = human_readable_report(code, args.entry)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(results["optimized_program"]["code"])
        print(f"\nOptimized code written to {args.output}")

    if args.json:
        payload = json.dumps(results, indent=2)
        if args.json == "-":
            print("\n" + "=" * 70)
            print("RAW JSON OUTPUT")
            print("=" * 70)
            print(payload)
        else:
            with open(args.json, "w", encoding="utf-8") as f:
                f.write(payload)
            print(f"\nJSON report written to {args.json}")


if __name__ == "__main__":
    main()