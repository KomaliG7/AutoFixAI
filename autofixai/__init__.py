"""AutoFixAI - automatic detection, repair, validation and explanation of Python bugs."""

from .analysis import analyze
from .engine import repair
from .models import ExecutionResult, Fix, Issue, Report, TextEdit

__version__ = "0.4.1"
__all__ = ["analyze", "repair", "Issue", "Fix", "TextEdit", "ExecutionResult", "Report", "__version__"]
