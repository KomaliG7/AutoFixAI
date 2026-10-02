"""Fixers that only need the source code (no execution required)."""

from __future__ import annotations

import ast
import difflib
import re
import sys
from typing import Optional

from ..astutils import (
    FUNC_TYPES,
    bound_names,
    callable_names,
    is_pure,
    mutable_defaults,
)
from ..models import Fix, TextEdit
from .base import Context, Fixer, node_edit

_STDLIB = getattr(sys, "stdlib_module_names", frozenset())
_NOT_AUTO_IMPORTED = {"this", "antigravity"}  # importing these has side effects


class UndefinedNameFixer(Fixer):
    """Fix ``NameError``-style bugs: typos in names and missing standard-library imports."""

    rule = "undefined-name"

    def propose(self, ctx: Context) -> list[Fix]:
        call_sites = {
            (n.func.lineno, n.func.col_offset)
            for n in ast.walk(ctx.tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        attr_bases = {
            (n.value.lineno, n.value.col_offset)
            for n in ast.walk(ctx.tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
        }
        all_names = bound_names(ctx.tree)
        callables = callable_names(ctx.tree)
        fixes: list[Fix] = []
        imported: set[str] = set()

        for issue in ctx.issues:
            if issue.rule != self.rule:
                continue
            name = issue.details.get("name", "")
            pos = (issue.line, issue.col)

            # 1) `os.getcwd()` with no `import os`  ->  add the import.
            if name in _STDLIB and name not in _NOT_AUTO_IMPORTED and pos in attr_bases:
                if name not in imported:
                    imported.add(name)
                    fixes.append(self._add_import(ctx, name, issue.line))
                continue

            # 2) Typo: pick the closest name that is actually defined.
            pool = callables if pos in call_sites else all_names
            match = difflib.get_close_matches(name, sorted(pool - {name}), n=1, cutoff=0.7)
            if not match:
                continue
            best = match[0]
            ratio = difflib.SequenceMatcher(None, name, best).ratio()
            end_col = issue.col + len(name.encode("utf-8"))
            fixes.append(
                Fix(
                    rule=self.rule,
                    description=f"Rename '{name}' to '{best}'",
                    line=issue.line,
                    edits=[TextEdit(issue.line, issue.col, issue.line, end_col, best)],
                    confidence=round(ratio, 2),
                    reason=(
                        f"'{name}' is not defined anywhere, but '{best}' is and is "
                        f"{ratio:.0%} similar - this looks like a typo."
                    ),
                )
            )
        return fixes

    @staticmethod
    def _add_import(ctx: Context, module: str, used_line: int) -> Fix:
        body = ctx.tree.body
        line, has_imports = 1, False
        idx = 0
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            line, idx = body[0].end_lineno + 1, 1
        last_import_end: Optional[int] = None
        for stmt in body[idx:]:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                last_import_end = stmt.end_lineno
            else:
                break
        if last_import_end is not None:
            line, has_imports = last_import_end + 1, True
        elif line == 1 and ctx.line_text(1).startswith("#!"):
            line = 2

        text = f"import {module}\n"
        if line > len(ctx.sm.lines) and ctx.sm.lines and not ctx.sm.lines[-1].endswith(("\n", "\r")):
            text = "\n" + text
        elif not has_imports and ctx.line_text(line).strip():
            text += "\n"
        return Fix(
            rule=UndefinedNameFixer.rule,
            description=f"Add missing 'import {module}'",
            line=used_line,
            edits=[TextEdit(line, 0, line, 0, text)],
            confidence=0.9,
            reason=f"'{module}' is used as a module but never imported; it is part of the standard library.",
        )


class UnusedVariableFixer(Fixer):
    """Remove local variables that are assigned but never read."""

    rule = "unused-variable"

    def propose(self, ctx: Context) -> list[Fix]:
        assigns = [n for n in ast.walk(ctx.tree) if isinstance(n, ast.Assign)]
        fixes: list[Fix] = []
        for issue in ctx.issues:
            if issue.rule != self.rule:
                continue
            name = issue.details.get("name")
            stmt = next(
                (
                    a
                    for a in assigns
                    if a.lineno == issue.line
                    and len(a.targets) == 1
                    and isinstance(a.targets[0], ast.Name)
                    and a.targets[0].id == name
                ),
                None,
            )
            if stmt is None:
                continue
            if is_pure(stmt.value):
                edit = ctx.remove_statement_edit(stmt)
                if edit:
                    fixes.append(
                        Fix(
                            rule=self.rule,
                            description=f"Remove unused variable '{name}'",
                            line=issue.line,
                            edits=[edit],
                            confidence=0.95,
                            reason=(
                                f"'{name}' is assigned but never read, and its value has no side "
                                "effects, so deleting it cannot change behaviour."
                            ),
                        )
                    )
            else:
                between = ctx.sm.source[
                    ctx.sm.offset(stmt.lineno, stmt.col_offset) : ctx.sm.offset(
                        stmt.value.lineno, stmt.value.col_offset
                    )
                ]
                if between.replace(" ", "") == f"{name}=" and stmt.lineno == stmt.value.lineno:
                    fixes.append(
                        Fix(
                            rule=self.rule,
                            description=f"Drop the unused assignment to '{name}' but keep the expression",
                            line=issue.line,
                            edits=[TextEdit(stmt.lineno, stmt.col_offset, stmt.value.lineno, stmt.value.col_offset, "")],
                            confidence=0.85,
                            reason=(
                                f"'{name}' is never read, but the right-hand side may have side "
                                "effects (a function call), so only the assignment is removed."
                            ),
                        )
                    )
        return fixes


class UnusedImportFixer(Fixer):
    """Remove imports that are never used."""

    rule = "unused-import"

    @staticmethod
    def _alias_id(node: ast.AST, alias: ast.alias) -> str:
        """Rebuild the identifier pyflakes prints for this alias."""
        if isinstance(node, ast.Import):
            full = alias.name
        else:
            prefix = "." * node.level + (node.module or "")
            full = prefix + alias.name if prefix.endswith(".") else f"{prefix}.{alias.name}"
        if alias.asname and alias.asname != alias.name:
            full += f" as {alias.asname}"
        return full

    @staticmethod
    def _fmt(alias: ast.alias) -> str:
        return alias.name + (f" as {alias.asname}" if alias.asname else "")

    def propose(self, ctx: Context) -> list[Fix]:
        imports = [n for n in ast.walk(ctx.tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        fixes: list[Fix] = []
        for issue in ctx.issues:
            if issue.rule != self.rule:
                continue
            ident = issue.details.get("name")
            node = next((n for n in imports if n.lineno == issue.line), None)
            if node is None:
                continue
            alias = next((a for a in node.names if self._alias_id(node, a) == ident), None)
            if alias is None:
                continue

            if len(node.names) == 1:
                edit = ctx.remove_statement_edit(node)
            elif node.lineno == node.end_lineno and ctx.owns_lines(node):
                remaining = ", ".join(self._fmt(a) for a in node.names if a is not alias)
                if isinstance(node, ast.Import):
                    new = f"import {remaining}"
                else:
                    module = "." * node.level + (node.module or "")
                    new = f"from {module} import {remaining}"
                edit = node_edit(node, new)
            else:
                edit = None
            if edit:
                fixes.append(
                    Fix(
                        rule=self.rule,
                        description=f"Remove unused import '{ident}'",
                        line=issue.line,
                        edits=[edit],
                        confidence=0.9,
                        reason=(
                            "The imported name is never used. (Keep it if this file intentionally "
                            "re-exports it, e.g. an __init__.py - run with --ignore unused-import.)"
                        ),
                    )
                )
        return fixes


class MutableDefaultFixer(Fixer):
    """Rewrite ``def f(x=[])`` to the safe ``None`` sentinel pattern."""

    rule = "mutable-default"

    def propose(self, ctx: Context) -> list[Fix]:
        fixes: list[Fix] = []
        for func in ast.walk(ctx.tree):
            if not isinstance(func, FUNC_TYPES):
                continue
            bad = mutable_defaults(func)
            if not bad:
                continue

            body = func.body
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                if len(body) == 1:
                    continue
                first = body[1]
            if not ctx.starts_line(first):
                continue  # one-line function body; not handled

            sources = [ctx.text(d) for _, d in bad]
            if any(s is None or "\n" in s for s in sources):
                continue

            insert_line = min([first.lineno] + [d.lineno for d in getattr(first, "decorator_list", [])])
            indent = ctx.indent_of(first.lineno)
            inner = indent + ctx.indent_unit(indent)
            guards = "".join(
                f"{indent}if {arg.arg} is None:\n{inner}{arg.arg} = {src}\n"
                for (arg, _), src in zip(bad, sources)
            )
            edits = [node_edit(d, "None") for _, d in bad]
            edits.append(TextEdit(insert_line, 0, insert_line, 0, guards))
            names = ", ".join(f"'{a.arg}'" for a, _ in bad)
            fixes.append(
                Fix(
                    rule=self.rule,
                    description=f"Use None instead of a mutable default for {names} in {func.name}()",
                    line=func.lineno,
                    edits=edits,
                    confidence=0.97,
                    reason=(
                        "Default values are created once, when the function is defined, so a "
                        "list/dict/set default is shared between every call. The value is now "
                        "created fresh inside the function."
                    ),
                )
            )
        return fixes


class BareExceptFixer(Fixer):
    """Catch ordinary exceptions without swallowing process-control exceptions."""

    rule = "bare-except"

    def propose(self, ctx: Context) -> list[Fix]:
        nodes = list(ast.walk(ctx.tree))
        for node in nodes:
            if (
                isinstance(node, ast.Name) and node.id == "Exception" and isinstance(node.ctx, (ast.Store, ast.Del))
                or isinstance(node, ast.arg) and node.arg == "Exception"
                or isinstance(node, (*FUNC_TYPES, ast.ClassDef)) and node.name == "Exception"
                or isinstance(node, ast.ExceptHandler) and node.name == "Exception"
                or isinstance(node, (ast.Import, ast.ImportFrom))
                and any((a.asname or a.name.split(".")[0]) == "Exception" or a.name == "*" for a in node.names)
            ):
                return []
        return [
            Fix(
                rule=self.rule,
                description="Replace bare except with except Exception",
                line=node.lineno,
                edits=[TextEdit(node.lineno, node.col_offset + 6, node.lineno, node.col_offset + 6, " Exception")],
                confidence=0.85,
                reason=(
                    "Bare except catches every BaseException, including KeyboardInterrupt and SystemExit. "
                    "Exception catches ordinary errors while letting interruption and exit propagate. "
                    "Review handlers that intentionally catch process-control exceptions."
                ),
            )
            for node in nodes if isinstance(node, ast.ExceptHandler) and node.type is None
        ]


class IsLiteralFixer(Fixer):
    """Replace ``x is "text"`` / ``x is 5`` with ``==`` (identity is not equality)."""

    rule = "is-literal"

    def propose(self, ctx: Context) -> list[Fix]:
        fixes: list[Fix] = []
        for issue in ctx.issues:
            if issue.rule != self.rule:
                continue
            node = next(
                (
                    n
                    for n in ast.walk(ctx.tree)
                    if isinstance(n, ast.Compare)
                    and n.lineno == issue.line
                    and n.col_offset == issue.col
                    and len(n.ops) == 1
                    and isinstance(n.ops[0], (ast.Is, ast.IsNot))
                ),
                None,
            )
            if node is None:
                continue
            left, right = node.left, node.comparators[0]
            start = ctx.sm.offset(left.end_lineno, left.end_col_offset)
            end = ctx.sm.offset(right.lineno, right.col_offset)
            segment = ctx.sm.source[start:end]
            negated = isinstance(node.ops[0], ast.IsNot)
            new = re.sub(r"\bis\s+not\b", "!=", segment, count=1) if negated else re.sub(r"\bis\b", "==", segment, count=1)
            if new == segment:
                continue
            fixes.append(
                Fix(
                    rule=self.rule,
                    description="Use '!=' instead of 'is not'" if negated else "Use '==' instead of 'is'",
                    line=issue.line,
                    edits=[TextEdit(left.end_lineno, left.end_col_offset, right.lineno, right.col_offset, new)],
                    confidence=0.95,
                    reason=(
                        "'is' tests object identity, not value. Comparing to a literal only works by "
                        "accident of CPython's caching; '==' compares values, which is what was meant."
                    ),
                )
            )
        return fixes
