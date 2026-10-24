"""
optimization.py
----------------
Module 2 (Review 2, Sections 6.4 - 6.5): constant propagation and the
function-inlining heuristic.

constant_propagation():
    "replaces numeric parameters with constant arguments... restricts
    expressions to simple arithmetic expressions before evaluation."

optimization_analysis():
    Inline score table (exactly as specified):
        Constant arguments              +5
        Constant propagation possible   +5
        Function size <= 20 lines       +3
    Decision rule: score >= 10 -> INLINE, else DO NOT INLINE.
    Recursive functions are skipped from the inline recommendation stage.
"""
import ast
import re

_NUMERIC_LITERAL_RE = re.compile(r"^(-?\d+(\.\d+)?|true|false)$")
_SIMPLE_RETURN_RE = re.compile(r"^\{\s*return\s+(?P<expr>.+?)\s*;\s*\}$", re.DOTALL)


def _extract_simple_return_expr(body: str):
    """If `body` is exactly a single `{ return <expr>; }` statement, return
    the expression string. Otherwise return None (not a 'simple' function
    per the documented limitation)."""
    m = _SIMPLE_RETURN_RE.match(body.strip())
    return m.group("expr") if m else None


class _UnsupportedExpression(ValueError):
    pass


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left ** right
        raise _UnsupportedExpression("unsupported binary operator")
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return +value
        raise _UnsupportedExpression("unsupported unary operator")
    raise _UnsupportedExpression(f"unsupported expression node: {type(node).__name__}")


def _safe_eval_arithmetic(expr: str):
    """Evaluate a restricted arithmetic expression (+, -, *, /, //, %, **,
    parentheses, numeric literals only). Raises _UnsupportedExpression for
    anything else -- never calls Python's built-in eval()."""
    # Map C/C++ boolean literals to Python integers
    py_expr = re.sub(r"\btrue\b", "1", expr)
    py_expr = re.sub(r"\bfalse\b", "0", py_expr)
    tree = ast.parse(py_expr, mode="eval")
    return _eval_node(tree.body)


def _substitute_params(expr: str, param_names, arg_values) -> str:
    for pname, aval in zip(param_names, arg_values):
        expr = re.sub(rf"\b{re.escape(pname)}\b", aval, expr)
    return expr


def constant_propagation(functions: dict, graph) -> list:
    """For every DIRECT call site passing only constant (numeric literal)
    arguments to a 'simple' callee (a single `return <expr>;` body),
    substitute and evaluate the result.

    Returns a list of result records:
        {caller, callee, args, original_expression, substituted_expression, result}
    """
    results = []
    direct_pairs = {(c, t) for (c, t, ty) in graph.edges if ty == "DIRECT"}

    for caller_name, callee_name in sorted(direct_pairs):
        caller = functions[caller_name]
        callee = functions[callee_name]

        simple_expr = _extract_simple_return_expr(callee.body)
        if simple_expr is None:
            continue
        param_names = [n for _t, n in callee.parameters]

        for m in re.finditer(rf"\b{re.escape(callee_name)}\s*\(\s*([^)]*)\s*\)", caller.body):
            raw_args = m.group(1).strip()
            args = [a.strip() for a in raw_args.split(",")] if raw_args else []
            if len(args) != len(param_names) or not args:
                continue
            if not all(_NUMERIC_LITERAL_RE.match(a) for a in args):
                continue

            substituted = _substitute_params(simple_expr, param_names, args)
            try:
                value = _safe_eval_arithmetic(substituted)
            except (_UnsupportedExpression, SyntaxError, ZeroDivisionError):
                continue

            results.append({
                "caller": caller_name,
                "callee": callee_name,
                "args": args,
                "original_expression": simple_expr,
                "substituted_expression": substituted,
                "result": value,
            })

    return results


def optimization_analysis(functions: dict, graph, recursive_functions: set, cp_results=None) -> dict:
    """Inline-decision heuristic (Review 2, Section 6.5)."""
    cp_results = cp_results or []
    cp_targets = {r["callee"] for r in cp_results}

    const_arg_targets = set()
    direct_pairs = {(c, t) for (c, t, ty) in graph.edges if ty == "DIRECT"}
    for caller_name, callee_name in direct_pairs:
        caller = functions[caller_name]
        for m in re.finditer(rf"\b{re.escape(callee_name)}\s*\(\s*([^)]*)\s*\)", caller.body):
            raw_args = m.group(1).strip()
            args = [a.strip() for a in raw_args.split(",")] if raw_args else []
            if args and all(_NUMERIC_LITERAL_RE.match(a) for a in args):
                const_arg_targets.add(callee_name)
                break

    results = {}
    for name, func in functions.items():
        if name in recursive_functions:
            results[name] = {
                "score": 0,
                "decision": "DO NOT INLINE",
                "reasons": ["Recursive function - skipped from inline recommendation stage"],
                "skipped_recursive": True,
            }
            continue

        score = 0
        reasons = []
        if name in const_arg_targets:
            score += 5
            reasons.append("Called with constant arguments (+5)")
        if name in cp_targets:
            score += 5
            reasons.append("Constant propagation possible (+5)")
        if func.line_count <= 20:
            score += 3
            reasons.append(f"Function size <= 20 lines ({func.line_count} lines) (+3)")

        decision = "INLINE" if score >= 10 else "DO NOT INLINE"
        results[name] = {
            "score": score,
            "decision": decision,
            "reasons": reasons,
            "skipped_recursive": False,
        }

    return results
