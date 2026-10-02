"""Command-line interface: ``autofix path/to/file.py``."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

from . import __version__
from .engine import repair
from .report import format_json, format_text
from .testdriven import repair_with_tests


def split_command(command: str, posix: bool | None = None) -> list[str]:
    """Split a --test-cmd string into arguments (Windows-safe).

    On Windows ``shlex`` keeps the quote characters inside each token, which then break
    ``subprocess``; strip one layer of surrounding quotes so ``"C:\\Program Files\\python.exe" t.py`` works.
    """
    posix = (os.name == "posix") if posix is None else posix
    parts = shlex.split(command, posix=posix)
    if not posix:
        parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
    return parts


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autofix",
        description="Detect, repair, validate and explain common Python bugs.",
    )
    p.add_argument("file", help="Python file to analyse and repair")
    p.add_argument("--check", action="store_true", help="don't write changes; exit 3 if changes would be made, 0 if clean")
    p.add_argument("--write", action="store_true", help="overwrite the file with the fixed code (a .orig backup is kept)")
    p.add_argument("-o", "--output", help="write the fixed code to this path instead")
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    p.add_argument("--no-diff", action="store_true", help="do not print the unified diff")
    p.add_argument("--no-run", action="store_true", help="static analysis only; never execute the code")
    p.add_argument("--timeout", type=float, default=5.0, help="seconds allowed per sandboxed run (default 5)")
    p.add_argument("--max-rounds", type=int, default=6, help="maximum repair iterations (default 6)")
    p.add_argument("--ignore", action="append", default=[], metavar="RULE", help="rule to skip (repeatable)")
    p.add_argument("--test-cmd", metavar="CMD", help="test command that must pass (e.g. \"pytest -q\"); enables test-driven mutation repair. "
                   "Runs in the file's directory and temporarily overwrites the file with candidates.")
    p.add_argument("--search-budget", type=int, default=500, help="max candidate patches to try with --test-cmd (default 500)")
    p.add_argument("--search-time", type=float, default=120.0, help="seconds allowed for the --test-cmd search (default 120)")
    p.add_argument("--version", action="version", version=f"autofixai {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    path = Path(args.file)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"autofix: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    report = repair(
        source,
        execute=not args.no_run,
        timeout=args.timeout,
        max_rounds=args.max_rounds,
        ignore=args.ignore,
    )

    if args.test_cmd:
        command = split_command(args.test_cmd)
        patched, fix, result, already = repair_with_tests(
            report.fixed, path.resolve(), command,
            max_candidates=args.search_budget, time_limit=args.search_time,
        )
        if fix is not None and patched is not None:
            report.fixed = patched
            report.fixes.append(fix)
        elif not already:
            tried = result.tried if result else 0
            report.unresolved.append(f"tests: still failing; no single-edit patch found after {tried} candidates")

    print(format_json(report) if args.json else format_text(report, path.name, show_diff=not args.no_diff))

    if not args.check and report.changed:
        if args.write:
            backup = path.with_name(path.name + ".orig")
            backup.write_text(source, encoding="utf-8")
            path.write_text(report.fixed, encoding="utf-8")
            print(f"\nWrote fixed code to {path} (original saved as {backup.name})", file=sys.stderr)
        elif args.output:
            Path(args.output).write_text(report.fixed, encoding="utf-8")
            print(f"\nWrote fixed code to {args.output}", file=sys.stderr)

    if args.check:
        if report.changed:
            return 3
        return 0 if report.success else 1

    return 0 if report.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
