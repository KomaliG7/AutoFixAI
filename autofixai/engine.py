"""The repair loop: detect -> propose -> apply -> re-run -> repeat.

Each round works on the *current* code, so fixes can unlock each other (for
example, renaming a typo'd function lets the program run far enough to reveal a
ZeroDivisionError further down).  The loop stops when the code is clean, when no
fixer has anything to propose, or after ``max_rounds``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from typing import Optional

from .analysis import analyze
from .edits import OverlapError, apply_edits, select_non_overlapping
from .fixers import Context, Fixer, default_fixers
from .models import ExecutionResult, Fix, Report
from .sandbox import run_code


def _parses(source: str) -> bool:
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


def _apply_safely(source: str, fixes: list[Fix]) -> tuple[str, list[Fix]]:
    """Apply fixes, dropping any that would leave syntactically invalid code."""
    viable: list[Fix] = []
    for fix in fixes:
        try:
            if _parses(apply_edits(source, fix.edits)):
                viable.append(fix)
        except OverlapError:
            continue
    if not viable:
        return source, []
    try:
        merged = apply_edits(source, [e for f in viable for e in f.edits])
    except OverlapError:
        return source, []
    if not _parses(merged):
        return source, []
    return merged, viable


def repair(
    source: str,
    *,
    execute: bool = True,
    timeout: float = 5.0,
    max_rounds: int = 6,
    ignore: Iterable[str] = (),
    select: Optional[Iterable[str]] = None,
    fixers: Optional[list[Fixer]] = None,
) -> Report:
    """Detect and repair bugs in ``source``.

    Args:
        execute: run the code in the sandbox to catch runtime errors and to
            verify every round of fixes.  Set to False for static-only mode.
        timeout: seconds allowed for each sandboxed run.
        max_rounds: safety cap on repair iterations.
        ignore: rule names to leave alone (e.g. ``{"unused-import"}``).
                select: if given, only these rules run; ``ignore`` still wins.
    """
    ignored = set(ignore)
    selected = set(select) if select is not None else None

    def wanted(rule: str) -> bool:
        return rule not in ignored and (selected is None or rule in selected)

    active = [f for f in (fixers if fixers is not None else default_fixers()) if wanted(f.rule)]

    initial_issues = [i for i in analyze(source) if wanted(i.rule)]
    initial_run = run_code(source, timeout) if execute else None
    last_run: Optional[ExecutionResult] = initial_run

    current = source
    applied: list[Fix] = []
    seen = {source}
    rounds = 0

    for _ in range(max_rounds):
        issues = [i for i in analyze(current) if wanted(i.rule)]
        ctx = Context.build(current, issues, last_run)
        if ctx is None:  # syntax error: nothing safe we can do yet
            break

        proposals: list[Fix] = []
        for fixer in active:
            if fixer.stage == "runtime" and (last_run is None or last_run.passed):
                continue
            proposals.extend(fixer.propose(ctx))
        if not proposals:
            break

        proposals.sort(key=lambda f: (-f.confidence, f.line))
        accepted, _deferred = select_non_overlapping(current, proposals)
        updated, done = _apply_safely(current, accepted)
        if updated == current or updated in seen:
            break
        seen.add(updated)
        applied.extend(sorted(done, key=lambda f: f.line))
        current = updated
        rounds += 1
        last_run = run_code(current, timeout) if execute else None

    remaining = [i for i in analyze(current) if wanted(i.rule)]
    unresolved = [f"line {i.line}: {i.message}" for i in remaining if i.severity == "error"]
    if last_run is not None and not last_run.passed:
        unresolved.append(f"runtime: {last_run.summary()}")

    return Report(
        original=source,
        fixed=current,
        issues=initial_issues,
        remaining_issues=remaining,
        fixes=applied,
        initial_run=initial_run,
        final_run=last_run,
        rounds=rounds,
        unresolved=unresolved,
    )
