# AutoFixAI

[![CI](https://github.com/KomaliG7/AutoFixAI/actions/workflows/ci.yml/badge.svg)](https://github.com/KomaliG7/AutoFixAI/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/autofixai.svg)](https://pypi.org/project/autofixai/)
[![Python](https://img.shields.io/pypi/pyversions/autofixai.svg)](https://pypi.org/project/autofixai/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Automatically detect, repair, validate and explain common Python bugs.**

AutoFixAI reads a Python file, finds bugs, fixes them with *surgical, position-exact edits*,
re-runs the program in an isolated process to prove the fix worked, and tells you **why** each
change was made and how confident it is.

```console
$ autofix samples/buggy_code.py
Issues detected: 3
  line 2    [literal-zero-division] Division by a literal zero always raises ZeroDivisionError
  line 3    [unused-variable] local variable 'unused' is assigned to but never used
  line 6    [undefined-name] undefined name 'calculte'

Before: FAIL - NameError: name 'calculte' is not defined (line 6)

Fixes applied: 3 (in 2 rounds)
  1. line 3  [unused-variable] Remove unused variable 'unused'                (confidence 0.95)
  2. line 6  [undefined-name]  Rename 'calculte' to 'calculate'              (confidence 0.94)
  3. line 2  [zero-division]   Replace the literal divisor 0 with parameter 'b' and guard against zero (confidence 0.75)

After:  PASS - runs without errors
Result: FIXED
```

## Why it is different from a linter or a chatbot

| | Linter | Chatbot | **AutoFixAI** |
|---|---|---|---|
| Finds problems | yes | sometimes | yes |
| Fixes them | rarely | yes, unverified | yes |
| **Proves the fix by running the program** | no | no | **yes** |
| Explains *why*, with a confidence score | no | loosely | **yes** |
| Never rewrites code it did not need to touch | n/a | often does | **yes** (exact-range edits) |

## Install

```bash
git clone https://github.com/KomaliG7/AutoFixAI.git
cd AutoFixAI
pip install -e ".[dev]"
```

Requires Python 3.10+. The only runtime dependency is [`pyflakes`](https://github.com/PyCQA/pyflakes).

## Usage

```bash
autofix my_script.py                 # analyse, repair, show a report and diff
autofix my_script.py --check         # CI check: exit 3 if changes would be made, never writes files
autofix my_script.py --write         # apply the fixes (keeps my_script.py.orig)
autofix my_script.py -o fixed.py     # write the fixed code somewhere else
autofix my_script.py --json          # machine-readable report (for CI / IDE plugins)
autofix my_script.py --no-run        # static analysis only - never executes your code
autofix my_script.py --ignore unused-import
autofix calc.py --test-cmd "python check_calc.py"   # test-driven repair (see below)
```

Exit code: `0` = clean or fixed, `1` = something still needs a human, `2` = usage error, `3` = changes would be made (with `--check`).

As a library:

```python
from autofixai import repair

report = repair(open("my_script.py").read())
print(report.success, report.fixed)
for fix in report.fixes:
    print(fix.rule, fix.description, fix.confidence, fix.reason)
```

## What it fixes today

| Rule | Detects | Repair |
|---|---|---|
| `undefined-name` | typos (`calculte`) and missing stdlib imports (`os.getcwd()` with no `import os`) | rename to the closest *defined* name (call-aware) / add the import |
| `unused-variable` | local assigned but never read | delete it - or keep the expression if it has side effects |
| `unused-import` | imported but never used | remove the import (or just that alias) |
| `mutable-default` | `def f(x=[])` | `x=None` + `if x is None: x = []` |
| `literal-zero-division` / `zero-division` | `a / 0`, or a runtime `ZeroDivisionError` | use the intended parameter as divisor + zero guard |
| `index-off-by-one` | `range(len(xs) + 1)`, `while i <= len(xs)`, `xs[len(xs)]` that raise `IndexError` | shift the bound by one |
| `key-error` | `d["missing"]` that raised `KeyError` | `d.get("missing")` |
| `str-concat` | `"n=" + n` / `n + " items"` that raised `TypeError` | wrap the number in `str()` |
| `is-literal` | `x is "text"`, `n is not 5` | `==` / `!=` |

## Test-driven repair (for bugs that don't crash)

A wrong operator, an off-by-one or the wrong variable produces no traceback, so rule-based fixers
have nothing to latch onto. With `--test-cmd`, AutoFixAI uses your tests as the specification and
searches for a fix the way academic repair tools do (*generate-and-validate*):

1. **Localise** - rank lines by suspiciousness with spectrum-based fault localisation (Ochiai).
2. **Mutate** - generate small edits with generic operators: swap a comparison / arithmetic / bitwise
   operator, `and`/`or`, change a constant by one, `± 1` on an index or bound, swap call arguments,
   negate a condition, delete a statement, use a different local variable.
3. **Validate** - accept the first single edit that makes your test command pass.

```console
$ autofix calc.py --test-cmd "python check_calc.py" --write
  1. line 2  [mutation] Line 2: replace '-' with '+'  (confidence 0.50)
       why: Found by test-driven search after 3 candidates ... Tests are the only specification, so review it.
```

The command runs in the file's directory and the file is temporarily overwritten with candidates
(always restored). Only run test commands you would run yourself.

## Independent evaluation: QuixBugs

[QuixBugs](https://github.com/jkoppel/QuixBugs) has 40 classic algorithms, each with a one-line bug
and a test-suite. Full table: [benchmark/QUIXBUGS_RESULTS.md](benchmark/QUIXBUGS_RESULTS.md).

| | Programs |
|---|---:|
| Rule-based pipeline only (no `--test-cmd`) | 0 / 40 |
| Test-driven search: patch passes all tests ("plausible") | 13 / 40 |
| ... of which identical to the reference fix | 7 |
| ... of which different but equivalent on 400 held-out random inputs | 4 |
| ... of which **overfit** (pass the tests, wrong on new inputs) | 2 |
| **Correct repairs** | **11 / 40 (28%)** |

Why the held-out check matters: passing the tests is not the same as being right. Two of the 13
"successful" patches (`depth_first_search`, `find_in_sorted`) were lucky edits that break on inputs
the tests never used. Reporting *plausible* patches as *fixes* is a well-known flaw in repair papers;
this repo separates them.

Caveats, stated plainly: the operator set was designed by someone who knows QuixBugs-style bug
categories, and the argument-swap operator was added after `gcd` failed without it, so 28% is best
read as an optimistic estimate for this operator set. Only single-edit repairs are searched. Reproduce
with `python -m benchmark.run_quixbugs --root path/to/QuixBugs`.

## How it works

```
source ──► analyse (pyflakes + AST rules) ──► propose fixes ──► apply exact edits
   ▲                                                                   │
   └──────── re-run in sandbox, read the traceback  ◄───────────────────┘
                   (repeat until clean, stuck, or max rounds)
```

1. **Detect** – scope-aware static analysis, plus a real run in a sandboxed subprocess.
2. **Propose** – each `Fixer` returns `Fix` objects: exact `TextEdit`s, a reason, a confidence.
3. **Apply** – non-overlapping edits are applied by source position, never by string search, so
   strings, comments and formatting elsewhere are untouched. A fix that would produce invalid
   syntax is discarded.
4. **Validate** – the program is re-executed (timeout, isolated mode, temp dir, CPU/memory caps
   on POSIX). Fixes can unlock one another, so this loops.
5. **Explain** – every fix reports its rule, reason and confidence.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and the reasoning behind it.

## Benchmark

`python -m benchmark.run_benchmark` runs 40 buggy programs and 11 already-correct controls.
Every case has a hand-written reference solution; a repair only counts if the program runs, prints
**exactly** what the reference prints, and no static issues remain. See
[benchmark/RESULTS.md](benchmark/RESULTS.md) for the current table.

Please read the numbers with the right expectations:

* The corpus was written by the author, so it is a **regression suite**, not independent evidence.
  Scoring 100% on bug classes the tool was built for is expected. Six `UNSUP-` cases (syntax errors,
  logic bugs, `None` attributes, infinite loops, missing recursion base case) are included on purpose
  and are *not* fixed.
* The "no fixers" baseline solves 0 cases, so the harness does measure repair, not luck.
* Independent evaluation on public datasets (e.g. QuixBugs, BugsInPy) is on the roadmap and will
  produce much lower, more honest numbers.

## Honest limitations

* Not every bug can be fixed automatically; unresolved problems are reported, never hidden.
* Confidence scores are heuristic rules, not calibrated probabilities (yet - see roadmap).
* A "fix" makes the program *run*; only you know if it does what you *intended*. Review the diff.
* The sandbox limits accidents, not attackers. **Do not run AutoFixAI on untrusted code.**
  Use `--no-run` if you only want static analysis.
* Syntax errors are reported but not yet repaired.
* Test-driven repair returns *plausible* patches: the first edit that passes your tests. If your tests are weak, the patch can be wrong. Read the diff.

## Roadmap

- [ ] Syntax-error repair (missing colons, unbalanced brackets)
- [x] Runtime fixers for `IndexError`, `KeyError`, `TypeError` (string concatenation)
- [ ] More runtime fixers: `AttributeError`, `UnboundLocalError`, argument-count `TypeError`
- [x] Author-written regression benchmark with published results
- [x] Independent evaluation on QuixBugs with held-out overfitting checks
- [ ] Evaluate on BugsInPy (real-world bugs) - expect much lower numbers
- [ ] Multi-edit and statement-insertion repair (e.g. missing `visited.add(node)`)
- [ ] Coverage-based localisation inside `--test-cmd`
- [ ] Optional LLM fallback whose every patch must pass the same sandbox validation
- [ ] Calibrated confidence scores
- [ ] Pre-commit hook and VS Code extension
- [ ] Publish to PyPI

Contributions are welcome - see [CONTRIBUTING.md](CONTRIBUTING.md) and the open issues labelled
`good first issue`. If you use AutoFixAI in research, see [CITATION.cff](CITATION.cff).

## Project history

AutoFixAI began as a prototype (detect → analyse → fix → validate → explain). Version 0.2 is a
ground-up rewrite that keeps the same pipeline idea but replaces string replacement with exact
AST-position edits, in-process `exec` with a sandboxed subprocess, and hard-coded fixes with
general rules, and adds a CLI, a JSON report, and a test suite.

## License

MIT - see [LICENSE](LICENSE).

**Author:** Komali ([@KomaliG7](https://github.com/KomaliG7))
