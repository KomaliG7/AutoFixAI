from pathlib import Path

import pytest

from autofixai import repair

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def fix(src, **kw):
    return repair(src, **kw)


# ---------- the original prototype scenario -------------------------------
def test_original_sample_is_fully_repaired():
    src = (SAMPLES / "buggy_code.py").read_text()
    report = fix(src)
    assert report.success and report.changed
    assert report.final_run.stdout.strip() == "2.5"
    assert "calculate(5, 2)" in report.fixed
    assert "unused" not in report.fixed
    assert "if b == 0:" in report.fixed


# ---------- precision: never touch things that are not the bug ------------
def test_rename_does_not_touch_strings_or_comments():
    src = 'def calculate():\n    return 1\n\n# calculte is a typo\nprint("calculte")\nprint(calculte())\n'
    report = fix(src, execute=False)
    assert 'print("calculte")' in report.fixed
    assert "# calculte is a typo" in report.fixed
    assert "print(calculate())" in report.fixed


def test_no_false_positive_on_valid_code():
    src = "import math\n\n\ndef area(r):\n    return math.pi * r ** 2\n\n\nprint(area(2))\n"
    report = fix(src)
    assert not report.changed and report.success


def test_fixing_is_idempotent():
    src = (SAMPLES / "typo_and_division.py").read_text()
    once = fix(src)
    twice = fix(once.fixed)
    assert not twice.changed and twice.success


# ---------- individual rules ----------------------------------------------
def test_missing_stdlib_import_added_after_docstring():
    src = '"""Doc."""\n\n\ndef f():\n    return os.getcwd()\n'
    report = fix(src, execute=False)
    assert report.fixed.startswith('"""Doc."""\nimport os')


def test_unused_import_partial_removal():
    src = "import os, sys\n\nprint(sys.argv)\n"
    report = fix(src, execute=False)
    assert report.fixed.startswith("import sys")


def test_unused_variable_keeps_side_effects():
    src = "def f():\n    x = print('hello')\n\nf()\n"
    report = fix(src, execute=False)
    assert "print('hello')" in report.fixed and "x =" not in report.fixed


def test_unused_variable_only_statement_becomes_pass():
    src = "def f():\n    x = 1\n\nf()\n"
    report = fix(src, execute=False)
    assert "pass" in report.fixed
    compile(report.fixed, "<t>", "exec")


def test_mutable_default_fixed_and_behaviour_correct():
    src = "def add(i, b=[]):\n    b.append(i)\n    return b\n\nprint(add(1))\nprint(add(2))\n"
    report = fix(src)
    assert report.final_run.stdout.split() == ["[1]", "[2]"]  # was [1] then [1, 2]


def test_mutable_default_multiple_args_and_docstring():
    src = 'def f(a, x=[], y={}):\n    """doc"""\n    return a\n'
    report = fix(src, execute=False)
    assert "x=None, y=None" in report.fixed
    assert report.fixed.count("is None") == 2
    compile(report.fixed, "<t>", "exec")


def test_division_by_named_zero_gets_guard():
    src = "def ratio(a, b):\n    return a / b\n\nprint(ratio(1, 0))\n"
    report = fix(src)
    assert report.success and report.final_run.stdout.strip() == "None"


# ---------- safety / control ----------------------------------------------
def test_ignore_rule_is_respected():
    src = "import os\n\nprint(1)\n"
    report = fix(src, execute=False, ignore={"unused-import"})
    assert not report.changed

def test_select_runs_only_chosen_rule():
    src = "import os\n\ndef f(x=[]):\n    return x\n"
    report = fix(src, execute=False, select={"unused-import"})
    assert {f.rule for f in report.fixes} == {"unused-import"}

def test_ignore_wins_over_select():
    src = "import os\n\nprint(1)\n"
    report = fix(src, execute=False, select={"unused-import"}, ignore={"unused-import"})
    assert not report.changed

def test_syntax_error_is_reported_not_crashed():
    report = fix("def broken(:\n    pass\n")
    assert not report.success and not report.changed
    assert any("syntax" in u.lower() or "invalid" in u.lower() for u in report.unresolved)


def test_infinite_loop_is_contained():
    report = fix("while True:\n    pass\n", timeout=1.0)
    assert not report.success


def test_static_mode_never_executes_code(tmp_path):
    marker = tmp_path / "ran.txt"
    src = f"open({str(marker)!r}, 'w').write('x')\n"
    fix(src, execute=False)
    assert not marker.exists()


@pytest.mark.parametrize("name", ["buggy_code", "mutable_default", "missing_import", "typo_and_division"])
def test_all_samples_end_up_passing(name):
    report = fix((SAMPLES / f"{name}.py").read_text())
    assert report.success


def test_empty_fixer_list_means_no_repairs():
    # Regression: `fixers or default_fixers()` used to treat [] as "use defaults".
    report = repair("import os\nprint(1)\n", fixers=[])
    assert not report.changed
