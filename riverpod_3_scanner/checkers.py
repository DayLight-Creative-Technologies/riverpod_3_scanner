"""
Violation detection module for the Riverpod 3.0 Safety Scanner.

Contains ALL checker functions that detect forbidden patterns in Dart code.
Each checker receives a CheckContext and returns a list of Violations.

Author: Steven Day
Company: DayLight Creative Technologies
License: MIT
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from .models import Violation, ViolationType, MethodKey
from .utils import (
    find_matching_brace,
    find_statement_end,
    strip_comments,
    remove_comments,
    find_async_methods,
    find_methods_using_ref,
    has_significant_code_after_await,
    infer_type_from_provider,
    resolve_variable_to_class,
    extract_snippet,
    get_abs_line,
    RE_REF_OPERATION,
    RE_REF_ALL_OPERATIONS,
    RE_MOUNTED_CHECK_BROAD,
    RE_MOUNTED_CHECK_WIDGET,
    FRAMEWORK_LIFECYCLE_METHODS,
    EVENT_HANDLERS,
)

if TYPE_CHECKING:
    from .analysis import AnalysisContext


# ---------------------------------------------------------------------------
# CheckContext: shared context passed to every checker function
# ---------------------------------------------------------------------------

@dataclass
class CheckContext:
    """Context object passed to every checker function."""
    file_path: Path
    class_name: str
    class_content: str        # The class body (from class declaration to closing brace)
    full_content: str         # Entire file content
    class_start: int          # Offset of class start in full_content
    lines: List[str]          # Lines of full_content
    has_async_methods: bool
    async_methods: List[str]
    is_consumer_state: bool
    # Cross-file analysis data (populated by scan_directory; None for single-file scans)
    analysis: Optional['AnalysisContext'] = None


# ---------------------------------------------------------------------------
# Helper: find_callback_end (kept here since utils.py uses the string-aware
# find_matching_brace exclusively; this simpler version handles the "scan
# forward from an arbitrary position to find the opening '{'" pattern that
# the original scanner._find_callback_end used).
# ---------------------------------------------------------------------------

def _find_callback_end(content: str, callback_start: int) -> int:
    """Find the end of a callback function (closure).

    ``callback_start`` points somewhere at or before the opening ``{``.
    Returns position just after the matching ``}``.
    """
    brace_start = content.find('{', callback_start)
    if brace_start == -1:
        return len(content)

    # Use string-aware brace matching from utils
    closing = find_matching_brace(content, brace_start + 1)
    return closing + 1 if closing < len(content) else len(content)


# ---------------------------------------------------------------------------
# Fix-instruction helper functions
# ---------------------------------------------------------------------------

def _get_field_caching_fix(
    field_name: str, async_methods: List[str], is_consumer_state: bool = False
) -> str:
    """Get fix instructions for field caching violation."""
    base_name = field_name[1:]
    mounted_check = "if (!mounted) return;" if is_consumer_state else "if (!ref.mounted) return;"
    return f"""1. Remove: {field_name} field and getter
2. In async methods ({', '.join(async_methods)}), use:
   {mounted_check}
   final {base_name} = ref.read(provider);
   await operation();
   {mounted_check}
   {base_name}.method();"""


def _get_lazy_getter_fix(getter_name: str) -> str:
    """Get fix instructions for lazy getter violation."""
    return f"""1. Remove: lazy getter 'get {getter_name} => ref.read(...)'
2. In async methods, read just-in-time:
   if (!ref.mounted) return;
   final {getter_name} = ref.read(provider);"""


def _get_async_getter_fix(field_name: str) -> str:
    """Get fix instructions for async getter violation."""
    base_name = field_name[1:]
    return f"""1. Remove: {field_name} field and async getter
2. In async methods, use:
   if (!ref.mounted) return;
   final {base_name} = await ref.read(provider.future);
   if (!ref.mounted) return;"""


def _get_ref_read_before_mounted_fix() -> str:
    """Get fix instructions for ref operation before mounted check."""
    return """Add at method entry BEFORE any ref operation (read/watch/listen):
   if (!ref.mounted) return;
   final dep = ref.read(provider);
   // OR
   ref.watch(someProvider);
   // OR
   ref.listen(someProvider, (prev, next) { ... });"""


def _get_missing_mounted_after_await_fix() -> str:
    """Get fix instructions for missing mounted after await."""
    return """Add after EVERY await:
   await operation();
   if (!ref.mounted) return;"""


def _get_missing_mounted_in_catch_fix() -> str:
    """Get fix instructions for missing mounted in catch."""
    return """Add at start of catch block:
   catch (e, st) {
     if (!ref.mounted) return;
     final logger = ref.read(myLoggerProvider);
     logger.logError(...);
   }"""


def _get_ref_in_lifecycle_fix(
    ref_or_method: str,
    is_direct: bool = True,
    is_cross_class: bool = False,
    callback_type: str = "ref.onDispose",
) -> str:
    """Get fix instructions for ref operations in lifecycle callbacks."""
    if is_direct:
        return f"""CRITICAL: Cannot use ref.{ref_or_method}() inside {callback_type}() callbacks!

Riverpod Error: "Cannot use Ref or modify other providers inside life-cycles/selectors"

FIX OPTIONS:
1. Capture dependency BEFORE {callback_type}():
   final logger = ref.read(myLoggerProvider);
   {callback_type}(() {{
     // Use captured logger - NO ref.read() here
     logger.logInfo('Disposing');
   }});

2. Remove ref operations entirely:
   {callback_type}(() {{
     // Only cleanup non-ref resources
     _subscription?.cancel();
   }});

3. If cleanup needs provider access, restructure to not require it in disposal

Reference: https://github.com/rrousselGit/riverpod/issues/1879
Riverpod explicitly forbids ref operations inside lifecycle callbacks."""
    else:
        return f"""CRITICAL: Cannot call {ref_or_method}() inside ref.onDispose() - it uses ref internally!

Riverpod Error: "Cannot use Ref or modify other providers inside life-cycles/selectors"

The method {ref_or_method}() contains ref.read/watch/listen operations, which are
FORBIDDEN inside lifecycle callbacks like ref.onDispose().

FIX OPTIONS:
1. Refactor {ref_or_method}() to accept dependencies as parameters:
   // In build() or other method:
   final eventNotifier = ref.read(someProvider.notifier);
   ref.onDispose(() {{
     // Pass dependency as parameter - NO ref.read() inside
     {ref_or_method}(eventNotifier);
   }});

2. Extract non-ref cleanup logic:
   // Create new method that doesn't use ref
   void {ref_or_method}NoRef() {{
     // Cleanup without ref operations
   }}
   ref.onDispose(() {{
     {ref_or_method}NoRef();
   }});

3. Remove the method call from onDispose entirely if not essential

Reference: https://github.com/rrousselGit/riverpod/issues/1879"""


# ===========================================================================
# CHECKER 1: check_field_caching
# ===========================================================================

