#!/usr/bin/env python3
"""
Riverpod 3.0 Safety Scanner
Comprehensive static analysis tool for Flutter/Dart projects using Riverpod 3.0+

Author: Steven Day
Company: DayLight Creative Technologies
License: MIT
Version: 1.5.0

Detects ALL forbidden patterns that violate Riverpod 3.0 async safety standards.

SCANS THREE CLASS TYPES:
- Riverpod provider classes (extends _$ClassName)
- ConsumerStatefulWidget State classes (extends ConsumerState<T>)
- ConsumerWidget classes (extends ConsumerWidget)

FORBIDDEN PATTERNS DETECTED (16 TYPES):

CRITICAL (Will crash in production):
1. Field caching (nullable/dynamic fields with getters in async classes)
2. Lazy getters (get x => ref.read()) in async classes
3. Async getters with field caching
4. ref operation (read/watch/listen) before ref.mounted check
5. Missing ref.mounted after await
6. Missing ref.mounted in catch blocks
7. Nullable field direct access (_field?.method()) when getter exists
8. ref operations inside lifecycle callbacks (ref.onDispose, ref.listen)
9. initState field access before caching (accessing cached fields before build() caches them)
10. Sync methods with ref.read() but no mounted check (called from async context)
11. Ref stored as field in plain Dart class (not Riverpod notifier/widget)

WARNINGS (High risk of crashes):
11. Widget lifecycle methods with unsafe ref (didUpdateWidget, deactivate, reassemble)
12. Timer/Future.delayed deferred callbacks without mounted checks
13. Async event handler callbacks without mounted checks (onTap, onPressed, etc.)

DEFENSIVE (Type safety & best practices):
14. Untyped var lazy getters (loses type information)
15. mounted vs ref.mounted confusion (educational - different lifecycles)

SPECIAL FEATURES:
- Type inference for dynamic fields (suggests proper types)
- Cross-file indirect violation detection
- Inline suppression comments (// riverpod_scanner:ignore)
- JSON output format for CI/CD integration (--format json)
- File caching for performance (each file read once)
- String-aware brace counting (correct handling of string literals)

CORRECT PATTERN (Riverpod 3.0):
  Future<void> myMethod() async {
    if (!ref.mounted) return;  // For Riverpod providers
    if (!mounted) return;      // For ConsumerStatefulWidget (widget check)
    final logger = ref.read(myLoggerProvider);
    await operation();
    if (!mounted) return;      // After await
    logger.logInfo('Done');
  }

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .models import Violation, ViolationType
from .utils import (
    FileCache,
    find_matching_brace,
    find_async_methods,
    is_line_suppressed,
    is_file_suppressed,
    RE_PROVIDER_CLASS,
    RE_CONSUMER_STATE_CLASS,
    RE_CONSUMER_WIDGET_CLASS,
)
from .analysis import AnalysisContext, run_all_passes
from .checkers import (
    CheckContext,
    check_field_caching,
    check_async_method_safety,
    check_sync_methods_without_mounted,
    check_nullable_field_misuse,
    check_ref_in_lifecycle_callbacks,
    check_ref_operations_outside_build,
    check_widget_lifecycle_unsafe_ref,
    check_deferred_callbacks,
    check_async_event_handlers,
    check_untyped_lazy_getters,
    check_mounted_confusion,
    check_initstate_field_access,
    check_ref_stored_as_field,
)
from .output import format_violation_text, print_summary_text, format_json


class RiverpodScanner:
    """Main scanner orchestrator.

    Coordinates the multi-pass analysis pipeline and per-file violation
    detection.  Maintains backward compatibility with the v1.3.x public API.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.file_cache = FileCache()

        # Cross-file analysis state (populated by run_all_passes)
        self._ctx: Optional[AnalysisContext] = None

    # ------------------------------------------------------------------
    # Public API (backward compatible)
    # ------------------------------------------------------------------

    def scan_file(self, file_path: Path) -> List[Violation]:
        """Scan a single Dart file for all Riverpod violations.

        When called standalone (without scan_directory), cross-file context
        is unavailable so only single-file checks run.
        """
        content = self.file_cache.read_text(file_path)
        if content is None:
            return []

        lines = content.split('\n')

        # Check file-level suppression
        if is_file_suppressed(content):
            return []

        violations: List[Violation] = []

        # --- Riverpod provider classes (extends _$ClassName) ---
        for match in RE_PROVIDER_CLASS.finditer(content):
            class_name = match.group(1)
            class_start = match.start()
            brace_pos = content.find('{', match.end())
            if brace_pos == -1:
                continue
            class_end = find_matching_brace(content, brace_pos + 1)
            class_content = content[class_start:class_end + 1]

            async_methods = find_async_methods(class_content)
            has_async = len(async_methods) > 0

            if self.verbose:
                print(f"\n\U0001f50d Analyzing {class_name} (Riverpod Provider):")
                print(f"   Async methods: {len(async_methods)}")
                if async_methods:
                    print(f"   Methods: {', '.join(async_methods)}")

            ctx = CheckContext(
                file_path=file_path,
                class_name=class_name,
                class_content=class_content,
                full_content=content,
                class_start=class_start,
                lines=lines,
                has_async_methods=has_async,
                async_methods=async_methods,
                is_consumer_state=False,
                analysis=self._ctx,
            )

            violations.extend(check_field_caching(ctx))
            if has_async:
                violations.extend(check_async_method_safety(ctx))
            violations.extend(check_sync_methods_without_mounted(ctx))
            violations.extend(check_nullable_field_misuse(ctx))
            violations.extend(check_ref_in_lifecycle_callbacks(ctx))
            violations.extend(check_ref_operations_outside_build(ctx))
            violations.extend(check_mounted_confusion(ctx))
            # Off-frame async (Future.microtask, scheduleMicrotask) applies
            # to notifier classes too — `ref` inside such a callback is
            # unsafe without a `ref.mounted` entry guard. Scope restricts
            # to the two micro-task specs whose detection logic cannot
            # false-positive on captured-parameter patterns common in
            # service-class notifiers.
            violations.extend(check_deferred_callbacks(ctx, notifier_scope=True))

        # --- ConsumerStatefulWidget State classes (extends ConsumerState<T>) ---
        for match in RE_CONSUMER_STATE_CLASS.finditer(content):
            class_name = match.group(1)
            class_start = match.start()
            brace_pos = content.find('{', match.end())
            if brace_pos == -1:
                continue
            class_end = find_matching_brace(content, brace_pos + 1)
            class_content = content[class_start:class_end + 1]

            async_methods = find_async_methods(class_content)
            has_async = len(async_methods) > 0

            if self.verbose:
                widget_name = match.group(2)
                print(f"\n\U0001f50d Analyzing {class_name} (ConsumerState<{widget_name}>):")
                print(f"   Async methods: {len(async_methods)}")
                if async_methods:
                    print(f"   Methods: {', '.join(async_methods)}")

            ctx = CheckContext(
                file_path=file_path,
                class_name=class_name,
                class_content=class_content,
                full_content=content,
                class_start=class_start,
                lines=lines,
                has_async_methods=has_async,
                async_methods=async_methods,
                is_consumer_state=True,
                analysis=self._ctx,
            )

            violations.extend(check_field_caching(ctx))
            if has_async:
                violations.extend(check_async_method_safety(ctx))
            violations.extend(check_sync_methods_without_mounted(ctx))
            violations.extend(check_nullable_field_misuse(ctx))
            violations.extend(check_ref_in_lifecycle_callbacks(ctx))
            violations.extend(check_ref_operations_outside_build(ctx))

            # ConsumerState-specific checks
            violations.extend(check_widget_lifecycle_unsafe_ref(ctx))
            violations.extend(check_deferred_callbacks(ctx))
            violations.extend(check_async_event_handlers(ctx))
            violations.extend(check_untyped_lazy_getters(ctx))
            violations.extend(check_initstate_field_access(ctx))

            # NOTE: Do NOT check mounted_confusion for ConsumerStatefulWidget.
            # WidgetRef does NOT have a .mounted property — only State.mounted is valid.

        # --- ConsumerWidget classes (extends ConsumerWidget) ---
        for match in RE_CONSUMER_WIDGET_CLASS.finditer(content):
            class_name = match.group(1)
            class_start = match.start()
            brace_pos = content.find('{', match.end())
            if brace_pos == -1:
                continue
            class_end = find_matching_brace(content, brace_pos + 1)
            class_content = content[class_start:class_end + 1]

            if self.verbose:
                print(f"\n\U0001f50d Analyzing {class_name} (ConsumerWidget):")

            ctx = CheckContext(
                file_path=file_path,
                class_name=class_name,
                class_content=class_content,
                full_content=content,
                class_start=class_start,
                lines=lines,
                has_async_methods=False,
                async_methods=[],
                is_consumer_state=False,
                analysis=self._ctx,
            )

            violations.extend(check_async_event_handlers(ctx))
            violations.extend(check_deferred_callbacks(ctx))

        # --- Any class storing Ref as field (forbidden in plain classes) ---
        violations.extend(check_ref_stored_as_field(file_path, content, lines))

        # Filter suppressed violations
        suppressed = []
        kept = []
        for v in violations:
            if is_line_suppressed(lines, v.line_number):
                suppressed.append(v)
            else:
                kept.append(v)

        if self.verbose and suppressed:
            print(f"   \U0001f507 Suppressed {len(suppressed)} violation(s) via inline comments")

        return kept

    def scan_directory(
        self,
        directory: Path,
        pattern: str = "**/*.dart",
    ) -> List[Violation]:
        """Scan all Dart files in a directory with comprehensive cross-file analysis."""
        violations: List[Violation] = []

        dart_files = [
            f for f in directory.glob(pattern)
            if f.is_file()
            and not str(f).endswith('.g.dart')
            and not str(f).endswith('.freezed.dart')
        ]
        total_files = len(dart_files)

        if self.verbose:
            print(f"\n\U0001f4c1 Scanning {total_files} Dart files in {directory}...")

        # Passes 1 → 2.5: Build cross-file analysis context
        self._ctx = AnalysisContext(self.file_cache, verbose=self.verbose)
        run_all_passes(dart_files, self._ctx)

        # Pass 3: Scan for violations with full call-graph context
        if self.verbose:
            print(f"\U0001f50d PASS 3: Scanning for violations with call-graph analysis...")

        scanned = 0
        for file_path in dart_files:
            scanned += 1
            if self.verbose and scanned % 50 == 0:
                print(f"   Progress: {scanned}/{total_files} files scanned...")

            file_violations = self.scan_file(file_path)
            violations.extend(file_violations)

        return violations

    # Backward-compatible aliases
    def format_violation(self, violation: Violation) -> str:
        """Format a violation for display (delegates to output module)."""
        return format_violation_text(violation)

    def print_summary(self, violations: List[Violation], path) -> None:
        """Print comprehensive summary (delegates to output module)."""
        print_summary_text(violations, path)


