"""Output formatting module for the Riverpod 3.0 Safety Scanner.

Provides text and JSON output formats for scanner results.
Text format is identical to the original scanner output for backward compatibility.
JSON format is designed for CI/CD integration and IDE tooling.

Author: Steven Day
Company: DayLight Creative Technologies
License: MIT
"""

import json
import sys
from typing import Dict, List

from .models import Violation, ViolationType, Severity, VIOLATION_SEVERITY

try:
    from . import __version__
except ImportError:
    __version__ = "unknown"


def format_violation_text(violation: Violation) -> str:
    """Format a single violation for text display.

    Produces identical output to RiverpodScanner.format_violation() for
    backward compatibility with existing CI/CD integrations and workflows.

    Args:
        violation: The Violation dataclass instance to format.

    Returns:
        Multi-line string with the formatted violation report.
    """
    output = []
    output.append(f"\n{'=' * 80}")
    output.append(f"❌ RIVERPOD 3.0 VIOLATION: {violation.violation_type.value.upper().replace('_', ' ')}")
    output.append(f"{'=' * 80}")
    output.append(f"📄 File: {violation.file_path}:{violation.line_number}")
    output.append(f"🏷️  Class: {violation.class_name}")
    output.append(f"📍 Context: {violation.context}")
    output.append(f"")
    output.append(f"Code:")
    output.append(violation.code_snippet)
    output.append(f"")
    output.append(f"✅ FIX:")
    output.append(violation.fix_instructions)
    output.append(f"")
    output.append(f"📚 Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md")

    return '\n'.join(output)


def print_summary_text(
    violations: List[Violation],
    path,
    suppressed_count: int = 0,
) -> None:
    """Print a comprehensive text summary of scan results.

    Produces identical output to RiverpodScanner.print_summary() for
    backward compatibility, with the addition of suppressed violation
    count when suppressions are present.

    Args:
        violations: List of Violation instances detected by the scanner.
        path: The path that was scanned (str or Path).
        suppressed_count: Number of violations suppressed by inline comments.
    """
    print(f"\n{'=' * 80}")
    print(f"🔍 RIVERPOD 3.0 COMPLIANCE SCAN COMPLETE")
    print(f"{'=' * 80}")
    print(f"📁 Scanned: {path}")
    print(f"🚨 Total violations: {len(violations)}")
    if suppressed_count > 0:
        print(f"🔇 Suppressed violations: {suppressed_count}")
    print(f"")

    if violations:
        # Group by type
        by_type: Dict[ViolationType, List[Violation]] = {}
        for v in violations:
            by_type.setdefault(v.violation_type, []).append(v)

        # Print summary by type
        print(f"VIOLATIONS BY TYPE:")
        print(f"{'-' * 80}")
        for vtype in ViolationType:
            count = len(by_type.get(vtype, []))
            if count > 0:
                icon = "🔴"
                print(f"{icon} {vtype.value.upper().replace('_', ' ')}: {count}")

        # Print file list
        print(f"\n{'=' * 80}")
        print(f"AFFECTED FILES:")
        print(f"{'=' * 80}")

        by_file: Dict[str, List[Violation]] = {}
        for v in violations:
            by_file.setdefault(v.file_path, []).append(v)

        for file_path, file_violations in sorted(by_file.items()):
            print(f"\n📄 {file_path} ({len(file_violations)} violation(s))")
            for v in file_violations:
                print(f"   • Line {v.line_number}: {v.violation_type.value}")

        # Print detailed violations
        print(f"\n{'=' * 80}")
        print(f"DETAILED VIOLATION REPORTS:")
        print(f"{'=' * 80}")

        for i, violation in enumerate(violations, 1):
            print(f"\n[{i}/{len(violations)}]")
            print(format_violation_text(violation))

        # Print action items
        print(f"\n{'=' * 80}")
        print(f"⚡ ACTION REQUIRED")
        print(f"{'=' * 80}")
        print(f"🚨 {len(violations)} violation(s) must be fixed")
        print(f"")
        print(f"Next steps:")
        print(f"  1. Fix each violation using Riverpod 3.0 pattern")
        print(f"  2. Run: dart analyze")
        print(f"  3. Re-run this scanner to verify: python3 riverpod_3_scanner.py lib")
        print(f"")
        print(f"📚 Documentation:")
        print(f"   https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md")
        print(f"   ")
        print(f"")

    else:
        print(f"✅ No Riverpod 3.0 violations detected!")
        print(f"✅ All code is compliant with async safety standards")
        print(f"")


def _violation_to_dict(violation: Violation) -> dict:
    """Convert a Violation dataclass to a JSON-serializable dictionary.

    Args:
        violation: The Violation instance to convert.

    Returns:
        Dictionary with all violation fields suitable for JSON serialization.
    """
    severity = VIOLATION_SEVERITY.get(
        violation.violation_type, Severity.WARNING
    )
    return {
        "file": violation.file_path,
        "line": violation.line_number,
        "class": violation.class_name,
        "type": violation.violation_type.value,
        "severity": severity.value,
        "context": violation.context,
        "code_snippet": violation.code_snippet,
        "fix": violation.fix_instructions,
    }


def format_json(
    violations: List[Violation],
    path,
    suppressed_count: int = 0,
) -> str:
    """Format scan results as JSON for CI/CD integration.

    Produces a structured JSON document suitable for consumption by
    CI pipelines, IDE extensions, and automated reporting tools.

    Args:
        violations: List of Violation instances detected by the scanner.
        path: The path that was scanned (str or Path).
        suppressed_count: Number of violations suppressed by inline comments.

    Returns:
        Pretty-printed JSON string with full scan results.
    """
    # Build summary counts by severity
    severity_counts: Dict[str, int] = {}
    for v in violations:
        sev = VIOLATION_SEVERITY.get(v.violation_type, Severity.WARNING).value
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    # Build summary counts by violation type
    type_counts: Dict[str, int] = {}
    for v in violations:
        vtype = v.violation_type.value
        type_counts[vtype] = type_counts.get(vtype, 0) + 1

    result = {
        "scanner": "riverpod-3-scanner",
        "version": __version__,
        "path": str(path),
        "violations_count": len(violations),
        "suppressed_count": suppressed_count,
        "summary": {
            "by_severity": severity_counts,
            "by_type": type_counts,
        },
        "violations": [
            _violation_to_dict(v) for v in violations
        ],
    }

    return json.dumps(result, indent=2, ensure_ascii=False)
