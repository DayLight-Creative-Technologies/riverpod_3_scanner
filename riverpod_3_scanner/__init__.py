"""
Riverpod 3.0 Safety Scanner
Comprehensive static analysis tool for Flutter/Dart projects using Riverpod 3.0+

Author: Steven Day
Company: DayLight Creative Technologies
License: MIT
"""

from .models import ViolationType, Violation, Severity, VIOLATION_SEVERITY
from .scanner import RiverpodScanner

__version__ = "1.4.0"
__author__ = "Steven Day"
__email__ = "support@daylightcreative.tech"
__license__ = "MIT"

__all__ = [
    "RiverpodScanner",
    "ViolationType",
    "Violation",
    "Severity",
    "VIOLATION_SEVERITY",
    "__version__",
]
