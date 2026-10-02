"""Static analysis: turn source code into a list of :class:`Issue` objects.

Two sources of evidence are combined:

* **pyflakes** - a mature checker for undefined names, unused imports and
  variables, etc.  Using it gives us *scope-aware* results (the old prototype
  flagged every function call, even ``print``).
* **AST rules** written for this project (mutable default arguments, division
  by a literal zero).
"""

from __future__ import annotations

import ast

from pyflakes import checker as _flakes

from .astutils import FUNC_TYPES, is_zero_constant, mutable_defaults
from .models import Issue

_PYFLAKES_RULES = {
    "UndefinedName": ("undefined-name", "error"),
    "UnusedVariable": ("unused-variable", "warning"),
    "UnusedImport": ("unused-import", "warning"),
    "ImportStarUsed": ("import-star", "warning"),
    "RedefinedWhileUnused": ("redefined-unused", "warning"),
    "ReturnOutsideFunction": ("return-outside-function", "error"),
    "DuplicateArgument": ("duplicate-argument", "error"),
    "IsLiteral": ("is-literal", "warning"),
}


def _from_pyflakes(msg) -> Issue:
    cls = type(msg).__name__
    rule, severity = _PYFLAKES_RULES.get(cls, (f"pyflakes-{cls}", "warning"))
    args = getattr(msg, "message_args", ())
    details = {"name": args[0]} if args else {}
    return Issue(
        rule=rule,
        message=msg.message % args,
        line=msg.lineno,
        col=getattr(msg, "col", 0),
        severity=severity,
        details=details,
    )


def _ast_rules(tree: ast.AST) -> list[Issue]:
    issues: list[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, FUNC_TYPES):
            for arg, default in mutable_defaults(node):
                issues.append(
                    Issue(
                        rule="mutable-default",
                        message=f"Mutable default value for argument '{arg.arg}' in {node.name}()",
                        line=default.lineno,
                        col=default.col_offset,
                        details={"function": node.name, "name": arg.arg},
                    )
                )
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append(
                Issue(
                    rule="bare-except",
                    message="Bare except also catches KeyboardInterrupt and SystemExit",
                    line=node.lineno,
                    col=node.col_offset,
                )
            )
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod))
            and is_zero_constant(node.right)
        ):
            issues.append(
                Issue(
                    rule="literal-zero-division",
                    message="Division by a literal zero always raises ZeroDivisionError",
                    line=node.lineno,
                    col=node.col_offset,
                    severity="error",
                )
            )
    return issues


def analyze(source: str) -> list[Issue]:
    """Return all statically detectable issues, sorted by position."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [
            Issue(
                rule="syntax-error",
                message=exc.msg,
                line=exc.lineno or 1,
                col=max((exc.offset or 1) - 1, 0),
                severity="error",
            )
        ]
    issues = [_from_pyflakes(m) for m in _flakes.Checker(tree, filename="<input>").messages]
    issues.extend(_ast_rules(tree))
    return sorted(issues, key=lambda i: (i.line, i.col, i.rule))