# ======================================================================
# CLI entry point
# ======================================================================

def main():
    """Command-line entry point for the Riverpod 3.0 Safety Scanner."""
    parser = argparse.ArgumentParser(
        description='Comprehensive Riverpod 3.0 compliance scanner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  riverpod-3-scanner lib
  riverpod-3-scanner lib/presentation
  riverpod-3-scanner lib/data/managers/schedule_manager.dart
  riverpod-3-scanner lib --verbose
  riverpod-3-scanner lib --format json

Exit codes:
  0: No violations found
  1: Violations found (must be fixed)
        """
    )
    parser.add_argument(
        'path',
        type=str,
        nargs='?',
        default='lib',
        help='Path to scan (file or directory, default: lib)',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output',
    )
    parser.add_argument(
        '--pattern',
        type=str,
        default='**/*.dart',
        help='Glob pattern for files to scan (default: **/*.dart)',
    )
    parser.add_argument(
        '--format',
        type=str,
        choices=['text', 'json'],
        default='text',
        help='Output format (default: text)',
    )

    args = parser.parse_args()

    scanner = RiverpodScanner(verbose=args.verbose)
    path = Path(args.path)

    if not path.exists():
        print(f"\u274c Error: Path does not exist: {path}", file=sys.stderr)
        sys.exit(2)

    if path.is_file():
        violations = scanner.scan_file(path)
    else:
        violations = scanner.scan_directory(path, args.pattern)

    if args.format == 'json':
        print(format_json(violations, path))
    else:
        print_summary_text(violations, path)

    if violations:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
