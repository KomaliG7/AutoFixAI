# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/).

## [0.4.1] - 2026-10-02
### Fixed
- PyPI metadata: declare supported Python versions (3.10-3.13) and OS independence so the badges are accurate.

## [0.4.0] - 2026-10-01
### Added
- **Test-driven repair** (`--test-cmd`): Ochiai fault localisation + generic mutation operators
  (operator swaps, constants, `+/- 1`, argument swaps, negation, statement deletion, variable swaps).
- QuixBugs evaluation harness with held-out differential testing to detect overfitting patches.
- Release tooling: CI on Linux/Windows/macOS, lint, PyPI trusted-publishing workflow, issue/PR templates.

### Fixed
- Plain `pytest` (not `python -m pytest`) could not import the `benchmark` package; added `pythonpath` to the pytest config.
- `--test-cmd` quoting on Windows: quoted paths containing spaces are now split correctly.
- Passing an empty fixer list silently re-enabled all default fixers.
- Stale `.pyc` reuse could make a correct candidate patch look failing during search.

## [0.3.0]
### Added
- Fixers: `IndexError` off-by-one, `KeyError` (`.get`), string/number `TypeError`, `is` with literals.
- Author-written regression benchmark (40 buggy programs, 11 correct controls).

## [0.2.0]
### Changed
- Ground-up rewrite of the prototype: exact-range AST edits instead of `str.replace`, sandboxed subprocess
  instead of in-process `exec`, scope-aware analysis via pyflakes, CLI, JSON report, test suite.

## [0.1.0] - prototype
- Original detect -> analyse -> fix -> validate -> explain pipeline.