def check_field_caching(ctx: CheckContext) -> List[Violation]:
    """Check for all field caching patterns (VIOLATIONS 1-3).

    Detects:
    - Direct lazy getters: ``Type get name => ref.read(...)``
    - Dynamic lazy getters: ``dynamic _field; dynamic get field { _field ??= ref.read(...) }``
    - Nullable/dynamic/late-final fields with sync or async getters
    """
    violations: List[Violation] = []
    class_content = ctx.class_content
    full_content = ctx.full_content
    class_start = ctx.class_start
    lines = ctx.lines

    # ------------------------------------------------------------------
    # CHECK DIRECT LAZY GETTERS (no field): TypeName get name => ref.read(...)
    # ------------------------------------------------------------------
    if ctx.has_async_methods:
        direct_lazy_getter_pattern = re.compile(
            r'(\w+)\s+get\s+(\w+)\s*=>\s*ref\.read\([^)]+\);'
        )

        for getter_match in direct_lazy_getter_pattern.finditer(class_content):
            getter_type = getter_match.group(1)
            getter_name = getter_match.group(2)
            abs_getter_line = full_content[:class_start + getter_match.start()].count('\n') + 1

            snippet_start = max(0, abs_getter_line - 1)
            snippet_end = min(len(lines), abs_getter_line + 3)
            snippet = '\n'.join(f"  {i + 1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

            violations.append(Violation(
                file_path=str(ctx.file_path),
                class_name=ctx.class_name,
                violation_type=ViolationType.LAZY_GETTER,
                line_number=abs_getter_line,
                context=f"DEADLY: Direct lazy getter 'get {getter_name} => ref.read()' in async class - will crash on widget unmount",
                code_snippet=snippet,
                fix_instructions=f"""CRITICAL: This lazy getter caused production crash (Sentry issue #7055596134)

❌ PROBLEM: Using lazy getter in ConsumerStatefulWidget with async methods
   Line {abs_getter_line}: {getter_type} get {getter_name} => ref.read(...);

   When widget unmounts during async operation, this getter crashes:
   StateError: Using "ref" when a widget is about to or has been unmounted

✅ FIX: Remove lazy getter, use just-in-time ref.read() with mounted checks

BEFORE (CRASHES):
   {getter_type} get {getter_name} => ref.read(myLoggerProvider);

   Future<void> _initializeScreen() async {{
     {getter_name}.logInfo('Start');  // ❌ CRASH if widget unmounted
     await operation();
     {getter_name}.logInfo('Done');   // ❌ CRASH if widget unmounted
   }}

AFTER (SAFE):
   // Remove lazy getter entirely

   Future<void> _initializeScreen() async {{
     if (!mounted) return;
     final {getter_name} = ref.read(myLoggerProvider);
     {getter_name}.logInfo('Start');

     await operation();
     if (!mounted) return;

     {getter_name}.logInfo('Done');
   }}

Applies to all async methods: {', '.join(ctx.async_methods)}

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md
Sentry Issue: #7055596134 (iOS production crash)"""
            ))

    # ------------------------------------------------------------------
    # CHECK DYNAMIC LAZY GETTERS
    # ------------------------------------------------------------------
    if ctx.has_async_methods:
        dynamic_field_pattern = re.compile(r'dynamic\s+(_\w+);')

        for field_match in dynamic_field_pattern.finditer(class_content):
            field_name = field_match.group(1)
            base_name = field_name[1:]

            dynamic_getter_pattern = re.compile(
                rf'dynamic\s+get\s+{base_name}\s*\{{[^}}]*{field_name}\s*\?\?=\s*ref\.read\(([^)]+)\)',
                re.DOTALL,
            )

            getter_match = dynamic_getter_pattern.search(class_content)
            if getter_match:
                provider_expr = getter_match.group(1)
                abs_getter_line = full_content[:class_start + getter_match.start()].count('\n') + 1

                snippet_start = max(0, abs_getter_line - 1)
                snippet_end = min(len(lines), abs_getter_line + 6)
                snippet = '\n'.join(f"  {i + 1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                suggested_type = infer_type_from_provider(provider_expr)

                violations.append(Violation(
                    file_path=str(ctx.file_path),
                    class_name=ctx.class_name,
                    violation_type=ViolationType.FIELD_CACHING,
                    line_number=abs_getter_line,
                    context=f"CRITICAL: dynamic lazy getter in async class - loses type safety AND crashes on unmount",
                    code_snippet=snippet,
                    fix_instructions=f"""CRITICAL: Using 'dynamic' removes type safety and will crash on widget unmount

❌ PROBLEM: dynamic lazy getter with ref.read() in async class
   Line {abs_getter_line}: dynamic get {base_name} {{ {field_name} ??= ref.read({provider_expr}); }}

   TWO ISSUES:
   1. Type Safety: 'dynamic' bypasses Dart's type system - runtime errors not caught
   2. Crash Risk: Will crash if widget unmounts during async operation

✅ FIX: Remove dynamic lazy getter, use properly typed just-in-time ref.read()

BEFORE (UNSAFE):
   dynamic {field_name};
   dynamic get {base_name} {{
     {field_name} ??= ref.read({provider_expr});
     return {field_name}!;
   }}

   Future<void> myMethod() async {{
     {base_name}.doSomething();  // ❌ No type checking, will crash if unmounted
     await operation();
     {base_name}.doSomething();  // ❌ CRASH if widget unmounted
   }}

AFTER (SAFE & TYPED):
   // Remove dynamic field and getter entirely

   Future<void> myMethod() async {{
     if (!mounted) return;
     final {base_name} = ref.read({provider_expr});  // ✅ Properly typed
     {base_name}.doSomething();  // ✅ Type-safe

     await operation();
     if (!mounted) return;

     {base_name}.doSomething();  // ✅ Safe after mounted check
   }}

SUGGESTED TYPE: {suggested_type}

If using .notifier, the type is the Notifier class name (e.g., InvitationWizardState)
If using provider directly, check the provider's return type

Applies to all async methods: {', '.join(ctx.async_methods)}

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                ))

    # ------------------------------------------------------------------
    # Collect all fields (nullable, dynamic, late final)
    # ------------------------------------------------------------------
    generic_field_pattern = re.compile(r'(\w+(?:<.+?>)?)\?\s+(_\w+);', re.DOTALL)
    dynamic_field_pattern_2 = re.compile(r'\bdynamic\s+(_\w+);')
    late_final_field_pattern = re.compile(r'late\s+final\s+(\w+(?:<.+?>)?)\??\s+(_\w+);', re.DOTALL)

    all_fields: List[Tuple[str, str, int]] = []
    for field_match in generic_field_pattern.finditer(class_content):
        line_num = full_content[:class_start + field_match.start()].count('\n') + 1
        all_fields.append((field_match.group(1), field_match.group(2), line_num))
    for field_match in dynamic_field_pattern_2.finditer(class_content):
        line_num = full_content[:class_start + field_match.start()].count('\n') + 1
        all_fields.append(('dynamic', field_match.group(1), line_num))
    for field_match in late_final_field_pattern.finditer(class_content):
        line_num = full_content[:class_start + field_match.start()].count('\n') + 1
        all_fields.append((field_match.group(1), field_match.group(2), line_num))

    for field_type, field_name, abs_field_line in all_fields:
        base_name = field_name[1:]
        escaped_field_type = re.escape(field_type)

        # Build sync getter patterns
        if field_type == 'dynamic':
            sync_getter_patterns = [
                rf'\w+\s+get\s+{base_name}\s*\{{[^}}]*{field_name}[^}}]*StateError',
                rf'\w+\s+get\s+{base_name}\s*\{{[^}}]*{field_name}\s*\?\?=',
                rf'\w+\s+get\s+{base_name}\s*=>\s*{field_name}\s*;',
            ]
        else:
            sync_getter_patterns = [
                rf'{escaped_field_type}\??\s+get\s+{base_name}\s*\{{[^}}]*{field_name}[^}}]*StateError',
                rf'{escaped_field_type}\??\s+get\s+{base_name}\s*\{{[^}}]*{field_name}\s*\?\?=',
                rf'{escaped_field_type}\??\s+get\s+{base_name}\s*=>\s*ref\.read\(',
                rf'{escaped_field_type}\??\s+get\s+{base_name}\s*=>\s*{field_name}\s*;',
            ]

        async_getter_patterns = [
            rf'Future<{escaped_field_type}>\s+get\s+{base_name}\s+async\s*\{{',
            rf'Future<{escaped_field_type}>\s+get\s+{base_name}Future\s+async\s*\{{',
        ]

        # Check sync getters
        for pattern in sync_getter_patterns:
            getter_match = re.search(pattern, class_content, re.DOTALL)
            if getter_match:
                abs_getter_line = full_content[:class_start + getter_match.start()].count('\n') + 1

                snippet_start = max(0, abs_getter_line - 1)
                snippet_end = min(len(lines), abs_getter_line + 8)
                snippet = '\n'.join(f"  {i + 1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                if ctx.has_async_methods:
                    violations.append(Violation(
                        file_path=str(ctx.file_path),
                        class_name=ctx.class_name,
                        violation_type=ViolationType.FIELD_CACHING,
                        line_number=abs_getter_line,
                        context=f"Field caching: {field_name} with getter in async class",
                        code_snippet=snippet,
                        fix_instructions=_get_field_caching_fix(field_name, ctx.async_methods, ctx.is_consumer_state),
                    ))
                elif 'ref.read' in getter_match.group(0):
                    violations.append(Violation(
                        file_path=str(ctx.file_path),
                        class_name=ctx.class_name,
                        violation_type=ViolationType.LAZY_GETTER,
                        line_number=abs_getter_line,
                        context=f"Lazy getter: get {base_name} => ref.read()",
                        code_snippet=snippet,
                        fix_instructions=_get_lazy_getter_fix(base_name),
                    ))
                break

        # Check async getters
        for pattern in async_getter_patterns:
            getter_match = re.search(pattern, class_content, re.DOTALL)
            if getter_match:
                abs_getter_line = full_content[:class_start + getter_match.start()].count('\n') + 1

                snippet_start = max(0, abs_getter_line - 1)
                snippet_end = min(len(lines), abs_getter_line + 8)
                snippet = '\n'.join(f"  {i + 1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(ctx.file_path),
                    class_name=ctx.class_name,
                    violation_type=ViolationType.ASYNC_GETTER,
                    line_number=abs_getter_line,
                    context=f"Async getter with field caching: {field_name}",
                    code_snippet=snippet,
                    fix_instructions=_get_async_getter_fix(field_name),
                ))
                break

    return violations


# ===========================================================================
# CHECKER 2: check_async_method_safety
# ===========================================================================

def check_async_method_safety(ctx: CheckContext) -> List[Violation]:
    """Check async methods for ref safety patterns (VIOLATIONS 4-6).

    Detects:
    - ref operation (read/watch/listen) before mounted check
    - Missing ref.mounted after await
    - Missing ref.mounted in catch blocks
    """
    violations: List[Violation] = []
    class_content = ctx.class_content
    full_content = ctx.full_content
    class_start = ctx.class_start
    lines = ctx.lines

    # Determine mounted pattern
    if ctx.is_consumer_state:
        mounted_pattern = r'if\s*\(\s*!mounted\s*\)'
    else:
        mounted_pattern = r'if\s*\(\s*!ref\.mounted\s*\)'

    for method_name in ctx.async_methods:
        method_pattern = re.compile(
            rf'(?:Future<[^>]+>|FutureOr<[^>]+>|Stream<[^>]+>)\s+{method_name}\s*\([^)]*\)\s+async\*?\s*\{{',
            re.DOTALL,
        )
        method_match = method_pattern.search(class_content)

        if not method_match:
            continue

        method_start = method_match.end()
        method_end = find_matching_brace(class_content, method_start)
        method_body = class_content[method_start:method_end]
        method_lines = method_body.split('\n')

        # ---- VIOLATION 4: ref operation before mounted check ----
        first_10_lines = '\n'.join(method_lines[:10])
        first_10_lines_no_comments = remove_comments(first_10_lines)

        has_early_mounted = re.search(mounted_pattern, first_10_lines_no_comments)
        ref_operation_match = re.search(r'ref\.(read|watch|listen)\(', first_10_lines_no_comments)

        if ref_operation_match and not has_early_mounted:
            operation_name = ref_operation_match.group(1)
            abs_line = full_content[:class_start + method_start].count('\n') + 2
            snippet_start = max(0, abs_line - 1)
            snippet_end = min(len(lines), abs_line + 5)
            snippet = '\n'.join(f"  {i + 1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

            violations.append(Violation(
                file_path=str(ctx.file_path),
                class_name=ctx.class_name,
                violation_type=ViolationType.REF_READ_BEFORE_MOUNTED,
                line_number=abs_line,
                context=f"Method {method_name}(): ref.{operation_name}() before mounted check",
                code_snippet=snippet,
                fix_instructions=_get_ref_read_before_mounted_fix(),
            ))

        # ---- VIOLATION 5: Missing ref.mounted after await ----
        await_pattern = re.compile(r'await\s+')
        for await_match in await_pattern.finditer(method_body):
            await_line_num = method_body[:await_match.start()].count('\n')
            await_line_in_body = await_line_num

            await_statement_start = await_match.start()
            await_statement_end = find_statement_end(method_body, await_statement_start)

            await_statement = method_body[await_statement_start:await_statement_end]

            # Skip if await contains a callback/closure
            if re.search(r':\s*\([^)]*\)\s*\{', await_statement) or re.search(r':\s*\(\)\s*\{', await_statement):
                continue

            # Skip "return await" statements
            current_line = method_lines[await_line_num] if await_line_num < len(method_lines) else ''
            if re.search(r'\breturn\s+await\s+', current_line):
                continue

            remaining_lines = method_lines[await_line_num + 1:await_line_num + 26]
            next_lines_str = '\n'.join(remaining_lines)

            has_mounted_after = re.search(mounted_pattern, next_lines_str)
            has_significant = has_significant_code_after_await(next_lines_str)

            if has_significant and not has_mounted_after:
                abs_line = full_content[:class_start + method_start + await_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 5)
                snippet = '\n'.join(f"  {i + 1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(ctx.file_path),
                    class_name=ctx.class_name,
                    violation_type=ViolationType.MISSING_MOUNTED_AFTER_AWAIT,
                    line_number=abs_line,
                    context=f"Method {method_name}(): Missing ref.mounted after await",
                    code_snippet=snippet,
                    fix_instructions=_get_missing_mounted_after_await_fix(),
                ))

        # ---- VIOLATION 6: Missing mounted in catch blocks ----
        catch_pattern = re.compile(r'catch\s*\([^)]+\)\s*\{')
        for catch_match in catch_pattern.finditer(method_body):
            catch_start = catch_match.end()
            catch_end = find_matching_brace(method_body, catch_start)
            catch_body = method_body[catch_start:catch_end]

            catch_first_lines = '\n'.join(catch_body.split('\n')[:5])
            has_mounted = re.search(mounted_pattern, catch_first_lines)
            has_ref_usage = re.search(r'ref\.(read|watch|listen)', catch_first_lines)

            if has_ref_usage and not has_mounted:
                abs_line = full_content[:class_start + method_start + catch_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 8)
                snippet = '\n'.join(f"  {i + 1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(ctx.file_path),
                    class_name=ctx.class_name,
                    violation_type=ViolationType.MISSING_MOUNTED_IN_CATCH,
                    line_number=abs_line,
                    context=f"Method {method_name}(): Missing ref.mounted in catch block",
                    code_snippet=snippet,
                    fix_instructions=_get_missing_mounted_in_catch_fix(),
                ))

    return violations


# ===========================================================================
# CHECKER 3: check_sync_methods_without_mounted
# ===========================================================================

def _find_sync_methods_with_ref_read(
    class_content: str, is_consumer_state: bool = False
) -> List[Tuple[str, int, str]]:
    """Find sync methods (non-async) that use ref.read() without mounted checks.

    Returns: List of (method_name, line_offset, method_body).
    """
    results: List[Tuple[str, int, str]] = []

    if is_consumer_state:
        mounted_pattern = r'if\s*\(\s*!mounted\s*\)\s*return'
    else:
        mounted_pattern = r'if\s*\(\s*!ref\.mounted\s*\)\s*return'

    method_pattern = re.compile(
        r'(?:void|bool|String|int|double|num|\w+\?)\s+(\w+)\s*\([^)]*\)\s*\{',
        re.DOTALL,
    )

    for method_match in method_pattern.finditer(class_content):
        method_name = method_match.group(1)
        method_start = method_match.end()
        method_end = find_matching_brace(class_content, method_start)
        method_body = class_content[method_start:method_end]

        # Skip framework lifecycle methods
        if method_name in FRAMEWORK_LIFECYCLE_METHODS:
            continue

        # Skip async methods
        full_signature = class_content[max(0, method_match.start() - 50):method_match.end() + 20]
        if re.search(r'\basync\b', full_signature):
            continue

        ref_read_matches = list(re.finditer(r'ref\.read\(', method_body))
        if not ref_read_matches:
            continue

        first_ref_read_pos = ref_read_matches[0].start()

        before_first_ref_read = method_body[:first_ref_read_pos]
        has_mounted_check = re.search(mounted_pattern, before_first_ref_read)

        if not has_mounted_check:
            line_offset = class_content[:method_match.start()].count('\n')
            results.append((method_name, line_offset, method_body))

    return results


def check_sync_methods_without_mounted(ctx: CheckContext) -> List[Violation]:
    """Check for VIOLATION 10: Sync methods with ref.read() but no mounted check.

    Only flags methods that are called from async contexts (cross-file analysis).
    """
    violations: List[Violation] = []

    sync_methods = _find_sync_methods_with_ref_read(ctx.class_content, ctx.is_consumer_state)

    for method_name, line_offset, method_body in sync_methods:
        method_key = (str(ctx.file_path), ctx.class_name, method_name)

        # Only flag if cross-file analysis is available AND method is in async context
        if ctx.analysis is None:
            continue
        if method_key not in ctx.analysis.methods_called_from_async:
            continue

        abs_line = ctx.full_content[:ctx.class_start].count('\n') + line_offset + 1

        snippet_start = max(0, abs_line - 1)
        snippet_end = min(len(ctx.lines), abs_line + 8)
        snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

        mounted_check = 'if (!mounted) return;' if ctx.is_consumer_state else 'if (!ref.mounted) return;'

        violations.append(Violation(
            file_path=str(ctx.file_path),
            class_name=ctx.class_name,
            violation_type=ViolationType.SYNC_METHOD_WITHOUT_MOUNTED_CHECK,
            line_number=abs_line,
            context=f"Method {method_name}(): Sync method uses ref.read() without mounted check (DANGEROUS when called from async callbacks)",
            code_snippet=snippet,
            fix_instructions=f"""CRITICAL: This sync method uses ref.read() without checking mounted state first.

PROBLEM:
- Method is safe when called synchronously
- CRASHES when called from async callbacks (onCompletion:, builder:, etc.)
- Provider can dispose during await gap before callback executes
- Sentry Error: UnmountedRefException (e.g. #7109530155)

EXAMPLE CRASH PATTERN:
await service.handleSomething(
    onCompletion: () {{
        notifier.{method_name}(); // ← CRASH if provider disposed during await
    }}
);

FIX:
Add mounted check at method entry:

void {method_name}() {{
    {mounted_check}  // ← ADD THIS

    // Existing ref.read() calls now safe
    final logger = ref.read(myLoggerProvider);
    ...
}}

ALTERNATIVE (if method is ONLY called from async contexts):
Make method async and add proper checks:

Future<void> {method_name}() async {{
    {mounted_check}

    final logger = ref.read(myLoggerProvider);
    // ... rest of code
}}

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
        ))

    return violations


# ===========================================================================
# CHECKER 4: check_nullable_field_misuse
# ===========================================================================

def check_nullable_field_misuse(ctx: CheckContext) -> List[Violation]:
    """Check for VIOLATION 7: Using _field?.method() when getter exists."""
    violations: List[Violation] = []

    field_pattern = re.compile(r'(\w+)\?\s+(_\w+);')

    for field_match in field_pattern.finditer(ctx.class_content):
        field_type = field_match.group(1)
        field_name = field_match.group(2)
        base_name = field_name[1:]

        getter_pattern = re.compile(rf'{field_type}\s+get\s+{base_name}\s*[{{=>]')
        has_getter = getter_pattern.search(ctx.class_content)

        if has_getter:
            nullable_access_pattern = re.compile(rf'{field_name}\?\.')

            for access_match in nullable_access_pattern.finditer(ctx.class_content):
                abs_line = ctx.full_content[:ctx.class_start + access_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(ctx.lines), abs_line + 3)
                snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(ctx.file_path),
                    class_name=ctx.class_name,
                    violation_type=ViolationType.NULLABLE_FIELD_ACCESS,
                    line_number=abs_line,
                    context=f"Using {field_name}?.method() instead of {base_name}.method()",
                    code_snippet=snippet,
                    fix_instructions=f"Replace {field_name}?. with {base_name}.",
                ))

    return violations


# ===========================================================================
# CHECKER 5: check_ref_in_lifecycle_callbacks
# ===========================================================================

def check_ref_in_lifecycle_callbacks(ctx: CheckContext) -> List[Violation]:
    """Check for VIOLATION 8: ref.read/watch/listen inside lifecycle callbacks.

    Checks both direct and indirect (same-class and cross-class) violations
    inside ref.onDispose() and ref.listen() callbacks.
    """
    violations: List[Violation] = []

    # Strip comments to avoid false positives
    stripped_class_content, class_position_map = strip_comments(ctx.class_content)

    # Find methods in this class that use ref operations (use original content)
    local_methods_using_ref = find_methods_using_ref(ctx.class_content)

    # Comprehensive ref usage pattern
    ref_usage_pattern = re.compile(
        r'\bref\.(read|watch|listen|invalidateSelf|invalidate|refresh|notifyListeners|onDispose|onCancel|onResume|onAddListener|onRemoveListener|state)\s*[(\.]'
    )

    # ---- STEP 2: ref.onDispose callbacks ----
    ondispose_pattern = re.compile(r'ref\.onDispose\s*\(')

    for ondispose_match in ondispose_pattern.finditer(stripped_class_content):
        callback_start = ondispose_match.end()
        callback_end = _find_callback_end(stripped_class_content, callback_start)
        callback_content = stripped_class_content[callback_start:callback_end]

        # CHECK A: Direct ref operations
        for ref_match in ref_usage_pattern.finditer(callback_content):
            stripped_pos = ondispose_match.start() + callback_start + ref_match.start()
            original_pos = class_position_map.get(stripped_pos, stripped_pos)
            abs_pos = ctx.class_start + original_pos
            abs_line = ctx.full_content[:abs_pos].count('\n') + 1

            snippet_start = max(0, abs_line - 2)
            snippet_end = min(len(ctx.lines), abs_line + 3)
            snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

            ref_op = ref_match.group(1)

            violations.append(Violation(
                file_path=str(ctx.file_path),
                class_name=ctx.class_name,
                violation_type=ViolationType.REF_IN_LIFECYCLE_CALLBACK,
                line_number=abs_line,
                context=f"DIRECT: ref.{ref_op}() called inside ref.onDispose() callback",
                code_snippet=snippet,
                fix_instructions=_get_ref_in_lifecycle_fix(ref_op, is_direct=True),
            ))

        # CHECK B: Indirect violations - same class
        for method_name in local_methods_using_ref:
            method_call_pattern = re.compile(rf'\b{method_name}\s*\(')

            for call_match in method_call_pattern.finditer(callback_content):
                stripped_pos = ondispose_match.start() + callback_start + call_match.start()
                original_pos = class_position_map.get(stripped_pos, stripped_pos)
                abs_pos = ctx.class_start + original_pos
                abs_line = ctx.full_content[:abs_pos].count('\n') + 1

                snippet_start = max(0, abs_line - 2)
                snippet_end = min(len(ctx.lines), abs_line + 3)
                snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(ctx.file_path),
                    class_name=ctx.class_name,
                    violation_type=ViolationType.REF_IN_LIFECYCLE_CALLBACK,
                    line_number=abs_line,
                    context=f"INDIRECT (same class): {method_name}() called inside ref.onDispose() - method uses ref internally",
                    code_snippet=snippet,
                    fix_instructions=_get_ref_in_lifecycle_fix(method_name, is_direct=False),
                ))

        # CHECK C: Indirect violations - cross-class
        cross_class_call_pattern = re.compile(r'(\w+)\.(\w+)\s*\(')

        for call_match in cross_class_call_pattern.finditer(callback_content):
            variable_name = call_match.group(1)
            method_name = call_match.group(2)

            if method_name in ['dispose', 'cancel', 'close', 'clear', 'reset']:
                continue

            # Cross-class resolution requires analysis context
            provider_to_class = ctx.analysis.provider_to_class if ctx.analysis else {}
            methods_using_ref_db = ctx.analysis.methods_using_ref if ctx.analysis else {}
            class_to_file_db = ctx.analysis.class_to_file if ctx.analysis else {}

            target_class = resolve_variable_to_class(
                variable_name, ctx.class_content, ctx.full_content, provider_to_class
            )

            if target_class and target_class in methods_using_ref_db:
                if method_name in methods_using_ref_db[target_class]:
                    stripped_pos = ondispose_match.start() + callback_start + call_match.start()
                    original_pos = class_position_map.get(stripped_pos, stripped_pos)
                    abs_pos = ctx.class_start + original_pos
                    abs_line = ctx.full_content[:abs_pos].count('\n') + 1

                    snippet_start = max(0, abs_line - 2)
                    snippet_end = min(len(ctx.lines), abs_line + 3)
                    snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

                    target_file = class_to_file_db.get(target_class, "unknown")

                    violations.append(Violation(
                        file_path=str(ctx.file_path),
                        class_name=ctx.class_name,
                        violation_type=ViolationType.REF_IN_LIFECYCLE_CALLBACK,
                        line_number=abs_line,
                        context=f"INDIRECT (cross-class): {variable_name}.{method_name}() called inside ref.onDispose() - {target_class}.{method_name}() uses ref internally (defined in {target_file})",
                        code_snippet=snippet,
                        fix_instructions=_get_ref_in_lifecycle_fix(f"{target_class}.{method_name}", is_direct=False, is_cross_class=True),
                    ))

    # ---- STEP 3: ref.listen callbacks ----
    listen_pattern = re.compile(r'ref\.listen\s*\(')

    for listen_match in listen_pattern.finditer(stripped_class_content):
        callback_search_start = listen_match.end()

        paren_depth = 1
        i = callback_search_start
        callback_start = None

        while i < len(stripped_class_content) and paren_depth > 0:
            if stripped_class_content[i] == '(':
                paren_depth += 1
            elif stripped_class_content[i] == ')':
                paren_depth -= 1
                if paren_depth == 0:
                    temp_i = i
                    while temp_i > callback_search_start:
                        if stripped_class_content[temp_i] == '{':
                            callback_start = temp_i + 1
                            break
                        temp_i -= 1
                    break
            elif stripped_class_content[i] == '{' and paren_depth == 1:
                callback_start = i + 1
                break
            i += 1

        if callback_start is None:
            continue

        callback_end_pos = _find_callback_end(stripped_class_content, callback_start - 1)
        callback_content = stripped_class_content[callback_start:callback_end_pos]

        for ref_match in ref_usage_pattern.finditer(callback_content):
            stripped_pos = callback_start + ref_match.start()
            original_pos = class_position_map.get(stripped_pos, stripped_pos)
            abs_pos = ctx.class_start + original_pos
            abs_line = ctx.full_content[:abs_pos].count('\n') + 1

            snippet_start = max(0, abs_line - 2)
            snippet_end = min(len(ctx.lines), abs_line + 3)
            snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

            ref_op = ref_match.group(1)

            violations.append(Violation(
                file_path=str(ctx.file_path),
                class_name=ctx.class_name,
                violation_type=ViolationType.REF_IN_LIFECYCLE_CALLBACK,
                line_number=abs_line,
                context=f"DIRECT: ref.{ref_op}() called inside ref.listen() callback",
                code_snippet=snippet,
                fix_instructions=_get_ref_in_lifecycle_fix(ref_op, is_direct=True, callback_type="ref.listen"),
            ))

    return violations


