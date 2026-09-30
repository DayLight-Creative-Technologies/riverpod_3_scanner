#!/usr/bin/env python3
"""
Riverpod 3.0 Safety Scanner
Comprehensive static analysis tool for Flutter/Dart projects using Riverpod 3.0+

Author: Steven Day
Company: DayLight Creative Technologies
License: MIT

Detects ALL forbidden patterns that violate Riverpod 3.0 async safety standards.

SCANS FOUR CLASS TYPES (plus two file-scope surfaces):
- Riverpod provider classes (extends _$ClassName)
- ConsumerStatefulWidget State classes (extends ConsumerState<T>)
- ConsumerWidget classes (extends ConsumerWidget)
- HookConsumerWidget classes (extends HookConsumerWidget)
- File scope: plain classes taking/storing Ref, and top-level @riverpod
  async* function providers

FORBIDDEN PATTERNS DETECTED (20 violation types — see models.ViolationType):

CRITICAL (Will crash in production):
- Field caching (nullable/dynamic fields with getters in async classes)
- Lazy getters (get x => ref.read()) in async classes
- Async getters with field caching
- ref operation (read/watch/listen) before ref.mounted check
- Missing ref.mounted after await; state assigned directly from await
- Missing ref.mounted in catch blocks
- Nullable field direct access (_field?.method()) when getter exists
- ref operations inside lifecycle callbacks (ref.onDispose, ref.listen)
- ref.listen outside build()
- initState field access before caching (fields only cached in build())
- Sync methods with ref.read() but no mounted check (called from async context)
- Ref/WidgetRef stored as field in plain Dart class (not Riverpod notifier/widget)
- Ref/WidgetRef passed to a plain Dart class constructor (entry point to the above)
- Unguarded ref.read/watch/listen in a top-level @riverpod async* function provider
- Off-frame callbacks (Future.microtask, scheduleMicrotask, addPostFrameCallback,
  .then/.catchError/.whenComplete) using ref without a mounted guard

WARNINGS (High risk of crashes):
- ref.watch outside build()
- Widget lifecycle methods with unsafe ref (didUpdateWidget, deactivate, reassemble)
- Timer/Future.delayed deferred callbacks without mounted checks
- Async event handler callbacks without mounted checks (onTap, onPressed,
  onChanged, ... — both `() async {}` and `(value) async {}` shapes)

DEFENSIVE (Type safety & best practices):
- Untyped var lazy getters (loses type information)
- mounted vs ref.mounted confusion (educational - different lifecycles)

SPECIAL FEATURES:
- Type inference for dynamic fields (suggests proper types)
- Cross-file indirect violation detection
- Inline suppression comments (// riverpod_scanner:ignore)
- JSON output format for CI/CD integration (--format json)
- File caching for performance (each file read once)
- String-aware brace counting AND comment blanking (a // inside a string
  literal is never treated as a comment)

CORRECT PATTERN (Riverpod 3.0):
  Future<void> myMethod() async {
    if (!ref.mounted) return;  // For Riverpod providers
    if (!mounted) return;      // For ConsumerStatefulWidget (widget check)
    final logger = ref.read(myLoggerProvider);
    await operation();
    if (!mounted) return;      // After await
    logger.logInfo('Done');
  }

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/docs/GUIDE.md
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Set

from . import __version__
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
    RE_HOOK_CONSUMER_WIDGET_CLASS,
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
    check_ref_into_plain_class,
    check_async_star_function_providers,
    check_build_listen_sync_state_mutation,
    check_log_after_mounted_guard,
    check_catch_guard_returns_success,
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

        # Count of violations silenced via inline suppression comments,
        # accumulated across scan_file calls. Reported in text and JSON
        # output so suppressions stay visible instead of vanishing.
        self.suppressed_count = 0

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
            # Build-phase provider modification: a build()-registered ref.listen
            # on a SYNC provider whose callback mutates state synchronously
            # (SocialScoreKeeper gaps #376/#381). Needs cross-file async-ness, so
            # it no-ops on standalone single-file scans.
            violations.extend(check_build_listen_sync_state_mutation(ctx))

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

        # --- HookConsumerWidget classes (extends HookConsumerWidget) ---
        # Same async-surface profile as ConsumerWidget: WidgetRef has no
        # `mounted` getter, so callbacks and off-frame closures in the build
        # body must guard with `context.mounted`. Hook bodies (useEffect)
        # commonly schedule Future.microtask — the exact Sentry 9CJ shape —
        # so these classes get the event-handler and deferred-callback checks.
        for match in RE_HOOK_CONSUMER_WIDGET_CLASS.finditer(content):
            class_name = match.group(1)
            class_start = match.start()
            brace_pos = content.find('{', match.end())
            if brace_pos == -1:
                continue
            class_end = find_matching_brace(content, brace_pos + 1)
            class_content = content[class_start:class_end + 1]

            if self.verbose:
                print(f"\n\U0001f50d Analyzing {class_name} (HookConsumerWidget):")

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

        # --- Any plain class taking/storing Ref or WidgetRef (forbidden) ---
        violations.extend(check_ref_into_plain_class(file_path, content, lines))

        # --- Top-level @riverpod async* function providers with an
        #     unguarded first ref.read/watch/listen ---
        violations.extend(
            check_async_star_function_providers(file_path, content, lines)
        )

        # --- Every catch / .catchError in the file: a failure handler that
        #     logs only after its mounted guard (log-first rule) ---
        violations.extend(check_log_after_mounted_guard(file_path, content, lines))

        # --- Every catch in the file: a mounted guard that reports success
        #     while the catch otherwise reports failure ---
        violations.extend(check_catch_guard_returns_success(file_path, content, lines))

        # Filter suppressed violations
        suppressed = []
        kept = []
        for v in violations:
            if is_line_suppressed(lines, v.line_number):
                suppressed.append(v)
            else:
                kept.append(v)

        self.suppressed_count += len(suppressed)

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
        self.suppressed_count = 0

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
# Baseline support — adopt the scanner on a codebase with pre-existing
# violations. A baseline is a remove-only ledger of ACCEPTED (path, line,
# type) signatures: matching violations are suppressed, so the scan fails
# only on NEW violations. Fixing a baselined site leaves a STALE entry
# (reported, never a failure — pruning it is the remove-only discipline).
# ======================================================================

def _baseline_key(violation: Violation, root: Path) -> str:
    """Stable signature for a violation: '<path-relative-to-root>:<line>:<type>'.
    Root-relative so the ledger is portable across checkouts/worktrees."""
    try:
        rel = os.path.relpath(violation.file_path, str(root))
    except ValueError:
        rel = str(violation.file_path)
    return f"{rel}:{violation.line_number}:{violation.violation_type.value}"


def _load_baseline(baseline_path: Path) -> Set[str]:
    """Load a baseline ledger (JSON list of signature strings)."""
    data = json.loads(baseline_path.read_text())
    if not isinstance(data, list):
        raise ValueError(
            f"Baseline {baseline_path} must be a JSON list of signature strings"
        )
    return set(data)


def _write_baseline(baseline_path: Path, keys: List[str]) -> None:
    """Write a baseline ledger (sorted JSON list) for the given signatures."""
    baseline_path.write_text(json.dumps(sorted(set(keys)), indent=2) + "\n")


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
    parser.add_argument(
        '--baseline',
        type=str,
        default=None,
        metavar='FILE',
        help='Remove-only baseline ledger (JSON): suppress its accepted '
             'violations so the scan fails only on NEW ones. Stale entries are '
             'reported, never a failure.',
    )
    parser.add_argument(
        '--write-baseline',
        type=str,
        default=None,
        metavar='FILE',
        help='Write the current violations to FILE as a baseline ledger and '
             'exit 0 (regenerate an accepted baseline).',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}',
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

    # Baseline root: signatures are relative to the scanned directory (or the
    # file's parent) so the ledger is stable across checkouts.
    root = path if path.is_dir() else path.parent

    # Regenerate an accepted baseline and exit.
    if args.write_baseline is not None:
        keys = [_baseline_key(v, root) for v in violations]
        _write_baseline(Path(args.write_baseline), keys)
        print(
            f"Wrote baseline with {len(set(keys))} accepted signature(s) "
            f"to {args.write_baseline}"
        )
        sys.exit(0)

    # Apply a baseline: suppress accepted violations, fail only on new ones.
    if args.baseline is not None:
        baseline = _load_baseline(Path(args.baseline))
        new_violations = [
            v for v in violations if _baseline_key(v, root) not in baseline
        ]
        present_keys = {_baseline_key(v, root) for v in violations}
        stale = sorted(baseline - present_keys)
        suppressed = len(violations) - len(new_violations)

        if args.format == 'json':
            print(format_json(new_violations, path, scanner.suppressed_count))
        else:
            print_summary_text(new_violations, path, scanner.suppressed_count)
            if suppressed:
                print(
                    f"\nℹ️  {suppressed} baselined violation(s) suppressed "
                    f"(remove-only ledger: {args.baseline})."
                )
            if stale:
                print(
                    f"\n⚠️  {len(stale)} STALE baseline entr"
                    f"{'y' if len(stale) == 1 else 'ies'} — the violation is gone; "
                    f"prune (remove-only):"
                )
                for s in stale:
                    print(f"     {s}")
        sys.exit(1 if new_violations else 0)

    if args.format == 'json':
        print(format_json(violations, path, scanner.suppressed_count))
    else:
        print_summary_text(violations, path, scanner.suppressed_count)

    if violations:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
