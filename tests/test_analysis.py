from autofixai.analysis import analyze


def rules(src):
    return {(i.rule, i.line) for i in analyze(src)}


def test_builtins_are_not_flagged():
    assert analyze("print(len([1, 2]))\n") == []


def test_undefined_name_and_unused_variable():
    src = "def f():\n    x = 1\n\nf2()\n"
    assert ("undefined-name", 4) in rules(src)
    assert ("unused-variable", 2) in rules(src)


def test_unused_import():
    assert ("unused-import", 1) in rules("import os\n")


def test_mutable_default_and_literal_zero_division():
    src = "def f(a, b=[]):\n    return a / 0\n"
    found = rules(src)
    assert ("mutable-default", 1) in found
    assert ("literal-zero-division", 2) in found


def test_syntax_error_becomes_issue():
    issues = analyze("def broken(:\n")
    assert len(issues) == 1 and issues[0].rule == "syntax-error"


def test_bare_except_is_reported_but_typed_handlers_are_not():
    src = "try:\n    print(1)\nexcept ValueError:\n    pass\nexcept:\n    pass\n"
    assert rules(src) == {("bare-except", 5)}