# ===========================================================================
# CHECKER 6: check_ref_operations_outside_build
# ===========================================================================

def check_ref_operations_outside_build(ctx: CheckContext) -> List[Violation]:
    """Check for ref.listen/ref.watch called outside build() method."""
    violations: List[Violation] = []

    stripped_class_content, class_position_map = strip_comments(ctx.class_content)

    # Find the build method
    build_pattern = re.compile(
        r'(@override\s+)?Widget\s+build\s*\([^)]*\)\s*\{',
        re.DOTALL,
    )

    build_match = build_pattern.search(stripped_class_content)
    if not build_match:
        return violations

    build_start = build_match.end()
    build_end = find_matching_brace(stripped_class_content, build_start)

    # Find Widget-returning helper methods
    widget_helper_methods: List[Dict] = []
    helper_pattern = re.compile(r'Widget\s+(_\w+)\s*\([^)]*\)\s*\{', re.DOTALL)

    for helper_match in helper_pattern.finditer(stripped_class_content):
        method_name = helper_match.group(1)
        method_start = helper_match.end()
        method_end = find_matching_brace(stripped_class_content, method_start)
        widget_helper_methods.append({
            'name': method_name,
            'start': method_start,
            'end': method_end,
        })

    # Build set of helpers called (directly or transitively) from build()
    build_content = stripped_class_content[build_start:build_end]
    called_helpers: Set[str] = set()

    for helper in widget_helper_methods:
        if re.search(rf'\b{helper["name"]}\s*\(', build_content):
            called_helpers.add(helper['name'])

    changed = True
    max_iterations = 10
    iteration = 0

    while changed and iteration < max_iterations:
        changed = False
        iteration += 1

        for helper in widget_helper_methods:
            if helper['name'] not in called_helpers:
                helper_content = stripped_class_content[helper['start']:helper['end']]

                for safe_helper in list(called_helpers):
                    safe_helper_obj = next((h for h in widget_helper_methods if h['name'] == safe_helper), None)
                    if safe_helper_obj:
                        safe_helper_content = stripped_class_content[safe_helper_obj['start']:safe_helper_obj['end']]
                        if re.search(rf'\b{helper["name"]}\s*\(', safe_helper_content):
                            called_helpers.add(helper['name'])
                            changed = True
                            break

    def is_in_safe_context(call_pos: int) -> bool:
        if build_start <= call_pos <= build_end:
            return True

        for helper in widget_helper_methods:
            if helper['start'] <= call_pos <= helper['end']:
                if helper['name'] in called_helpers:
                    return True

        consumer_pattern = re.compile(r'Consumer\d*\s*\(\s*builder:\s*\([^)]*\)\s*\{')
        for consumer_match in consumer_pattern.finditer(stripped_class_content):
            consumer_start = consumer_match.end()
            consumer_end = find_matching_brace(stripped_class_content, consumer_start)
            if consumer_start <= call_pos <= consumer_end:
                return True

        return False

    # Check ref.listen calls
    ref_listen_pattern = re.compile(r'\bref\.listen\s*\(')

    for listen_match in ref_listen_pattern.finditer(stripped_class_content):
        call_pos = listen_match.start()

        if not is_in_safe_context(call_pos):
            original_class_pos = class_position_map.get(call_pos, call_pos)
            abs_pos = ctx.class_start + original_class_pos
            abs_line = ctx.full_content[:abs_pos].count('\n') + 1
            snippet_start = max(0, abs_line - 3)
            snippet_end = min(len(ctx.lines), abs_line + 5)
            snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

            violations.append(Violation(
                file_path=str(ctx.file_path),
                class_name=ctx.class_name,
                violation_type=ViolationType.REF_LISTEN_OUTSIDE_BUILD,
                line_number=abs_line,
                context="ref.listen() called outside build() method",
                code_snippet=snippet,
                fix_instructions="""❌ CRITICAL: ref.listen() can only be called from build() method

Per Riverpod documentation and Flutter framework requirements:
- ref.listen() MUST be called from within the build() method
- Calling from initState(), didUpdateWidget(), or helper methods will cause AssertionError

✅ CORRECT PATTERN:
@override
Widget build(BuildContext context) {
  final logger = ref.read(myLoggerProvider);

  ref.listen(someProvider, (previous, next) {
    // Handle changes
  });

  return widget.child;
}

❌ WRONG - Causes AssertionError:
void initState() {
  super.initState();
  ref.listen(someProvider, ...);  // CRASH!
}

void _setupListener() {
  ref.listen(someProvider, ...);  // CRASH if called from initState!
}

Reference: Sentry #7088955972 - Production crash from ref.listen in initState
""",
            ))

    # Check ref.watch calls
    ref_watch_pattern = re.compile(r'\bref\.watch\s*\(')

    for watch_match in ref_watch_pattern.finditer(stripped_class_content):
        call_pos = watch_match.start()

        if not is_in_safe_context(call_pos):
            original_class_pos = class_position_map.get(call_pos, call_pos)
            abs_pos = ctx.class_start + original_class_pos
            abs_line = ctx.full_content[:abs_pos].count('\n') + 1
            snippet_start = max(0, abs_line - 3)
            snippet_end = min(len(ctx.lines), abs_line + 5)
            snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

            violations.append(Violation(
                file_path=str(ctx.file_path),
                class_name=ctx.class_name,
                violation_type=ViolationType.REF_WATCH_OUTSIDE_BUILD,
                line_number=abs_line,
                context="ref.watch() called outside build() method",
                code_snippet=snippet,
                fix_instructions="""❌ WARNING: ref.watch() should typically be in build() method

ref.watch() is designed for reactive rebuilds and should be called from build().
If you need to read a value in initState() or other methods, use ref.read() instead.

✅ CORRECT PATTERN:
@override
Widget build(BuildContext context) {
  final value = ref.watch(someProvider);  // ✅ Reactive
  return Text('Value: $value');
}

void initState() {
  super.initState();
  final value = ref.read(someProvider);  // ✅ One-time read
}

❌ WRONG:
void initState() {
  super.initState();
  final value = ref.watch(someProvider);  // ❌ Wrong method
}
""",
            ))

    return violations


