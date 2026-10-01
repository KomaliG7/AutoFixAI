import json

from autofixai.cli import main, split_command


def test_cli_prints_report_and_returns_zero(tmp_path, capsys):
    f = tmp_path / "bug.py"
    f.write_text("def f(a, b):\n    return a / 0\n\nprint(f(4, 2))\n")
    code = main([str(f)])
    out = capsys.readouterr().out
    assert code == 0 and "Result: FIXED" in out


def test_cli_write_keeps_backup(tmp_path):
    f = tmp_path / "bug.py"
    original = "import os\nprint(1)\n"
    f.write_text(original)
    assert main([str(f), "--write"]) == 0
    assert f.read_text() == "print(1)\n"
    assert (tmp_path / "bug.py.orig").read_text() == original


def test_cli_json_output_is_valid(tmp_path, capsys):
    f = tmp_path / "bug.py"
    f.write_text("import os\nprint(1)\n")
    main([str(f), "--json", "--no-run"])
    data = json.loads(capsys.readouterr().out)
    assert data["changed"] is True and data["fixes"][0]["rule"] == "unused-import"


def test_cli_check_mode_exits_3_when_changes_would_be_made_and_never_writes(tmp_path):
    f = tmp_path / "bug.py"
    original = "import os\nprint(1)\n"
    f.write_text(original)
    code = main([str(f), "--check", "--no-run"])
    assert code == 3
    assert f.read_text() == original
    assert not (tmp_path / "bug.py.orig").exists()


def test_cli_check_mode_exits_0_when_clean(tmp_path):
    f = tmp_path / "clean.py"
    clean_code = "print(1)\n"
    f.write_text(clean_code)
    code = main([str(f), "--check", "--no-run"])
    assert code == 0
    assert f.read_text() == clean_code


def test_cli_check_mode_works_with_json(tmp_path, capsys):
    f = tmp_path / "bug.py"
    f.write_text("import os\nprint(1)\n")
    code = main([str(f), "--check", "--json", "--no-run"])
    assert code == 3
    data = json.loads(capsys.readouterr().out)
    assert data["changed"] is True
    assert data["fixes"][0]["rule"] == "unused-import"


def test_cli_check_mode_with_write_flag_still_does_not_write(tmp_path):
    f = tmp_path / "bug.py"
    original = "import os\nprint(1)\n"
    f.write_text(original)
    code = main([str(f), "--check", "--write", "--no-run"])
    assert code == 3
    assert f.read_text() == original
    assert not (tmp_path / "bug.py.orig").exists()


def test_cli_missing_file_returns_2(tmp_path):
    assert main([str(tmp_path / "nope.py")]) == 2


def test_cli_unfixable_returns_1(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def broken(:\n")
    assert main([str(f)]) == 1


def test_cli_test_driven_repair_finds_logic_bug(tmp_path, capsys):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / "check.py").write_text(
        "from calc import add\nassert add(2, 3) == 5\nassert add(0, 0) == 0\nassert add(-1, 1) == 0\n"
    )
    code = main([str(tmp_path / "calc.py"), "--no-run", "--test-cmd", f'"{__import__("sys").executable}" check.py', "--write"])
    assert code == 0
    assert "a + b" in (tmp_path / "calc.py").read_text()
    assert "[mutation]" in capsys.readouterr().out


def test_cli_test_driven_failure_is_reported_and_file_restored(tmp_path):
    original = "def f(a):\n    return a\n"
    (tmp_path / "m.py").write_text(original)
    (tmp_path / "check.py").write_text("from m import f\nassert f(1) == 12345\n")
    code = main([str(tmp_path / "m.py"), "--no-run", "--search-budget", "30",
                 "--test-cmd", f'"{__import__("sys").executable}" check.py'])
    assert code == 1
    assert (tmp_path / "m.py").read_text() == original


def test_split_command_handles_windows_style_quotes():
    # posix=False reproduces how Windows tokenises; quotes around a path with spaces must be removed.
    parts = split_command('"C:\\Program Files\\Python\\python.exe" check.py -q', posix=False)
    assert parts == ["C:\\Program Files\\Python\\python.exe", "check.py", "-q"]


def test_split_command_posix():
    assert split_command("pytest -q 'a b.py'", posix=True) == ["pytest", "-q", "a b.py"]
