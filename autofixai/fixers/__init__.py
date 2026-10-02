from .base import Context, Fixer
from .runtime import IndexErrorFixer, KeyErrorFixer, StrConcatFixer, ZeroDivisionFixer
from .static import (
    BareExceptFixer,
    IsLiteralFixer,
    MutableDefaultFixer,
    UndefinedNameFixer,
    UnusedImportFixer,
    UnusedVariableFixer,
)


def default_fixers() -> list[Fixer]:
    return [
        UndefinedNameFixer(),
        UnusedImportFixer(),
        UnusedVariableFixer(),
        MutableDefaultFixer(),
        IsLiteralFixer(),
        BareExceptFixer(),
        ZeroDivisionFixer(),
        IndexErrorFixer(),
        KeyErrorFixer(),
        StrConcatFixer(),
    ]


__all__ = ["Context", "Fixer", "default_fixers"]