# ===========================================================================
# CHECKER 7: check_widget_lifecycle_unsafe_ref
# ===========================================================================

def check_widget_lifecycle_unsafe_ref(ctx: CheckContext) -> List[Violation]:
    """Check for VIOLATION 9: Unsafe ref usage in widget lifecycle methods."""
    violations: List[Violation] = []

    risky_lifecycle_methods = {
        'didUpdateWidget': 'WARN',
        'deactivate': 'ERROR',
        'reassemble': 'WARN',
    }

    for method_name, severity in risky_lifecycle_methods.items():
        lifecycle_pattern = re.compile(
            rf'@override\s+void\s+{method_name}\s*\([^)]*\)\s*\{{',
            re.DOTALL,
        )

        for method_match in lifecycle_pattern.finditer(ctx.class_content):
            method_start = method_match.end()
            method_end = find_matching_brace(ctx.class_content, method_start)
            method_body = ctx.class_content[method_start:method_end]

            has_ref_usage = re.search(r'\bref\.(read|watch|listen)\(', method_body)

            if has_ref_usage:
                abs_line = ctx.full_content[:ctx.class_start + method_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(ctx.lines), abs_line + 10)
                snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

                context_msg = f"{severity}: ref usage in {method_name}() - widget may be unmounting"
                if severity == 'ERROR':
                    context_msg = f"DEADLY: ref usage in {method_name}() - widget IS unmounting, will crash"

                # Build method-specific fix text
                if method_name == 'deactivate':
                    option_text = f'''OPTION 1: Remove all ref operations from {method_name}()
   @override
   void {method_name}(...) {{
     super.{method_name}(...);
     // NO ref operations here - this is disposal time
     _subscription?.cancel();
     _controller?.close();
   }}'''
                else:
                    option_text = f'''OPTION 1: Capture dependencies BEFORE {method_name}() is called
   If you need to use providers when properties change, do it in build():

   @override
   Widget build(BuildContext context, WidgetRef ref) {{
     final currentProp = widget.someProp;

     ref.listen(someProvider, (prev, next) {{
       // React to changes here instead of in {method_name}()
     }});

     return ...;
   }}

OPTION 2: Use ref safely with mounted checks
   @override
   void {method_name}(...) {{
     super.{method_name}(...);

     // Only if widget still mounted
     if (mounted) {{
       WidgetsBinding.instance.addPostFrameCallback((_) {{
         if (mounted) {{
           // Now safe to use ref
           final data = ref.read(provider);
         }}
       }});
     }}
   }}'''

                violations.append(Violation(
                    file_path=str(ctx.file_path),
                    class_name=ctx.class_name,
                    violation_type=ViolationType.WIDGET_LIFECYCLE_UNSAFE_REF,
                    line_number=abs_line,
                    context=context_msg,
                    code_snippet=snippet,
                    fix_instructions=f"""{'CRITICAL' if severity == 'ERROR' else 'WARNING'}: Using ref in {method_name}() is unsafe

❌ PROBLEM: ref.read/watch/listen in {method_name}() lifecycle method
   Line {abs_line}: {method_name}() contains ref operations

   {method_name}() is called when:
   {'- Widget is being UNMOUNTED (deactivated from tree)' if method_name == 'deactivate' else '- Widget properties change (could be during disposal)' if method_name == 'didUpdateWidget' else '- Hot reload occurs (during development)'}
   - ref may be disposed or in unstable state
   {'- ANY ref operation will crash with StateError' if method_name == 'deactivate' else '- Async operations may complete after widget disposal'}

✅ FIX OPTIONS:

{option_text}

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
                ))

            # Special check for addPostFrameCallback in didUpdateWidget
            if method_name == 'didUpdateWidget':
                postframe_pattern = re.compile(r'addPostFrameCallback\s*\([^)]*\)\s*\{')
                for postframe_match in postframe_pattern.finditer(method_body):
                    pf_callback_start = postframe_match.end()
                    pf_callback_end = _find_callback_end(method_body, pf_callback_start - 1)
                    pf_callback_content = method_body[pf_callback_start:pf_callback_end]

                    has_mounted_check = re.search(r'if\s*\(\s*mounted\s*\)', pf_callback_content)

                    async_call_pattern = re.compile(r'_\w+\s*\(')
                    for call_match in async_call_pattern.finditer(pf_callback_content):
                        method_called = call_match.group(0).strip('(').strip()

                        if any(method_called.startswith('_' + am) for am in find_async_methods(ctx.class_content)):
                            if not has_mounted_check:
                                abs_line = ctx.full_content[:ctx.class_start + method_start + postframe_match.start()].count('\n') + 1
                                snippet_start = max(0, abs_line - 1)
                                snippet_end = min(len(ctx.lines), abs_line + 8)
                                snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

                                violations.append(Violation(
                                    file_path=str(ctx.file_path),
                                    class_name=ctx.class_name,
                                    violation_type=ViolationType.WIDGET_LIFECYCLE_UNSAFE_REF,
                                    line_number=abs_line,
                                    context=f"WARNING: addPostFrameCallback calling async method without mounted check",
                                    code_snippet=snippet,
                                    fix_instructions=f"""WARNING: Calling async method from addPostFrameCallback without mounted check

❌ PROBLEM: Widget may unmount before callback executes
   Line {abs_line}: addPostFrameCallback calls {method_called} without checking mounted

✅ FIX: Always check mounted before calling async methods

BEFORE (RISKY):
   WidgetsBinding.instance.addPostFrameCallback((_) {{
     {method_called}();  // ❌ Widget may be unmounted
   }});

AFTER (SAFE):
   WidgetsBinding.instance.addPostFrameCallback((_) {{
     if (mounted) {{
       {method_called}();  // ✅ Safe - widget still mounted
     }}
   }});

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
                                ))

    return violations


