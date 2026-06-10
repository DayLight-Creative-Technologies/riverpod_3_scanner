"""
Riverpod 3.0 Safety Scanner
Comprehensive static analysis tool for Flutter/Dart projects using Riverpod 3.0+

Author: Steven Day
Company: DayLight Creative Technologies
License: MIT
"""

# Version is the package's single source of truth — pyproject.toml reads it
# dynamically (tool.setuptools.dynamic) and setup.py is a metadata-free shim.
# It must be defined BEFORE the submodule imports below so that scanner.py
# can `from . import __version__` without a circular-import failure.
__version__ = "1.12.0"
__author__ = "Steven Day"
__email__ = "support@daylightcreative.tech"
__license__ = "MIT"

from .models import ViolationType, Violation, Severity, VIOLATION_SEVERITY
from .scanner import RiverpodScanner

__all__ = [
    "RiverpodScanner",
    "ViolationType",
    "Violation",
    "Severity",
    "VIOLATION_SEVERITY",
    "__version__",
]