# ===========================================================================
# CHECKER 8: check_deferred_callbacks  (DEDUPLICATED from 6 blocks)
# ===========================================================================

@dataclass
class DeferredCallbackSpec:
    """Specification for a deferred callback type to check."""
    name: str
    pattern: re.Pattern
    severity: str
    check_getters: bool = False
    check_method_calls: bool = False
    mounted_pattern: Optional[re.Pattern] = None
    context_template: str = ""
    fix_instructions: str = ""


# Pre-compiled mounted-check patterns
_MOUNTED_CHECK_BROAD = re.compile(r'if\s*\(\s*!?\s*(ref\.)?\s*mounted\s*\)')
_MOUNTED_CHECK_WIDGET = re.compile(r'if\s*\(\s*!?mounted\s*\)')

# The six deferred callback specifications
DEFERRED_CALLBACKS = [
    DeferredCallbackSpec(
        name='Future.delayed',
        pattern=re.compile(r'Future\.delayed\s*\([^)]*\)\s*,\s*\(\)\s*\{'),
        severity='WARNING',
        check_getters=False,
        check_method_calls=True,
        mounted_pattern=_MOUNTED_CHECK_BROAD,
        context_template="WARNING: Future.delayed callback without mounted check before ref usage",
        fix_instructions="""WARNING: Deferred callbacks must check mounted before ref operations

❌ PROBLEM: Widget may unmount before Future.delayed callback executes
   Future.delayed callbacks execute AFTER a delay - widget could be disposed

✅ FIX: Always check mounted at start of callback

BEFORE (RISKY):
   Future.delayed(Duration(seconds: 3), () {
     _asyncMethod();  // ❌ Widget may be unmounted
     final data = ref.read(provider);  // ❌ Will crash if unmounted
   });

AFTER (SAFE):
   Future.delayed(Duration(seconds: 3), () {
     if (!mounted) return;  // ✅ Guard at callback entry
     _asyncMethod();
     final data = ref.read(provider);
   });

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
    ),
    DeferredCallbackSpec(
        name='Timer',
        pattern=re.compile(r'Timer(?:\.periodic)?\s*\([^,]+,\s*\([^)]*\)\s*\{'),
        severity='WARNING',
        check_getters=False,
        check_method_calls=False,
        mounted_pattern=_MOUNTED_CHECK_BROAD,
        context_template="WARNING: Timer callback without mounted check before ref usage",
        fix_instructions="""WARNING: Timer callbacks must check mounted before ref operations

❌ PROBLEM: Widget may unmount while timer is running
   Timer callbacks execute repeatedly or after delay - widget could be disposed

✅ FIX: Always check mounted at start of callback AND cancel timer on dispose

BEFORE (RISKY):
   Timer.periodic(Duration(seconds: 1), (_) {
     final data = ref.read(provider);  // ❌ Will crash if unmounted
   });

AFTER (SAFE):
   late Timer _timer;

   @override
   void initState() {
     super.initState();
     _timer = Timer.periodic(Duration(seconds: 1), (_) {
       if (!mounted) return;  // ✅ Guard at callback entry
       final data = ref.read(provider);
     });
   }

   @override
   void dispose() {
     _timer.cancel();  // ✅ Cancel timer on dispose
     super.dispose();
   }

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
    ),
    DeferredCallbackSpec(
        name='addPostFrameCallback',
        pattern=re.compile(r'addPostFrameCallback\s*\(\s*\([^)]*\)\s*\{', re.DOTALL),
        severity='CRITICAL',
        check_getters=False,
        check_method_calls=False,
        mounted_pattern=_MOUNTED_CHECK_BROAD,
        context_template="CRITICAL: addPostFrameCallback without mounted check - caused production crash",
        fix_instructions="""CRITICAL: addPostFrameCallback callbacks MUST check mounted before ref operations

❌ PROBLEM: Widget may unmount before post-frame callback executes
   Post-frame callbacks execute AFTER the current frame completes
   Widget could be disposed between scheduling and execution
   Using lazy getters (logger, notifiers) crashes when widget unmounted

✅ FIX: Always check mounted at start of callback

BEFORE (CRASHES - Production Sentry #7364580c89a044b387aafbb7a997a682):
   WidgetsBinding.instance.addPostFrameCallback((_) {
     logger.logInfo('Message');  // ❌ Lazy getter crashes if unmounted
     final notifier = ref.read(provider);  // ❌ Crashes if unmounted
   });

AFTER (SAFE):
   WidgetsBinding.instance.addPostFrameCallback((_) {
     if (!mounted) return;  // ✅ Guard at callback entry
     final logger = ref.read(myLoggerProvider);
     logger.logInfo('Message');
     final notifier = ref.read(provider);
   });

IMPORTANT: Remove lazy getter entirely and use just-in-time ref.read()
   ❌ REMOVE: MyLogger get logger => ref.read(myLoggerProvider);
   ✅ USE: if (!mounted) return; final logger = ref.read(myLoggerProvider);

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md
Sentry Issue: #7364580c89a044b387aafbb7a997a682 (iOS production crash)""",
    ),
    DeferredCallbackSpec(
        name='.then()',
        pattern=re.compile(r'\.then\s*\(\s*\([^)]*\)\s*\{', re.DOTALL),
        severity='CRITICAL',
        check_getters=True,
        check_method_calls=False,
        mounted_pattern=_MOUNTED_CHECK_WIDGET,
        context_template="CRITICAL: .then() callback without mounted check",
        fix_instructions="""CRITICAL: .then() callbacks MUST check mounted before ref operations

❌ PROBLEM: Widget may unmount before Future completes
   .then() callbacks execute when Future completes (timing unpredictable)
   Widget could be disposed while waiting for async operation
   Using lazy getters or ref operations crashes when widget unmounted

✅ FIX: Always check mounted at start of callback

BEFORE (CRASHES):
   someAsyncOperation().then((result) {
     logger.logInfo('Done');  // ❌ Lazy getter crashes if unmounted
     final notifier = ref.read(provider);  // ❌ Crashes if unmounted
   });

AFTER (SAFE):
   someAsyncOperation().then((result) {
     if (!mounted) return;  // ✅ Guard at callback entry
     final logger = ref.read(myLoggerProvider);
     logger.logInfo('Done');
     final notifier = ref.read(provider);
   });

BEST PRACTICE: Use async/await instead of .then() for better error handling
   async someMethod() async {
     final result = await someAsyncOperation();
     if (!mounted) return;
     final logger = ref.read(myLoggerProvider);
     logger.logInfo('Done');
   }

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
    ),
    DeferredCallbackSpec(
        name='.catchError()',
        pattern=re.compile(r'\.catchError\s*\(\s*\([^)]*\)\s*\{', re.DOTALL),
        severity='CRITICAL',
        check_getters=True,
        check_method_calls=False,
        mounted_pattern=_MOUNTED_CHECK_WIDGET,
        context_template="CRITICAL: .catchError() callback without mounted check",
        fix_instructions="""CRITICAL: .catchError() callbacks MUST check mounted before ref operations

❌ PROBLEM: Error handler may execute after widget unmounts
   Exception handling is unpredictable timing - widget could be disposed

✅ FIX: Always check mounted in error handlers

BEFORE (CRASHES):
   someAsyncOperation().catchError((e) {
     logger.logError('Failed', error: e);  // ❌ Crashes if unmounted
   });

AFTER (SAFE):
   someAsyncOperation().catchError((e) {
     if (!mounted) return;
     final logger = ref.read(myLoggerProvider);
     logger.logError('Failed', error: e);
   });

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
    ),
    DeferredCallbackSpec(
        name='.whenComplete()',
        pattern=re.compile(r'\.whenComplete\s*\(\s*\([^)]*\)\s*\{', re.DOTALL),
        severity='CRITICAL',
        check_getters=True,
        check_method_calls=False,
        mounted_pattern=_MOUNTED_CHECK_WIDGET,
        context_template="CRITICAL: .whenComplete() callback without mounted check",
        fix_instructions="""CRITICAL: .whenComplete() callbacks MUST check mounted before ref operations

❌ PROBLEM: Completion handler executes after widget may have unmounted

✅ FIX: Always check mounted in completion handlers

BEFORE (CRASHES):
   someAsyncOperation().whenComplete(() {
     logger.logInfo('Complete');  // ❌ Crashes if unmounted
   });

AFTER (SAFE):
   someAsyncOperation().whenComplete(() {
     if (!mounted) return;
     final logger = ref.read(myLoggerProvider);
     logger.logInfo('Complete');
   });

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
    ),
]


def check_deferred_callbacks(ctx: CheckContext) -> List[Violation]:
    """Check for VIOLATION 10: Timer/Future.delayed/post-frame/.then/.catchError/.whenComplete
    callbacks without mounted checks.

    Unified, data-driven approach replacing 6 nearly identical blocks.
    """
    violations: List[Violation] = []

    for spec in DEFERRED_CALLBACKS:
        for match in spec.pattern.finditer(ctx.class_content):
            callback_start = match.end()
            callback_end = _find_callback_end(ctx.class_content, callback_start - 1)
            callback_content = ctx.class_content[callback_start:callback_end]

            # Check if callback has mounted check
            has_mounted_check = spec.mounted_pattern.search(callback_content) if spec.mounted_pattern else False

            # Check if callback uses ref
            has_ref_usage = bool(re.search(r'\bref\.(read|watch|listen)\(', callback_content))

            # Check if callback uses lazy getters (only for .then/.catchError/.whenComplete)
            has_getter_usage = False
            if spec.check_getters:
                has_getter_usage = bool(re.search(
                    r'\b(logger|[a-z][a-zA-Z]*Notifier|[a-z][a-zA-Z]*Service)\s*\.',
                    callback_content,
                ))

            # Check if callback calls methods that might use ref (only for Future.delayed)
            has_method_calls = False
            if spec.check_method_calls:
                has_method_calls = bool(re.search(r'_\w+\s*\(', callback_content))

            # Determine if violation should be raised
            has_dangerous_usage = has_ref_usage or has_getter_usage or has_method_calls

            if has_dangerous_usage and not has_mounted_check:
                abs_line = ctx.full_content[:ctx.class_start + match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(ctx.lines), abs_line + 8)
                snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(ctx.file_path),
                    class_name=ctx.class_name,
                    violation_type=ViolationType.DEFERRED_CALLBACK_UNSAFE_REF,
                    line_number=abs_line,
                    context=spec.context_template,
                    code_snippet=snippet,
                    fix_instructions=spec.fix_instructions,
                ))

    return violations


# ===========================================================================
# CHECKER 9: check_async_event_handlers
# ===========================================================================

def check_async_event_handlers(ctx: CheckContext) -> List[Violation]:
    """Check for VIOLATION 15: Async event handler callbacks without mounted checks.

    Detects async lambdas in event handlers (onTap, onPressed, etc.) that use
    ref after await without checking ref.mounted.
    """
    violations: List[Violation] = []

    for handler in EVENT_HANDLERS:
        pattern = re.compile(
            rf'{handler}\s*:\s*\(\)\s*async\s*\{{',
            re.DOTALL,
        )

        for match in pattern.finditer(ctx.class_content):
            callback_start = match.end()
            callback_end = _find_callback_end(ctx.class_content, callback_start - 1)
            callback_content = ctx.class_content[callback_start:callback_end]

            # Check for await statements
            await_pattern = re.compile(r'\bawait\s+')
            await_matches = list(await_pattern.finditer(callback_content))

            if not await_matches:
                continue

            # Check for ref usage after any await
            ref_usages: List[re.Match] = []
            ref_pattern = re.compile(r'\bref\.(read|watch|listen)\(')

            for ref_match in ref_pattern.finditer(callback_content):
                ref_pos = ref_match.start()

                for await_match in await_matches:
                    if ref_pos > await_match.end():
                        ref_usages.append(ref_match)
                        break

            if not ref_usages:
                continue

            # Collect mounted checks
            mounted_checks: List[re.Match] = []

            # Pattern 1: Early return guards
            for m in re.finditer(r'if\s*\(\s*!\s*(ref\.)?mounted\s*\)\s*return', callback_content):
                mounted_checks.append(m)

            # Pattern 2: Positive mounted checks in compound conditions
            for m in re.finditer(r'if\s*\([^)]*\b(ref\.)?mounted\b[^)]*\)', callback_content):
                condition = m.group(0)
                if 'ref.mounted' in condition or ('mounted' in condition and 'ref' not in condition):
                    mounted_checks.append(m)

            # For each ref usage after await, verify mounted check
            for ref_usage in ref_usages:
                ref_pos = ref_usage.start()

                last_mounted_check = None
                for mounted_check in mounted_checks:
                    if mounted_check.start() < ref_pos:
                        last_mounted_check = mounted_check

                has_await_after_check = False
                if last_mounted_check:
                    check_pos = last_mounted_check.end()
                    for await_match in await_matches:
                        if check_pos < await_match.start() < ref_pos:
                            has_await_after_check = True
                            break
                else:
                    has_await_after_check = True

                if has_await_after_check or last_mounted_check is None:
                    abs_line = ctx.full_content[:ctx.class_start + match.start()].count('\n') + 1
                    snippet_start = max(0, abs_line - 1)
                    snippet_end = min(len(ctx.lines), abs_line + 15)
                    snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

                    violations.append(Violation(
                        file_path=str(ctx.file_path),
                        class_name=ctx.class_name,
                        violation_type=ViolationType.DEFERRED_CALLBACK_UNSAFE_REF,
                        line_number=abs_line,
                        context=f"CRITICAL: {handler} async callback uses ref after await without ref.mounted check",
                        code_snippet=snippet,
                        fix_instructions=f"""CRITICAL: Async event handler callbacks MUST check ref.mounted before ref operations

❌ PROBLEM: Widget may unmount while async {handler} callback is executing
   When async callbacks execute across await boundaries, the widget could be disposed
   before the callback completes. Using ref after the widget unmounts causes StateError.

   **PRODUCTION CRASH**: This pattern caused Sentry issue #7230735475

✅ FIX: Always check ref.mounted AFTER each await and BEFORE each ref operation

BEFORE (CRASHES):
   {handler}: () async {{
     final data = await someAsyncCall();
     // Widget could have unmounted during the await
     final provider = ref.read(myProvider);  // ❌ CRASH if unmounted
     provider.doSomething(data);
   }}

AFTER (SAFE):
   {handler}: () async {{
     final data = await someAsyncCall();
     if (!ref.mounted) return;  // ✅ Check after await
     final provider = ref.read(myProvider);
     provider.doSomething(data);
   }}

PATTERN: ref.mounted checks AFTER every await statement in async callbacks

For ConsumerWidget: Use `if (!ref.mounted) return;`
For ConsumerStatefulWidget: Use `if (!mounted) return;`

Reference: docs/quick_reference/async_patterns.md
Caused by: Sentry #7230735475 - StateError in TournamentGameCardContent.build""",
                    ))
                    # Only report once per callback
                    break

    return violations


# ===========================================================================
# CHECKER 10: check_untyped_lazy_getters
# ===========================================================================

def check_untyped_lazy_getters(ctx: CheckContext) -> List[Violation]:
    """Check for VIOLATION 11: Untyped var lazy getters (defensive)."""
    violations: List[Violation] = []

    if not ctx.has_async_methods:
        return violations

    var_field_pattern = re.compile(r'\bvar\s+(_\w+);')

    for field_match in var_field_pattern.finditer(ctx.class_content):
        field_name = field_match.group(1)
        base_name = field_name[1:]

        getter_pattern = re.compile(
            rf'get\s+{base_name}\s*(?:=>|\{{)[^}}]*ref\.read\(',
            re.DOTALL,
        )

        getter_match = getter_pattern.search(ctx.class_content)
        if getter_match:
            abs_getter_line = ctx.full_content[:ctx.class_start + getter_match.start()].count('\n') + 1

            snippet_start = max(0, abs_getter_line - 2)
            snippet_end = min(len(ctx.lines), abs_getter_line + 5)
            snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

            violations.append(Violation(
                file_path=str(ctx.file_path),
                class_name=ctx.class_name,
                violation_type=ViolationType.UNTYPED_LAZY_GETTER,
                line_number=abs_getter_line,
                context=f"WARNING: Untyped var lazy getter - loses type safety",
                code_snippet=snippet,
                fix_instructions=f"""WARNING: Using 'var' for lazy getter removes type safety

❌ PROBLEM: var {field_name}; with lazy getter loses type information
   Line {abs_getter_line}: No explicit type annotation

   Dart infers type from first assignment, but:
   1. Type is not visible in code (readability issue)
   2. Runtime errors not caught at compile time
   3. IDE autocomplete degraded

✅ FIX: Use explicit type annotation

BEFORE (UNCLEAR):
   var {field_name};
   get {base_name} => {field_name} ??= ref.read(provider);

AFTER (CLEAR):
   // Remove lazy getter, use just-in-time typed read

   Future<void> myMethod() async {{
     if (!mounted) return;
     final {base_name} = ref.read(provider);  // ✅ Type inferred from provider
   }}

   // OR if you must keep a getter for sync-only class:
   // (Only if class has NO async methods!)
   ProviderType get {base_name} => ref.read(provider);

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
            ))

    return violations


# ===========================================================================
# CHECKER 11: check_mounted_confusion
# ===========================================================================

def check_mounted_confusion(ctx: CheckContext) -> List[Violation]:
    """Check for VIOLATION 12: mounted vs ref.mounted confusion (educational).

    Only applies to @riverpod provider classes (NOT ConsumerStatefulWidget).
    """
    violations: List[Violation] = []

    for method_name in ctx.async_methods:
        method_pattern = re.compile(
            rf'(?:Future<[^>]+>|FutureOr<[^>]+>|Stream<[^>]+>)\s+{method_name}\s*\([^)]*\)\s+async\*?\s*\{{',
            re.DOTALL,
        )
        method_match = method_pattern.search(ctx.class_content)

        if not method_match:
            continue

        method_start = method_match.end()
        method_end = find_matching_brace(ctx.class_content, method_start)
        method_body = ctx.class_content[method_start:method_end]

        has_widget_mounted = re.search(r'if\s*\(\s*!mounted\s*\)', method_body)
        has_ref_mounted = re.search(r'if\s*\(\s*!ref\.mounted\s*\)', method_body)
        has_ref_usage = re.search(r'\bref\.(read|watch|listen)\(', method_body)

        if has_widget_mounted and not has_ref_mounted and has_ref_usage:
            abs_line = ctx.full_content[:ctx.class_start + method_match.start()].count('\n') + 1
            snippet_start = max(0, abs_line - 1)
            snippet_end = min(len(ctx.lines), abs_line + 15)
            snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

            violations.append(Violation(
                file_path=str(ctx.file_path),
                class_name=ctx.class_name,
                violation_type=ViolationType.MOUNTED_VS_REF_MOUNTED_CONFUSION,
                line_number=abs_line,
                context=f"EDUCATIONAL: Method {method_name}() uses 'mounted' but missing 'ref.mounted' checks",
                code_snippet=snippet,
                fix_instructions=f"""EDUCATIONAL: Widget 'mounted' and Riverpod 'ref.mounted' are DIFFERENT

❌ COMMON CONFUSION: Checking 'mounted' but not 'ref.mounted'
   Line {abs_line}: Method {method_name}() has 'if (!mounted)' but uses ref without 'ref.mounted'

   KEY INSIGHT:
   • 'mounted' = Widget is still in the tree (BuildContext valid)
   • 'ref.mounted' = Riverpod provider is still active (ref valid)

   These have DIFFERENT lifecycles! A widget can be mounted while ref is disposed.

✅ PATTERN: For ConsumerStatefulWidget with async methods, check BOTH

CURRENT (INCOMPLETE):
   Future<void> {method_name}() async {{
     if (!mounted) return;  // ✅ Widget check

     await operation();

     if (!mounted) return;  // ✅ Widget check

     final logger = ref.read(myLoggerProvider);  // ❌ Missing ref.mounted check!
     logger.logInfo('Done');
   }}

RECOMMENDED (COMPLETE):
   Future<void> {method_name}() async {{
     // Check BOTH mounted states at entry
     if (!mounted) return;  // Widget check

     final logger = ref.read(myLoggerProvider);  // Safe after widget mounted check
     logger.logInfo('Start');

     await operation();

     // Check BOTH after async gaps
     if (!mounted) return;  // Widget check (for setState safety)

     logger.logInfo('Done');  // Safe - logger captured before await
   }}

NOTE: In ConsumerStatefulWidget:
- Use 'mounted' to protect setState() calls
- Capture ref.read() results BEFORE await (so they survive disposal)
- Don't call ref.read() AFTER await without re-checking mounted

Reference: https://riverpod.dev/docs/whats_new#refmounted
See also: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
            ))

    return violations


# ===========================================================================
# CHECKER 12: check_initstate_field_access
# ===========================================================================

def check_initstate_field_access(ctx: CheckContext) -> List[Violation]:
    """Check for VIOLATION 13: initState field access before caching.

    Detects when initState() (or methods called from it) accesses cached fields
    that are only initialized in build().
    """
    violations: List[Violation] = []

    # Only applies to ConsumerStatefulWidget State classes
    if not re.search(r'extends\s+ConsumerState<', ctx.class_content):
        return violations

    # Find nullable fields with force-unwrap getters
    field_getter_pattern = re.compile(
        r'(\w+)\?\s+(_\w+)\s*;.*?'
        r'\1\s+get\s+(\w+)\s*=>\s*\2!',
        re.DOTALL,
    )

    fields_with_getters: Dict[str, Tuple[str, str]] = {}  # field_name -> (type, getter_name)
    for match in field_getter_pattern.finditer(ctx.class_content):
        field_type = match.group(1)
        field_name = match.group(2)
        getter_name = match.group(3)
        fields_with_getters[field_name] = (field_type, getter_name)

    if not fields_with_getters:
        return violations

    # Find where fields are cached (typically in build)
    field_caching_locations: Dict[str, int] = {}
    for field_name in fields_with_getters.keys():
        caching_pattern = re.compile(rf'{re.escape(field_name)}\s*\?\?=\s*ref\.read\(')
        match = caching_pattern.search(ctx.class_content)
        if match:
            line_num = ctx.class_content[:match.start()].count('\n')
            field_caching_locations[field_name] = line_num

    # Find initState() method
    initstate_pattern = re.compile(r'void\s+initState\s*\(\s*\)\s*\{', re.DOTALL)
    initstate_match = initstate_pattern.search(ctx.class_content)

    if not initstate_match:
        return violations

    initstate_start = initstate_match.end()
    initstate_end = find_matching_brace(ctx.class_content, initstate_start)
    initstate_body = ctx.class_content[initstate_start:initstate_end]

    # Strip comments from initState body
    initstate_body_stripped, _ = strip_comments(initstate_body)

    # Remove addPostFrameCallback blocks from initstate_body
    initstate_body_no_callbacks = initstate_body_stripped
    callback_pattern = re.compile(r'addPostFrameCallback\s*\([^)]*\)\s*\{', re.DOTALL)
    callback_match = callback_pattern.search(initstate_body_no_callbacks)
    if callback_match:
        cb_start = callback_match.end()
        cb_end = find_matching_brace(initstate_body_no_callbacks, cb_start)
        initstate_body_no_callbacks = (
            initstate_body_no_callbacks[:callback_match.start()]
            + initstate_body_no_callbacks[cb_end + 1:]
        )

    # Find methods called from initState (excluding callbacks)
    method_call_pattern = re.compile(r'(?:await\s+)?([_\w]+)\s*\(')
    called_methods: Set[str] = set()
    for match in method_call_pattern.finditer(initstate_body_no_callbacks):
        method_name = match.group(1)
        if method_name not in ['super', 'setState', 'addPostFrameCallback', 'addListener', 'initState']:
            called_methods.add(method_name)

    # Check each field
    for field_name, (field_type, getter_name) in fields_with_getters.items():
        if field_name not in field_caching_locations:
            continue

        caching_line = field_caching_locations[field_name]

        # Check if getter is used directly in initState (excluding callbacks)
        if re.search(rf'\b{getter_name}\b', initstate_body_no_callbacks):
            abs_line = ctx.full_content[:ctx.class_start + initstate_match.start()].count('\n') + 1
            snippet_start = max(0, abs_line - 1)
            snippet_end = min(len(ctx.lines), abs_line + 20)
            snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

            violations.append(Violation(
                file_path=str(ctx.file_path),
                class_name=ctx.class_name,
                violation_type=ViolationType.INITSTATE_FIELD_ACCESS_BEFORE_CACHING,
                line_number=abs_line,
                context=f"initState() directly accesses {getter_name} before {field_name} is cached in build()",
                code_snippet=snippet,
                fix_instructions=f"""CRITICAL: Widget lifecycle timing bug - Null pointer exception risk

❌ VIOLATION: initState() accesses {getter_name} but {field_name} only cached in build()
   Line {abs_line}: initState() uses {getter_name}
   Field {field_name} is cached at line {ctx.class_start + caching_line} (in build method)

   EXECUTION ORDER:
   1. initState() runs → accesses {getter_name} getter
   2. Getter returns {field_name}! (force unwrap)
   3. CRASH: {field_name} is null (not cached yet)
   4. build() runs → caches {field_name} (too late)

✅ FIX: Move getter access to addPostFrameCallback()

CURRENT (CRASHES):
   @override
   void initState() {{
     super.initState();
     _someMethod();  // Uses {getter_name} internally
   }}

   void _someMethod() async {{
     await {getter_name}.doSomething();  // CRASH! null pointer
   }}

   @override
   Widget build(BuildContext context, WidgetRef ref) {{
     {field_name} ??= ref.read(...);  // Too late
   }}

FIXED (SAFE):
   @override
   void initState() {{
     super.initState();

     // Defer to after first frame (when build() has run)
     WidgetsBinding.instance.addPostFrameCallback((_) {{
       if (mounted) {{
         _someMethod();  // Safe - {field_name} is cached in build()
       }}
     }});
   }}

   @override
   Widget build(BuildContext context, WidgetRef ref) {{
     {field_name} ??= ref.read(...);  // Runs BEFORE callback
     return YourWidget();
   }}

ALTERNATIVE (Eager caching):
   @override
   void initState() {{
     super.initState();

     // Cache immediately in initState (no ref operations allowed here)
     // NOTE: Only use this if the dependency doesn't require ref operations
     WidgetsBinding.instance.addPostFrameCallback((_) {{
       if (mounted) {{
         {field_name} = ref.read(...);  // Cache before using
         _someMethod();  // Now safe
       }}
     }});
   }}

PRODUCTION IMPACT:
This pattern caused critical production failures:
- Sentry Issue: Chat access failures ("You are not a member")
- Root cause: Database queries failing due to null backendService
- Users unable to access revenue-critical features

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md
See also: Flutter widget lifecycle documentation""",
            ))
            continue

        # Check methods called from initState to see if they use the getter
        for method_name in called_methods:
            method_pattern = re.compile(
                rf'(?:Future<[^>]*>|void)\s+{method_name}\s*\([^)]*\)\s+(?:async\s+)?\{{',
                re.DOTALL,
            )
            method_match = method_pattern.search(ctx.class_content)

            if not method_match:
                continue

            method_start = method_match.end()
            method_end = find_matching_brace(ctx.class_content, method_start)
            method_body = ctx.class_content[method_start:method_end]

            if re.search(rf'\b{getter_name}\b', method_body):
                abs_line = ctx.full_content[:ctx.class_start + initstate_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(ctx.lines), abs_line + 20)
                snippet = '\n'.join(f"  {i + 1:4d} | {ctx.lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(ctx.file_path),
                    class_name=ctx.class_name,
                    violation_type=ViolationType.INITSTATE_FIELD_ACCESS_BEFORE_CACHING,
                    line_number=abs_line,
                    context=f"initState() calls {method_name}() which accesses {getter_name} before {field_name} is cached",
                    code_snippet=snippet,
                    fix_instructions=f"""CRITICAL: Widget lifecycle timing bug - Null pointer exception risk

❌ VIOLATION: initState() → {method_name}() → accesses {getter_name} before caching
   Line {abs_line}: initState() calls {method_name}()
   Method {method_name}() uses {getter_name} getter
   Field {field_name} is only cached at line {ctx.class_start + caching_line} (in build method)

   CALL CHAIN:
   1. initState() runs
   2. Calls {method_name}()
   3. {method_name}() accesses {getter_name}
   4. Getter returns {field_name}! (force unwrap)
   5. CRASH: {field_name} is null (build() hasn't run yet)

✅ FIX: Move {method_name}() call to addPostFrameCallback()

CURRENT (CRASHES):
   @override
   void initState() {{
     super.initState();
     {method_name}();  // ← Called BEFORE build()
   }}

   void {method_name}() async {{
     await {getter_name}.doSomething();  // ← CRASH! null pointer
   }}

   @override
   Widget build(BuildContext context, WidgetRef ref) {{
     {field_name} ??= ref.read(...);  // ← Too late!
   }}

FIXED (SAFE):
   @override
   void initState() {{
     super.initState();

     // Defer to after first frame (when build() has run)
     WidgetsBinding.instance.addPostFrameCallback((_) {{
       if (mounted) {{
         {method_name}();  // Safe - {field_name} cached in build()
       }}
     }});
   }}

   @override
   Widget build(BuildContext context, WidgetRef ref) {{
     {field_name} ??= ref.read(...);  // Runs BEFORE callback
     return YourWidget();
   }}

PRODUCTION CRASH EXAMPLE:
File: lib/presentation/features/game/views/game_chat_view.dart
- initState() called _getOrCreateRoom()
- _getOrCreateRoom() used backendService.client
- backendService getter returned _backendService!
- _backendService was null (cached in build())
- Query failed silently → "You are not a member" error shown

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md""",
                ))

    return violations
