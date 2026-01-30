#!/usr/bin/env python3
"""
Riverpod 3.0 Safety Scanner
Comprehensive static analysis tool for Flutter/Dart projects using Riverpod 3.0+

Author: Steven Day
Company: DayLight Creative Technologies
License: MIT
Version: 1.3.0

Detects ALL forbidden patterns that violate Riverpod 3.0 async safety standards.

SCANS THREE CLASS TYPES:
- Riverpod provider classes (extends _$ClassName)
- ConsumerStatefulWidget State classes (extends ConsumerState<T>)
- ConsumerWidget classes (extends ConsumerWidget)

FORBIDDEN PATTERNS DETECTED (15 TYPES):

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
- Sentry crash correlation (#7055596134)
- Comment stripping (prevents false positives)

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

import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass
from enum import Enum


class ViolationType(Enum):
    """Types of Riverpod 3.0 violations"""
    FIELD_CACHING = "field_caching"
    LAZY_GETTER = "lazy_getter"
    ASYNC_GETTER = "async_getter"
    REF_READ_BEFORE_MOUNTED = "ref_read_before_mounted"
    MISSING_MOUNTED_AFTER_AWAIT = "missing_mounted_after_await"
    MISSING_MOUNTED_IN_CATCH = "missing_mounted_in_catch"
    NULLABLE_FIELD_ACCESS = "nullable_field_access"
    REF_IN_LIFECYCLE_CALLBACK = "ref_in_lifecycle_callback"
    REF_LISTEN_OUTSIDE_BUILD = "ref_listen_outside_build"
    REF_WATCH_OUTSIDE_BUILD = "ref_watch_outside_build"
    WIDGET_LIFECYCLE_UNSAFE_REF = "widget_lifecycle_unsafe_ref"
    DEFERRED_CALLBACK_UNSAFE_REF = "deferred_callback_unsafe_ref"
    UNTYPED_LAZY_GETTER = "untyped_lazy_getter"
    MOUNTED_VS_REF_MOUNTED_CONFUSION = "mounted_vs_ref_mounted_confusion"
    INITSTATE_FIELD_ACCESS_BEFORE_CACHING = "initstate_field_access_before_caching"
    SYNC_METHOD_WITHOUT_MOUNTED_CHECK = "sync_method_without_mounted_check"


@dataclass
class Violation:
    """Represents a detected violation"""
    file_path: str
    class_name: str
    violation_type: ViolationType
    line_number: int
    context: str
    code_snippet: str
    fix_instructions: str


class RiverpodScanner:
    """Comprehensive Riverpod 3.0 compliance scanner with cross-file analysis"""

    def __init__(self, verbose: bool = False):
        self.violations: List[Violation] = []
        self.verbose = verbose
        # Cross-file analysis database
        self.methods_using_ref: Dict[str, Set[str]] = {}  # class_name -> set of method names
        self.class_to_file: Dict[str, Path] = {}  # class_name -> file path
        self.provider_to_class: Dict[str, str] = {}  # provider_name -> class_name

        # Call-graph analysis database for async context detection
        self.all_methods: Dict[Tuple[str, str, str], Dict] = {}  # (file, class, method) -> {has_ref_read, has_mounted_check, is_async}
        self.methods_called_from_async: Set[Tuple[str, str, str]] = set()  # Set of (file, class, method) called from async contexts

    @staticmethod
    def _strip_comments(content: str) -> Tuple[str, Dict[int, int]]:
        """
        Strip comments from Dart code to avoid false positives.

        Returns:
            Tuple of (stripped_content, position_map)
            position_map: maps positions in stripped content to original content
        """
        original_content = content
        position_map = {}

        # Build position mapping: stripped_pos -> original_pos
        stripped_content = []
        original_pos = 0
        stripped_pos = 0

        i = 0
        while i < len(content):
            # Check for // comment
            if i < len(content) - 1 and content[i:i+2] == '//':
                # Skip until newline
                while i < len(content) and content[i] != '\n':
                    i += 1
                # Keep the newline
                if i < len(content):
                    stripped_content.append('\n')
                    position_map[stripped_pos] = i
                    stripped_pos += 1
                    i += 1
                continue

            # Check for /* */ comment
            if i < len(content) - 1 and content[i:i+2] == '/*':
                # Skip until */
                i += 2
                while i < len(content) - 1:
                    if content[i:i+2] == '*/':
                        i += 2
                        break
                    # Preserve newlines to keep line numbers accurate
                    if content[i] == '\n':
                        stripped_content.append('\n')
                        position_map[stripped_pos] = i
                        stripped_pos += 1
                    i += 1
                continue

            # Regular character
            stripped_content.append(content[i])
            position_map[stripped_pos] = i
            stripped_pos += 1
            i += 1

        return ''.join(stripped_content), position_map

    def _build_method_database(self, file_path: Path) -> None:
        """PASS 1.5: Build complete database of all methods with metadata

        Stores: (file, class, method) -> {
            has_ref_read: bool,
            has_mounted_check: bool,
            is_async: bool,
            is_lifecycle_method: bool,
            method_body: str
        }
        """
        try:
            content = file_path.read_text()
        except Exception:
            return

        # Framework lifecycle methods
        framework_lifecycle_methods = {
            'initState', 'dispose', 'didUpdateWidget', 'didChangeDependencies',
            'deactivate', 'reassemble', 'build'
        }

        # Find all classes (Riverpod providers and ConsumerState)
        provider_pattern = re.compile(r'class\s+(\w+)\s+extends\s+_\$(\w+)')
        consumer_state_pattern = re.compile(r'class\s+(\w+)\s+extends\s+ConsumerState<(\w+)>')

        for pattern, is_consumer in [(provider_pattern, False), (consumer_state_pattern, True)]:
            for class_match in pattern.finditer(content):
                class_name = class_match.group(1)
                class_start = class_match.start()
                class_end = self._find_class_end(content, class_start)
                class_content = content[class_start:class_end]

                # Determine mounted pattern for this class type
                mounted_pattern = r'if\s*\(\s*!mounted\s*\)\s*return' if is_consumer else r'if\s*\(\s*!ref\.mounted\s*\)\s*return'

                # Find all methods (both async and sync)
                method_pattern = re.compile(
                    r'(?:Future<[^>]+>|Stream<[^>]+>|void|bool|String|int|double|num|\w+\?)\s+(\w+)\s*\([^)]*\)\s*(?:async\s*)?\{',
                    re.DOTALL
                )

                for method_match in method_pattern.finditer(class_content):
                    method_name = method_match.group(1)

                    # Skip getters (different pattern)
                    if 'get ' in content[max(0, class_start + method_match.start() - 20):class_start + method_match.start() + 20]:
                        continue

                    method_start = method_match.end()
                    method_end = self._find_method_end(class_content, method_start)
                    method_body = class_content[method_start:method_end]

                    # Check metadata
                    full_signature = class_content[max(0, method_match.start() - 50):method_match.end() + 20]
                    is_async = bool(re.search(r'\basync\b', full_signature))
                    has_ref_read = bool(re.search(r'ref\.read\(', method_body))

                    # Check if mounted appears BEFORE first ref.read()
                    has_mounted_check = False
                    if has_ref_read:
                        ref_read_matches = list(re.finditer(r'ref\.read\(', method_body))
                        if ref_read_matches:
                            first_ref_read_pos = ref_read_matches[0].start()
                            before_first_ref_read = method_body[:first_ref_read_pos]
                            has_mounted_check = bool(re.search(mounted_pattern, before_first_ref_read))

                    is_lifecycle = method_name in framework_lifecycle_methods

                    # Store in database with composite key
                    key = (str(file_path), class_name, method_name)
                    self.all_methods[key] = {
                        'has_ref_read': has_ref_read,
                        'has_mounted_check': has_mounted_check,
                        'is_async': is_async,
                        'is_lifecycle_method': is_lifecycle,
                        'method_body': method_body,
                        'is_consumer_state': is_consumer
                    }

    def _trace_async_callbacks(self, file_path: Path) -> None:
        """PASS 2: Trace which methods are called from async contexts

        Detects:
        1. Methods called directly in async methods (after await)
        2. Methods called in async callback parameters (onCompletion:, builder:, etc.)
        3. Methods called in stream.listen() callbacks
        4. Methods called in Timer/Future.delayed callbacks
        5. Methods called in addPostFrameCallback

        Builds: self.methods_called_from_async set
        """
        try:
            content = file_path.read_text()
        except Exception:
            return

        # Find all classes
        provider_pattern = re.compile(r'class\s+(\w+)\s+extends\s+_\$(\w+)')
        consumer_state_pattern = re.compile(r'class\s+(\w+)\s+extends\s+ConsumerState<(\w+)>')

        for pattern in [provider_pattern, consumer_state_pattern]:
            for class_match in pattern.finditer(content):
                class_name = class_match.group(1)
                class_start = class_match.start()
                class_end = self._find_class_end(content, class_start)
                class_content = content[class_start:class_end]

                # Find all async methods and callbacks
                self._trace_async_method_calls(file_path, class_name, class_content)
                self._trace_callback_parameter_calls(file_path, class_name, class_content)
                self._trace_stream_listen_calls(file_path, class_name, class_content)
                self._trace_deferred_calls(file_path, class_name, class_content)

    def _trace_async_method_calls(self, file_path: Path, class_name: str, class_content: str) -> None:
        """Find all method calls inside async methods (after await statements)"""
        # Get full file content for variable resolution
        try:
            full_file_content = file_path.read_text()
        except Exception:
            return

        # Find all async methods (including FutureOr for Riverpod build methods)
        async_pattern = re.compile(r'(?:Future<[^>]+>|FutureOr<[^>]+>|Stream<[^>]+>)\s+(\w+)\s*\([^)]*\)\s*async\s*\{', re.DOTALL)

        for async_match in async_pattern.finditer(class_content):
            method_name = async_match.group(1)
            method_start = async_match.end()
            method_end = self._find_method_end(class_content, method_start)
            method_body = class_content[method_start:method_end]

            # Find all 'await' statements
            await_positions = [m.start() for m in re.finditer(r'\bawait\s+', method_body)]

            # For each await, find method calls that come AFTER it
            for await_pos in await_positions:
                # Get code after this await
                after_await = method_body[await_pos:]

                # Find next mounted check (if any)
                mounted_check_match = re.search(r'if\s*\(\s*!(?:ref\.)?mounted\s*\)\s*return', after_await)

                # Find all method calls between await and next mounted check (or end of after_await)
                search_end = mounted_check_match.start() if mounted_check_match else len(after_await)
                danger_zone = after_await[:search_end]

                # Find method calls in danger zone: methodName() or object.methodName()
                method_call_pattern = re.compile(r'(?:^|[^\w])(\w+)\.(\w+)\(|(?:^|[^\w])(\w+)\(')

                for call_match in method_call_pattern.finditer(danger_zone):
                    called_method = call_match.group(2) if call_match.group(2) else call_match.group(3)
                    object_name = call_match.group(1) if call_match.group(2) else None

                    if called_method and not called_method in ['read', 'watch', 'listen', 'mounted', 'setState']:
                        # Try to resolve variable to class if this is object.method() pattern
                        if object_name:
                            # Use correct signature: (variable_name, class_content, full_content)
                            resolved_class = self._resolve_variable_to_class(object_name, class_content, full_file_content)
                            if resolved_class:
                                # Try to find method in resolved class across all files
                                for (f, c, m), data in self.all_methods.items():
                                    if c == resolved_class and m == called_method:
                                        self.methods_called_from_async.add((f, c, m))
                                        break
                        else:
                            # Standalone method call - try in current class
                            key = (str(file_path), class_name, called_method)
                            if key in self.all_methods:
                                self.methods_called_from_async.add(key)

    def _trace_callback_parameter_calls(self, file_path: Path, class_name: str, class_content: str) -> None:
        """Find methods called inside callback parameters (onCompletion:, builder:, etc.)"""
        # Get full file content for variable resolution
        try:
            full_file_content = file_path.read_text()
        except Exception:
            return

        # Pattern: parameterName: (args) {
        # NOTE: Use brace counting to handle nested callbacks properly
        callback_start_pattern = re.compile(r'(\w+):\s*\([^)]*\)\s*(?:async\s*)?\{', re.DOTALL)

        for callback_match in callback_start_pattern.finditer(class_content):
            param_name = callback_match.group(1)

            # Find the matching closing brace using brace counting
            brace_start = callback_match.end() - 1  # Position of opening {
            callback_end = self._find_method_end(class_content, callback_match.end())
            callback_body = class_content[callback_match.end():callback_end]

            # Common async callback parameters
            async_callback_params = {
                'onCompletion', 'onComplete', 'onSuccess', 'onFailure', 'onError',
                'builder', 'onPressed', 'onTap', 'onLongPress', 'onChanged',
                'onSubmitted', 'onFieldSubmitted', 'onSaved', 'listener',
                'requiresGameCompletion', 'requiresStart', 'requiresResume'
            }

            # Check if this callback is passed to an awaited method
            # Look backwards from callback to find if there's an 'await' nearby
            callback_pos = callback_match.start()
            before_callback = class_content[max(0, callback_pos - 200):callback_pos]

            # If 'await' appears within 200 chars before callback, this is async context
            has_await_before = bool(re.search(r'\bawait\s+\w+', before_callback))

            # Also check if callback contains await (callback is async)
            has_await_inside = bool(re.search(r'\bawait\s+', callback_body))

            if has_await_before or has_await_inside or param_name in async_callback_params:
                # Find all method calls in callback body
                method_call_pattern = re.compile(r'(?:^|[^\w])(\w+)\.(\w+)\(|(?:^|[^\w])(\w+)\(')

                for call_match in method_call_pattern.finditer(callback_body):
                    called_method = call_match.group(2) if call_match.group(2) else call_match.group(3)
                    object_name = call_match.group(1) if call_match.group(2) else None

                    if called_method and not called_method in ['read', 'watch', 'listen', 'mounted', 'setState']:
                        # Try to resolve variable to class if this is object.method() pattern
                        if object_name:
                            # Use correct signature: (variable_name, class_content, full_content)
                            resolved_class = self._resolve_variable_to_class(object_name, class_content, full_file_content)

                            if resolved_class:
                                # Try to find method in resolved class
                                for (f, c, m), data in self.all_methods.items():
                                    if c == resolved_class and m == called_method:
                                        self.methods_called_from_async.add((f, c, m))
                                        break
                        else:
                            # Standalone method call - try in current class
                            key = (str(file_path), class_name, called_method)
                            if key in self.all_methods:
                                self.methods_called_from_async.add(key)

    def _trace_stream_listen_calls(self, file_path: Path, class_name: str, class_content: str) -> None:
        """Find methods called inside .listen() callbacks"""
        # Get full file content for variable resolution
        try:
            full_file_content = file_path.read_text()
        except Exception:
            return

        # Pattern: stream.listen((event) { method(); })
        listen_pattern = re.compile(r'\.listen\s*\(\s*\([^)]*\)\s*\{([^}]+)\}', re.DOTALL)

        for listen_match in listen_pattern.finditer(class_content):
            callback_body = listen_match.group(1)

            # Find all method calls in listen callback
            method_call_pattern = re.compile(r'(?:^|[^\w])(\w+)\.(\w+)\(|(?:^|[^\w])(\w+)\(')

            for call_match in method_call_pattern.finditer(callback_body):
                called_method = call_match.group(2) if call_match.group(2) else call_match.group(3)
                object_name = call_match.group(1) if call_match.group(2) else None

                if called_method and not called_method in ['read', 'watch', 'listen', 'mounted', 'setState']:
                    # Try to resolve variable to class if this is object.method() pattern
                    if object_name:
                        # Use correct signature
                        resolved_class = self._resolve_variable_to_class(object_name, class_content, full_file_content)
                        if resolved_class:
                            for (f, c, m), data in self.all_methods.items():
                                if c == resolved_class and m == called_method:
                                    self.methods_called_from_async.add((f, c, m))
                                    break
                    else:
                        # Standalone method call
                        key = (str(file_path), class_name, called_method)
                        if key in self.all_methods:
                            self.methods_called_from_async.add(key)

    def _trace_deferred_calls(self, file_path: Path, class_name: str, class_content: str) -> None:
        """Find methods called from Timer, Future.delayed, addPostFrameCallback"""
        # Get full file content for variable resolution
        try:
            full_file_content = file_path.read_text()
        except Exception:
            return

        # Pattern 1: Timer(duration, () { method(); })
        timer_pattern = re.compile(r'Timer(?:\.periodic)?\s*\([^,]+,\s*\([^)]*\)\s*\{([^}]+)\}', re.DOTALL)

        # Pattern 2: Future.delayed(duration, () { method(); })
        delayed_pattern = re.compile(r'Future\.delayed\s*\([^,]+,\s*\([^)]*\)\s*\{([^}]+)\}', re.DOTALL)

        # Pattern 3: addPostFrameCallback((_) { method(); })
        postframe_pattern = re.compile(r'addPostFrameCallback\s*\(\s*\([^)]*\)\s*\{([^}]+)\}', re.DOTALL)

        for pattern in [timer_pattern, delayed_pattern, postframe_pattern]:
            for match in pattern.finditer(class_content):
                callback_body = match.group(1)

                # Find all method calls
                method_call_pattern = re.compile(r'(?:^|[^\w])(\w+)\.(\w+)\(|(?:^|[^\w])(\w+)\(')

                for call_match in method_call_pattern.finditer(callback_body):
                    called_method = call_match.group(2) if call_match.group(2) else call_match.group(3)
                    object_name = call_match.group(1) if call_match.group(2) else None

                    if called_method and not called_method in ['read', 'watch', 'listen', 'mounted', 'setState']:
                        # Try to resolve variable to class if this is object.method() pattern
                        if object_name:
                            # Use correct signature
                            resolved_class = self._resolve_variable_to_class(object_name, class_content, full_file_content)
                            if resolved_class:
                                for (f, c, m), data in self.all_methods.items():
                                    if c == resolved_class and m == called_method:
                                        self.methods_called_from_async.add((f, c, m))
                                        break
                        else:
                            # Standalone method call
                            key = (str(file_path), class_name, called_method)
                            if key in self.all_methods:
                                self.methods_called_from_async.add(key)

    def _propagate_async_context_transitively(self) -> None:
        """PASS 2.5: Propagate async context transitively through call graph

        If method A calls method B, and B is in async context,
        then A is also in async context (recursively).

        Uses fixed-point iteration until no new methods are added.
        """
        iteration = 0
        while True:
            iteration += 1
            initial_count = len(self.methods_called_from_async)

            if self.verbose:
                print(f"   🔄 Iteration {iteration}: {initial_count} methods in async context")

            # For each method in all_methods
            for method_key, method_data in self.all_methods.items():
                # Skip if already marked as async context
                if method_key in self.methods_called_from_async:
                    continue

                method_body = method_data['method_body']
                file_path, class_name, method_name = method_key

                # Find all method calls in this method's body
                method_call_pattern = re.compile(r'(?:^|[^\w])(\w+)\.(\w+)\(|(?:^|[^\w])(\w+)\(')

                for call_match in method_call_pattern.finditer(method_body):
                    called_method = call_match.group(2) if call_match.group(2) else call_match.group(3)

                    if not called_method or called_method in ['read', 'watch', 'listen', 'mounted', 'setState']:
                        continue

                    # Check if called method is in async context
                    # Try same class first
                    called_key = (file_path, class_name, called_method)

                    if called_key in self.methods_called_from_async:
                        # This method calls a method that's in async context
                        # Therefore this method is also in async context
                        self.methods_called_from_async.add(method_key)
                        break

            # Fixed-point reached?
            if len(self.methods_called_from_async) == initial_count:
                if self.verbose:
                    print(f"   ✅ Fixed-point reached after {iteration} iterations")
                break

            if iteration > 100:  # Safety limit
                if self.verbose:
                    print(f"   ⚠️  Stopped after 100 iterations")
                break

    def scan_file(self, file_path: Path) -> List[Violation]:
        """Scan a single Dart file for all Riverpod violations"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
        except Exception as e:
            print(f"Error reading {file_path}: {e}", file=sys.stderr)
            return []

        violations = []

        # Pattern 1: Find Riverpod provider classes (classes extending _$ClassName)
        provider_pattern = re.compile(r'class\s+(\w+)\s+extends\s+_\$(\w+)')

        # Pattern 2: Find ConsumerStatefulWidget State classes (extends ConsumerState<T>)
        consumer_state_pattern = re.compile(r'class\s+(\w+)\s+extends\s+ConsumerState<(\w+)>')

        for provider_match in provider_pattern.finditer(content):
            class_name = provider_match.group(1)
            class_start = provider_match.start()
            class_end = self._find_class_end(content, class_start)
            class_content = content[class_start:class_end]
            class_lines = class_content.split('\n')

            # Check if class has async methods
            async_methods = self._find_async_methods(class_content)
            has_async_methods = len(async_methods) > 0

            if self.verbose:
                print(f"\n🔍 Analyzing {class_name} (Riverpod Provider):")
                print(f"   Async methods: {len(async_methods)}")
                if async_methods:
                    print(f"   Methods: {', '.join(async_methods)}")

            # VIOLATION 1-3: Field caching patterns
            violations.extend(self._check_field_caching(
                file_path, class_name, class_content, content, class_start,
                lines, has_async_methods, async_methods
            ))

            # VIOLATION 4-6: Async method ref safety
            if has_async_methods:
                violations.extend(self._check_async_method_safety(
                    file_path, class_name, class_content, content, class_start,
                    lines, async_methods, is_consumer_state=False
                ))

            # VIOLATION 10: Sync methods without mounted check (called from async callbacks)
            violations.extend(self._check_sync_methods_without_mounted(
                file_path, class_name, class_content, content, class_start,
                lines, is_consumer_state=False
            ))

            # VIOLATION 7: Nullable field misuse
            violations.extend(self._check_nullable_field_misuse(
                file_path, class_name, class_content, content, class_start, lines
            ))

            # VIOLATION 8: ref operations inside lifecycle callbacks
            violations.extend(self._check_ref_in_lifecycle_callbacks(
                file_path, class_name, class_content, content, class_start, lines
            ))

            # VIOLATION 9-10: ref.listen/ref.watch outside build method
            violations.extend(self._check_ref_operations_outside_build(
                file_path, class_name, class_content, content, class_start, lines
            ))

        # Pattern 2: Find ConsumerStatefulWidget State classes (extends ConsumerState<T>)
        consumer_state_pattern = re.compile(r'class\s+(\w+)\s+extends\s+ConsumerState<(\w+)>')

        for consumer_match in consumer_state_pattern.finditer(content):
            class_name = consumer_match.group(1)
            widget_name = consumer_match.group(2)
            class_start = consumer_match.start()
            class_end = self._find_class_end(content, class_start)
            class_content = content[class_start:class_end]
            class_lines = class_content.split('\n')

            # Check if class has async methods
            async_methods = self._find_async_methods(class_content)
            has_async_methods = len(async_methods) > 0

            if self.verbose:
                print(f"\n🔍 Analyzing {class_name} (ConsumerState<{widget_name}>):")
                print(f"   Async methods: {len(async_methods)}")
                if async_methods:
                    print(f"   Methods: {', '.join(async_methods)}")

            # VIOLATION 1-3: Field caching patterns
            violations.extend(self._check_field_caching(
                file_path, class_name, class_content, content, class_start,
                lines, has_async_methods, async_methods, is_consumer_state=True
            ))

            # VIOLATION 4-6: Async method ref safety
            if has_async_methods:
                violations.extend(self._check_async_method_safety(
                    file_path, class_name, class_content, content, class_start,
                    lines, async_methods, is_consumer_state=True
                ))

            # VIOLATION 10: Sync methods without mounted check (called from async callbacks)
            violations.extend(self._check_sync_methods_without_mounted(
                file_path, class_name, class_content, content, class_start,
                lines, is_consumer_state=True
            ))

            # VIOLATION 7: Nullable field misuse
            violations.extend(self._check_nullable_field_misuse(
                file_path, class_name, class_content, content, class_start, lines
            ))

            # VIOLATION 8: ref operations inside lifecycle callbacks
            violations.extend(self._check_ref_in_lifecycle_callbacks(
                file_path, class_name, class_content, content, class_start, lines
            ))

            # VIOLATION 9-10: ref.listen/ref.watch outside build method
            violations.extend(self._check_ref_operations_outside_build(
                file_path, class_name, class_content, content, class_start, lines
            ))

            # VIOLATION 11-14: ConsumerState-specific checks (widget lifecycle, timers, etc.)
            violations.extend(self._check_widget_lifecycle_unsafe_ref(
                file_path, class_name, class_content, content, class_start, lines
            ))

            violations.extend(self._check_deferred_callback_unsafe_ref(
                file_path, class_name, class_content, content, class_start, lines
            ))

            violations.extend(self._check_async_event_handler_callbacks(
                file_path, class_name, class_content, content, class_start, lines
            ))

            violations.extend(self._check_untyped_lazy_getters(
                file_path, class_name, class_content, content, class_start, lines, has_async_methods
            ))

            # VIOLATION 13: initState field access before caching
            violations.extend(self._check_initstate_field_access_before_caching(
                file_path, class_name, class_content, content, class_start, lines
            ))

            # NOTE: Do NOT check mounted_confusion for ConsumerStatefulWidget
            # WidgetRef does NOT have a .mounted property - only 'mounted' from State is valid
            # The confusion check only applies to @riverpod provider classes with Ref

        # Pattern 3: Find ConsumerWidget classes (extends ConsumerWidget)
        consumer_widget_pattern = re.compile(r'class\s+(\w+)\s+extends\s+ConsumerWidget')

        for consumer_match in consumer_widget_pattern.finditer(content):
            class_name = consumer_match.group(1)
            class_start = consumer_match.start()
            class_end = self._find_class_end(content, class_start)
            class_content = content[class_start:class_end]
            class_lines = class_content.split('\n')

            if self.verbose:
                print(f"\n🔍 Analyzing {class_name} (ConsumerWidget):")

            # VIOLATION 15: Async event handler callbacks without mounted checks
            # This is the most common violation in ConsumerWidget - async callbacks in build
            violations.extend(self._check_async_event_handler_callbacks(
                file_path, class_name, class_content, content, class_start, lines
            ))

            # Also check deferred callbacks (Timer, Future.delayed, etc.)
            violations.extend(self._check_deferred_callback_unsafe_ref(
                file_path, class_name, class_content, content, class_start, lines
            ))

        return violations

    def _find_class_end(self, content: str, class_start: int) -> int:
        """Find the end of a class definition"""
        brace_count = 0
        in_class = False

        for i in range(class_start, len(content)):
            if content[i] == '{':
                brace_count += 1
                in_class = True
            elif content[i] == '}':
                brace_count -= 1
                if in_class and brace_count == 0:
                    return i + 1

        return len(content)

    def _find_async_methods(self, class_content: str) -> List[str]:
        """Find all async methods in a class, including stream generators (async*)"""
        # CRITICAL FIX: Handle nested parentheses in function type parameters
        # Example: Future<void> startClock({required void Function() onApproved}) async
        #
        # Strategy: Use non-greedy match followed by specific ' async' keyword detection
        # This avoids issues with nested () in parameter lists

        # Pattern 1: Future<T> methodName(...) async
        # UPDATED: Use .+? to handle nested generics like Future<Either<A, List<B>>>
        # Non-greedy match continues until it finds "> methodName(...) async"
        async_future_pattern = re.compile(r'Future<.+?>\s+(\w+)\s*\(.*?\)\s+async(?:\s|{)', re.DOTALL)

        # Pattern 2: FutureOr<T> methodName(...) async (used by Riverpod build methods)
        async_futureor_pattern = re.compile(r'FutureOr<.+?>\s+(\w+)\s*\(.*?\)\s+async(?:\s|{)', re.DOTALL)

        # Pattern 3: Stream<T> methodName(...) async*
        async_stream_pattern = re.compile(r'Stream<.+?>\s+(\w+)\s*\(.*?\)\s+async\*(?:\s|{)', re.DOTALL)

        methods = []
        methods.extend([match.group(1) for match in async_future_pattern.finditer(class_content)])
        methods.extend([match.group(1) for match in async_futureor_pattern.finditer(class_content)])
        methods.extend([match.group(1) for match in async_stream_pattern.finditer(class_content)])
        return methods

    def _find_sync_methods_with_ref_read(self, class_content: str, is_consumer_state: bool = False) -> List[Tuple[str, int, str]]:
        """Find sync methods (non-async) that use ref.read() without mounted checks

        Args:
            class_content: The class source code
            is_consumer_state: True if this is a ConsumerStatefulWidget State class

        Returns: List of tuples (method_name, line_offset, method_body)

        CRITICAL: These methods are safe when called synchronously but crash when
        called from async callbacks (onCompletion:, builder:, etc.) because the
        provider can be disposed during the await gap.
        """
        results = []

        # Determine which mounted pattern to check based on class type
        if is_consumer_state:
            # ConsumerStatefulWidget uses widget's 'mounted' property
            mounted_pattern = r'if\s*\(\s*!mounted\s*\)\s*return'
        else:
            # Riverpod provider classes use 'ref.mounted'
            mounted_pattern = r'if\s*\(\s*!ref\.mounted\s*\)\s*return'

        # Find all methods that are NOT async but contain ref.read()
        # Pattern: void/bool/String/etc methodName(...) { ... ref.read() ... }
        # Excludes: async methods, getters (handled by lazy getter check)
        method_pattern = re.compile(
            r'(?:void|bool|String|int|double|num|\w+\?)\s+(\w+)\s*\([^)]*\)\s*\{',
            re.DOTALL
        )

        # Flutter framework lifecycle methods - these are called synchronously by framework
        # and widget lifecycle is separate from provider lifecycle
        framework_lifecycle_methods = {
            'initState', 'dispose', 'didUpdateWidget', 'didChangeDependencies',
            'deactivate', 'reassemble', 'build'
        }

        for method_match in method_pattern.finditer(class_content):
            method_name = method_match.group(1)
            method_start = method_match.end()
            method_end = self._find_method_end(class_content, method_start)
            method_body = class_content[method_start:method_end]

            # Skip framework lifecycle methods - these are called synchronously by Flutter
            if method_name in framework_lifecycle_methods:
                continue

            # Skip if this is actually an async method (has 'async' keyword)
            full_signature = class_content[max(0, method_match.start() - 50):method_match.end() + 20]
            if re.search(r'\basync\b', full_signature):
                continue

            # Check if method contains ref.read()
            ref_read_matches = list(re.finditer(r'ref\.read\(', method_body))
            if not ref_read_matches:
                continue

            # Find position of first ref.read()
            first_ref_read_pos = ref_read_matches[0].start()

            # Check if mounted check appears BEFORE first ref.read()
            # Search entire method body up to first ref.read()
            # Use appropriate mounted pattern for class type
            before_first_ref_read = method_body[:first_ref_read_pos]
            has_mounted_check = re.search(mounted_pattern, before_first_ref_read)

            if not has_mounted_check:
                # Calculate line offset
                line_offset = class_content[:method_match.start()].count('\n')
                results.append((method_name, line_offset, method_body))

        return results

    def _check_field_caching(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str],
        has_async_methods: bool, async_methods: List[str], is_consumer_state: bool = False
    ) -> List[Violation]:
        """Check for all field caching patterns (VIOLATIONS 1-3)"""
        violations = []

        # CHECK DIRECT LAZY GETTERS (no field): TypeName get name => ref.read(...)
        # This pattern is DEADLY in async classes - common in ConsumerStatefulWidget
        if has_async_methods:
            direct_lazy_getter_pattern = re.compile(
                r'(\w+)\s+get\s+(\w+)\s*=>\s*ref\.read\([^)]+\);'
            )

            for getter_match in direct_lazy_getter_pattern.finditer(class_content):
                getter_type = getter_match.group(1)
                getter_name = getter_match.group(2)
                abs_getter_line = full_content[:class_start + getter_match.start()].count('\n') + 1

                # Extract code snippet
                snippet_start = max(0, abs_getter_line - 1)
                snippet_end = min(len(lines), abs_getter_line + 3)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
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

Applies to all async methods: {', '.join(async_methods)}

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md
Sentry Issue: #7055596134 (iOS production crash)"""
                ))

        # CHECK DYNAMIC LAZY GETTERS (CRITICAL - Common in legacy code)
        # Pattern: dynamic _field; dynamic get field { _field ??= ref.read(...); return _field!; }
        if has_async_methods:
            dynamic_field_pattern = re.compile(r'dynamic\s+(_\w+);')

            for field_match in dynamic_field_pattern.finditer(class_content):
                field_name = field_match.group(1)
                base_name = field_name[1:]  # Remove underscore

                # Check if there's a corresponding dynamic getter
                dynamic_getter_pattern = re.compile(
                    rf'dynamic\s+get\s+{base_name}\s*\{{[^}}]*{field_name}\s*\?\?=\s*ref\.read\(([^)]+)\)',
                    re.DOTALL
                )

                getter_match = dynamic_getter_pattern.search(class_content)
                if getter_match:
                    provider_expr = getter_match.group(1)
                    abs_getter_line = full_content[:class_start + getter_match.start()].count('\n') + 1

                    # Extract code snippet
                    snippet_start = max(0, abs_getter_line - 1)
                    snippet_end = min(len(lines), abs_getter_line + 6)
                    snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                    # Try to infer correct type from provider name
                    suggested_type = self._infer_type_from_provider(provider_expr)

                    violations.append(Violation(
                        file_path=str(file_path),
                        class_name=class_name,
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

Applies to all async methods: {', '.join(async_methods)}

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                    ))

        # Find nullable fields: TypeName? _fieldName; OR dynamic _fieldName; OR late final TypeName _fieldName;
        # Patterns support simple types (String?), generics (Map<K,V>?), and nested generics (Either<A, List<B>>?)
        # Pattern 1: Generic nullable fields - Type<...>? _fieldName;
        generic_field_pattern = re.compile(r'(\w+(?:<.+?>)?)\?\s+(_\w+);', re.DOTALL)
        # Pattern 2: Dynamic fields - dynamic _fieldName; (implicitly nullable)
        dynamic_field_pattern = re.compile(r'\bdynamic\s+(_\w+);')
        # Pattern 3: Late final fields - late final TypeName _fieldName; OR late final TypeName? _fieldName;
        # CRITICAL: late final creates lazy initialization which is FORBIDDEN in async classes
        late_final_field_pattern = re.compile(r'late\s+final\s+(\w+(?:<.+?>)?)\??\s+(_\w+);', re.DOTALL)

        # Collect all fields (nullable typed + dynamic + late final) with line numbers
        all_fields = []
        for field_match in generic_field_pattern.finditer(class_content):
            line_num = full_content[:class_start + field_match.start()].count('\n') + 1
            all_fields.append((field_match.group(1), field_match.group(2), line_num))
        for field_match in dynamic_field_pattern.finditer(class_content):
            line_num = full_content[:class_start + field_match.start()].count('\n') + 1
            all_fields.append(('dynamic', field_match.group(1), line_num))
        for field_match in late_final_field_pattern.finditer(class_content):
            line_num = full_content[:class_start + field_match.start()].count('\n') + 1
            all_fields.append((field_match.group(1), field_match.group(2), line_num))

        for field_type, field_name, abs_field_line in all_fields:
            base_name = field_name[1:]  # Remove underscore

            # Escape field_type for safe use in regex patterns (handles Map<K,V>, Either<A,List<B>>, etc.)
            escaped_field_type = re.escape(field_type)

            # Check for ANY getter (sync or async) for this field
            # Pattern 1: Sync getter with field caching
            # Handle both typed fields (String?, int?) and dynamic fields
            if field_type == 'dynamic':
                # For dynamic fields, getter can be dynamic or any type
                sync_getter_patterns = [
                    # Enhanced getter with StateError (any return type)
                    rf'\w+\s+get\s+{base_name}\s*\{{[^}}]*{field_name}[^}}]*StateError',
                    # Simple lazy getter (any return type)
                    rf'\w+\s+get\s+{base_name}\s*\{{[^}}]*{field_name}\s*\?\?=',
                    # Arrow syntax with any return type
                    rf'\w+\s+get\s+{base_name}\s*=>\s*{field_name}\s*;',
                ]
            else:
                # For typed fields, match the specific type (nullable or non-nullable return)
                sync_getter_patterns = [
                    # Enhanced getter with StateError (nullable or non-nullable return type)
                    rf'{escaped_field_type}\??\s+get\s+{base_name}\s*\{{[^}}]*{field_name}[^}}]*StateError',
                    # Simple lazy getter
                    rf'{escaped_field_type}\??\s+get\s+{base_name}\s*\{{[^}}]*{field_name}\s*\?\?=',
                    # Arrow syntax with ref.read
                    rf'{escaped_field_type}\??\s+get\s+{base_name}\s*=>\s*ref\.read\(',
                    # Simple arrow getter returning cached field (CRITICAL: Field caching pattern)
                    # Matches both nullable and non-nullable return types
                    rf'{escaped_field_type}\??\s+get\s+{base_name}\s*=>\s*{field_name}\s*;',
                ]

            # Pattern 2: Async getter with field caching
            async_getter_patterns = [
                rf'Future<{escaped_field_type}>\s+get\s+{base_name}\s+async\s*\{{',
                rf'Future<{escaped_field_type}>\s+get\s+{base_name}Future\s+async\s*\{{',
            ]

            # Check sync getters
            for pattern in sync_getter_patterns:
                getter_match = re.search(pattern, class_content, re.DOTALL)
                if getter_match:
                    abs_getter_line = full_content[:class_start + getter_match.start()].count('\n') + 1

                    # Extract code snippet
                    snippet_start = max(0, abs_getter_line - 1)
                    snippet_end = min(len(lines), abs_getter_line + 8)
                    snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                    if has_async_methods:
                        violations.append(Violation(
                            file_path=str(file_path),
                            class_name=class_name,
                            violation_type=ViolationType.FIELD_CACHING,
                            line_number=abs_getter_line,
                            context=f"Field caching: {field_name} with getter in async class",
                            code_snippet=snippet,
                            fix_instructions=self._get_field_caching_fix(field_name, async_methods, is_consumer_state)
                        ))
                    elif 'ref.read' in getter_match.group(0):
                        # Lazy getter pattern
                        violations.append(Violation(
                            file_path=str(file_path),
                            class_name=class_name,
                            violation_type=ViolationType.LAZY_GETTER,
                            line_number=abs_getter_line,
                            context=f"Lazy getter: get {base_name} => ref.read()",
                            code_snippet=snippet,
                            fix_instructions=self._get_lazy_getter_fix(base_name)
                        ))
                    break

            # Check async getters
            for pattern in async_getter_patterns:
                getter_match = re.search(pattern, class_content, re.DOTALL)
                if getter_match:
                    abs_getter_line = full_content[:class_start + getter_match.start()].count('\n') + 1

                    snippet_start = max(0, abs_getter_line - 1)
                    snippet_end = min(len(lines), abs_getter_line + 8)
                    snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                    violations.append(Violation(
                        file_path=str(file_path),
                        class_name=class_name,
                        violation_type=ViolationType.ASYNC_GETTER,
                        line_number=abs_getter_line,
                        context=f"Async getter with field caching: {field_name}",
                        code_snippet=snippet,
                        fix_instructions=self._get_async_getter_fix(field_name)
                    ))
                    break

        return violations

    def _check_async_method_safety(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str],
        async_methods: List[str], is_consumer_state: bool = False
    ) -> List[Violation]:
        """Check async methods for ref safety patterns (VIOLATIONS 4-6)"""
        violations = []

        # Determine which mounted pattern to check based on class type
        if is_consumer_state:
            # ConsumerStatefulWidget uses widget's 'mounted' property
            mounted_pattern = r'if\s*\(\s*!mounted\s*\)'
        else:
            # Riverpod provider classes use 'ref.mounted'
            mounted_pattern = r'if\s*\(\s*!ref\.mounted\s*\)'

        for method_name in async_methods:
            # Find the method (Future, FutureOr, or Stream)
            method_pattern = re.compile(
                rf'(?:Future<[^>]+>|FutureOr<[^>]+>|Stream<[^>]+>)\s+{method_name}\s*\([^)]*\)\s+async\*?\s*\{{',
                re.DOTALL
            )
            method_match = method_pattern.search(class_content)

            if not method_match:
                continue

            method_start = method_match.end()
            method_end = self._find_method_end(class_content, method_start)
            method_body = class_content[method_start:method_end]
            method_lines = method_body.split('\n')

            # VIOLATION 4: ref operation (read/watch/listen) before mounted check
            first_10_lines = '\n'.join(method_lines[:10])
            # Strip comments to avoid false positives from comments containing ref operations
            first_10_lines_no_comments = self._remove_comments(first_10_lines)

            has_early_mounted = re.search(mounted_pattern, first_10_lines_no_comments)
            # Check for ANY ref operation: ref.read(), ref.watch(), or ref.listen()
            ref_operation_match = re.search(r'ref\.(read|watch|listen)\(', first_10_lines_no_comments)

            if ref_operation_match and not has_early_mounted:
                # Determine which operation was used
                operation_name = ref_operation_match.group(1)
                abs_line = full_content[:class_start + method_start].count('\n') + 2
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 5)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
                    violation_type=ViolationType.REF_READ_BEFORE_MOUNTED,
                    line_number=abs_line,
                    context=f"Method {method_name}(): ref.{operation_name}() before mounted check",
                    code_snippet=snippet,
                    fix_instructions=self._get_ref_read_before_mounted_fix()
                ))

            # VIOLATION 5: Missing ref.mounted after await
            await_pattern = re.compile(r'await\s+')
            for await_match in await_pattern.finditer(method_body):
                await_line_num = method_body[:await_match.start()].count('\n')
                await_line_in_body = await_line_num

                # Find the end of the await statement (semicolon or closing brace/paren)
                await_statement_start = await_match.start()
                await_statement_end = self._find_statement_end(method_body, await_statement_start)

                # Get the await statement to check if it contains callbacks
                await_statement = method_body[await_statement_start:await_statement_end]

                # Skip if await contains a callback/closure (onApproved:, builder:, etc.)
                # These callbacks may have their own ref usage with their own ref.mounted checks
                if re.search(r':\s*\([^)]*\)\s*\{', await_statement) or re.search(r':\s*\(\)\s*\{', await_statement):
                    continue

                # Skip if this is a "return await" statement - no code executes after
                # Example: return await _signInWithAppleIOS();
                # The method returns immediately, so mounted check would never execute
                current_line = method_lines[await_line_num] if await_line_num < len(method_lines) else ''
                if re.search(r'\breturn\s+await\s+', current_line):
                    continue

                # Get next 25 lines after await to find mounted check (increased from 15)
                # Some methods have long function call chains that span many lines
                remaining_lines = method_lines[await_line_num + 1:await_line_num + 26]
                next_lines = '\n'.join(remaining_lines)

                # Check if mounted appears in next lines (use appropriate pattern for class type)
                has_mounted_after = re.search(mounted_pattern, next_lines)

                # Check if there's significant code after await that requires mounted check
                # This includes: return with value, ref operations, state assignments, method calls
                has_significant_code = self._has_significant_code_after_await(next_lines)

                if has_significant_code and not has_mounted_after:
                    abs_line = full_content[:class_start + method_start + await_match.start()].count('\n') + 1
                    snippet_start = max(0, abs_line - 1)
                    snippet_end = min(len(lines), abs_line + 5)
                    snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                    violations.append(Violation(
                        file_path=str(file_path),
                        class_name=class_name,
                        violation_type=ViolationType.MISSING_MOUNTED_AFTER_AWAIT,
                        line_number=abs_line,
                        context=f"Method {method_name}(): Missing ref.mounted after await",
                        code_snippet=snippet,
                        fix_instructions=self._get_missing_mounted_after_await_fix()
                    ))

            # VIOLATION 6: Missing mounted in catch blocks
            catch_pattern = re.compile(r'catch\s*\([^)]+\)\s*\{')
            for catch_match in catch_pattern.finditer(method_body):
                catch_start = catch_match.end()
                catch_end = self._find_block_end(method_body, catch_start)
                catch_body = method_body[catch_start:catch_end]

                # Check first few lines of catch block
                catch_first_lines = '\n'.join(catch_body.split('\n')[:5])
                has_mounted = re.search(mounted_pattern, catch_first_lines)
                has_ref_usage = re.search(r'ref\.(read|watch|listen)', catch_first_lines)

                if has_ref_usage and not has_mounted:
                    abs_line = full_content[:class_start + method_start + catch_match.start()].count('\n') + 1
                    snippet_start = max(0, abs_line - 1)
                    snippet_end = min(len(lines), abs_line + 8)
                    snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                    violations.append(Violation(
                        file_path=str(file_path),
                        class_name=class_name,
                        violation_type=ViolationType.MISSING_MOUNTED_IN_CATCH,
                        line_number=abs_line,
                        context=f"Method {method_name}(): Missing ref.mounted in catch block",
                        code_snippet=snippet,
                        fix_instructions=self._get_missing_mounted_in_catch_fix()
                    ))

        return violations

    def _check_sync_methods_without_mounted(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str],
        is_consumer_state: bool = False
    ) -> List[Violation]:
        """Check for VIOLATION 10: Sync methods with ref.read() but no mounted check

        CRITICAL: Sync methods are safe when called synchronously but crash when
        called from async callbacks (onCompletion:, builder:, etc.) because the
        provider can be disposed during the await gap.

        Example crash pattern (Sentry #7109530155):
            await gameCompletionService.handleGameCompletion(
                onCompletion: () {
                    basketballNotifier.completeGame(); // ← CRASH if provider disposed during await
                }
            );

        The completeGame() method uses ref.read() without checking ref.mounted first.
        """
        violations = []

        # Find sync methods with ref.read() but no mounted check
        # Pass is_consumer_state to use correct mounted pattern
        sync_methods = self._find_sync_methods_with_ref_read(class_content, is_consumer_state)

        for method_name, line_offset, method_body in sync_methods:
            # CRITICAL: Only flag if this method is called from async context
            # This eliminates false positives for methods only called synchronously
            method_key = (str(file_path), class_name, method_name)

            if method_key not in self.methods_called_from_async:
                # Method is NOT called from async context - skip (no violation)
                continue

            # Calculate absolute line number
            abs_line = full_content[:class_start].count('\n') + line_offset + 1

            snippet_start = max(0, abs_line - 1)
            snippet_end = min(len(lines), abs_line + 8)
            snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

            # Determine mounted check type based on class
            mounted_check = 'if (!mounted) return;' if is_consumer_state else 'if (!ref.mounted) return;'

            violations.append(Violation(
                file_path=str(file_path),
                class_name=class_name,
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

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
            ))

        return violations

    def _check_nullable_field_misuse(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str]
    ) -> List[Violation]:
        """Check for VIOLATION 7: Using _field?.method() when getter exists"""
        violations = []

        # Find nullable fields with getters
        field_pattern = re.compile(r'(\w+)\?\s+(_\w+);')

        for field_match in field_pattern.finditer(class_content):
            field_type = field_match.group(1)
            field_name = field_match.group(2)
            base_name = field_name[1:]

            # Check if a getter exists for this field
            getter_pattern = re.compile(rf'{field_type}\s+get\s+{base_name}\s*[{{=>]')
            has_getter = getter_pattern.search(class_content)

            if has_getter:
                # Check for direct nullable field access
                nullable_access_pattern = re.compile(rf'{field_name}\?\.')

                for access_match in nullable_access_pattern.finditer(class_content):
                    abs_line = full_content[:class_start + access_match.start()].count('\n') + 1
                    snippet_start = max(0, abs_line - 1)
                    snippet_end = min(len(lines), abs_line + 3)
                    snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                    violations.append(Violation(
                        file_path=str(file_path),
                        class_name=class_name,
                        violation_type=ViolationType.NULLABLE_FIELD_ACCESS,
                        line_number=abs_line,
                        context=f"Using {field_name}?.method() instead of {base_name}.method()",
                        code_snippet=snippet,
                        fix_instructions=f"Replace {field_name}?. with {base_name}."
                    ))

        return violations

    def _check_ref_in_lifecycle_callbacks(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str]
    ) -> List[Violation]:
        """Check for VIOLATION 8: ref.read/watch/listen inside lifecycle callbacks (direct AND indirect)"""
        violations = []

        # CRITICAL: Strip comments to avoid false positives
        stripped_class_content, class_position_map = self._strip_comments(class_content)

        # STEP 1: Find all methods in this class that use ref operations
        # Use ORIGINAL content for method detection (comments don't affect this)
        methods_using_ref = self._find_methods_using_ref(class_content)

        # STEP 2: Find ref.onDispose callbacks in STRIPPED content
        ondispose_pattern = re.compile(r'ref\.onDispose\s*\(')

        for ondispose_match in ondispose_pattern.finditer(stripped_class_content):
            callback_start = ondispose_match.end()
            callback_end = self._find_callback_end(stripped_class_content, callback_start)
            callback_content = stripped_class_content[callback_start:callback_end]

            # CHECK A: Direct ref operations inside the callback
            # CRITICAL: Detect ALL ref operations, not just read/watch/listen
            # This includes: invalidateSelf, invalidate, refresh, state setter, etc.
            ref_usage_pattern = re.compile(
                r'\bref\.(read|watch|listen|invalidateSelf|invalidate|refresh|notifyListeners|onDispose|onCancel|onResume|onAddListener|onRemoveListener|state)\s*[(\.]'
            )

            for ref_match in ref_usage_pattern.finditer(callback_content):
                # Map stripped position back to original position for accurate line numbers
                stripped_pos = ondispose_match.start() + callback_start + ref_match.start()
                original_pos = class_position_map.get(stripped_pos, stripped_pos)
                abs_pos = class_start + original_pos
                abs_line = full_content[:abs_pos].count('\n') + 1

                snippet_start = max(0, abs_line - 2)
                snippet_end = min(len(lines), abs_line + 3)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                ref_op = ref_match.group(1)

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
                    violation_type=ViolationType.REF_IN_LIFECYCLE_CALLBACK,
                    line_number=abs_line,
                    context=f"DIRECT: ref.{ref_op}() called inside ref.onDispose() callback",
                    code_snippet=snippet,
                    fix_instructions=self._get_ref_in_lifecycle_fix(ref_op, is_direct=True)
                ))

            # CHECK B: Indirect violations - calling methods that use ref (SAME CLASS)
            for method_name in methods_using_ref:
                # Look for calls to this method inside the callback
                method_call_pattern = re.compile(rf'\b{method_name}\s*\(')

                for call_match in method_call_pattern.finditer(callback_content):
                    # Map stripped position back to original position
                    stripped_pos = ondispose_match.start() + callback_start + call_match.start()
                    original_pos = class_position_map.get(stripped_pos, stripped_pos)
                    abs_pos = class_start + original_pos
                    abs_line = full_content[:abs_pos].count('\n') + 1

                    snippet_start = max(0, abs_line - 2)
                    snippet_end = min(len(lines), abs_line + 3)
                    snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                    violations.append(Violation(
                        file_path=str(file_path),
                        class_name=class_name,
                        violation_type=ViolationType.REF_IN_LIFECYCLE_CALLBACK,
                        line_number=abs_line,
                        context=f"INDIRECT (same class): {method_name}() called inside ref.onDispose() - method uses ref internally",
                        code_snippet=snippet,
                        fix_instructions=self._get_ref_in_lifecycle_fix(method_name, is_direct=False)
                    ))

            # CHECK C: Indirect violations - calling methods on OTHER providers (CROSS-CLASS)
            # Look for patterns like: someNotifier.methodName()
            cross_class_call_pattern = re.compile(r'(\w+)\.(\w+)\s*\(')

            for call_match in cross_class_call_pattern.finditer(callback_content):
                variable_name = call_match.group(1)
                method_name = call_match.group(2)

                # Skip obvious non-provider calls
                if method_name in ['dispose', 'cancel', 'close', 'clear', 'reset']:
                    continue

                # Try to resolve the variable to a provider/class
                # Search in FULL class content, not just callback (variables may be declared outside)
                target_class = self._resolve_variable_to_class(variable_name, class_content, full_content)

                if target_class and target_class in self.methods_using_ref:
                    if method_name in self.methods_using_ref[target_class]:
                        # Map stripped position back to original position
                        stripped_pos = ondispose_match.start() + callback_start + call_match.start()
                        original_pos = class_position_map.get(stripped_pos, stripped_pos)
                        abs_pos = class_start + original_pos
                        abs_line = full_content[:abs_pos].count('\n') + 1

                        snippet_start = max(0, abs_line - 2)
                        snippet_end = min(len(lines), abs_line + 3)
                        snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                        target_file = self.class_to_file.get(target_class, "unknown")

                        violations.append(Violation(
                            file_path=str(file_path),
                            class_name=class_name,
                            violation_type=ViolationType.REF_IN_LIFECYCLE_CALLBACK,
                            line_number=abs_line,
                            context=f"INDIRECT (cross-class): {variable_name}.{method_name}() called inside ref.onDispose() - {target_class}.{method_name}() uses ref internally (defined in {target_file})",
                            code_snippet=snippet,
                            fix_instructions=self._get_ref_in_lifecycle_fix(f"{target_class}.{method_name}", is_direct=False, is_cross_class=True)
                        ))

        # STEP 3: Also check ref.listen callbacks (Pattern 4 from guide)
        # ref.listen callbacks ALSO cannot contain ref operations
        listen_pattern = re.compile(r'ref\.listen\s*\(')

        for listen_match in listen_pattern.finditer(stripped_class_content):
            # Find the callback function in ref.listen(provider, (prev, next) { ... })
            # The callback starts after the second parameter
            callback_search_start = listen_match.end()

            # Find the opening brace of the callback function
            paren_depth = 1  # We're inside the ref.listen(
            i = callback_search_start
            callback_start = None

            while i < len(stripped_class_content) and paren_depth > 0:
                if stripped_class_content[i] == '(':
                    paren_depth += 1
                elif stripped_class_content[i] == ')':
                    paren_depth -= 1
                    if paren_depth == 0:
                        # This closes ref.listen(), but we need to find the callback inside
                        # Look backwards for the callback function
                        # Pattern: (previous, next) { ... }
                        temp_i = i
                        while temp_i > callback_search_start:
                            if stripped_class_content[temp_i] == '{':
                                callback_start = temp_i + 1
                                break
                            temp_i -= 1
                        break
                elif stripped_class_content[i] == '{' and paren_depth == 1:
                    # Found opening brace of callback while still inside ref.listen()
                    callback_start = i + 1
                    break
                i += 1

            if callback_start is None:
                continue

            callback_end = self._find_callback_end(stripped_class_content, callback_start - 1)
            callback_content = stripped_class_content[callback_start:callback_end]

            # CHECK: Direct ref operations inside the ref.listen callback
            # CRITICAL: Detect ALL ref operations, not just read/watch/listen
            # This includes: invalidateSelf, invalidate, refresh, state setter, etc.
            ref_usage_pattern = re.compile(
                r'\bref\.(read|watch|listen|invalidateSelf|invalidate|refresh|notifyListeners|onDispose|onCancel|onResume|onAddListener|onRemoveListener|state)\s*[(\.]'
            )

            for ref_match in ref_usage_pattern.finditer(callback_content):
                # Map stripped position back to original position
                stripped_pos = callback_start + ref_match.start()
                original_pos = class_position_map.get(stripped_pos, stripped_pos)
                abs_pos = class_start + original_pos
                abs_line = full_content[:abs_pos].count('\n') + 1

                snippet_start = max(0, abs_line - 2)
                snippet_end = min(len(lines), abs_line + 3)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                ref_op = ref_match.group(1)

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
                    violation_type=ViolationType.REF_IN_LIFECYCLE_CALLBACK,
                    line_number=abs_line,
                    context=f"DIRECT: ref.{ref_op}() called inside ref.listen() callback",
                    code_snippet=snippet,
                    fix_instructions=self._get_ref_in_lifecycle_fix(ref_op, is_direct=True, callback_type="ref.listen")
                ))

        return violations

    def _check_ref_operations_outside_build(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str]
    ) -> List[Violation]:
        """Check for ref.listen/ref.watch called outside build() method"""
        violations = []

        # Strip comments to avoid false positives from commented code
        stripped_class_content, class_position_map = self._strip_comments(class_content)

        # Find the build method
        build_pattern = re.compile(
            r'(@override\s+)?Widget\s+build\s*\([^)]*\)\s*\{',
            re.DOTALL
        )

        build_match = build_pattern.search(stripped_class_content)
        if not build_match:
            # No build method - skip this check
            return violations

        build_start = build_match.end()
        build_end = self._find_method_end(stripped_class_content, build_start)

        # Find all Widget-returning helper methods (these are part of build phase)
        # Pattern: Widget _buildXxx() or Widget _someMethod()
        widget_helper_methods = []
        helper_pattern = re.compile(r'Widget\s+(_\w+)\s*\([^)]*\)\s*\{', re.DOTALL)

        for helper_match in helper_pattern.finditer(stripped_class_content):
            method_name = helper_match.group(1)
            method_start = helper_match.end()
            method_end = self._find_method_end(stripped_class_content, method_start)
            widget_helper_methods.append({
                'name': method_name,
                'start': method_start,
                'end': method_end
            })

        # Check if helper methods are called from build() - with transitive analysis
        # A helper is safe if:
        # 1. It's called directly from build(), OR
        # 2. It's called from another safe helper (transitive)
        build_content = stripped_class_content[build_start:build_end]
        called_helpers = set()

        # First pass: Find helpers called directly from build()
        for helper in widget_helper_methods:
            if re.search(rf'\b{helper["name"]}\s*\(', build_content):
                called_helpers.add(helper['name'])

        # Transitive passes: Find helpers called from other safe helpers
        # Keep iterating until no new helpers are found
        changed = True
        max_iterations = 10  # Prevent infinite loops
        iteration = 0

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1

            for helper in widget_helper_methods:
                if helper['name'] not in called_helpers:
                    # Check if this helper is called from any safe helper
                    helper_content = stripped_class_content[helper['start']:helper['end']]

                    for safe_helper in list(called_helpers):
                        # Find the safe helper's content
                        safe_helper_obj = next((h for h in widget_helper_methods if h['name'] == safe_helper), None)
                        if safe_helper_obj:
                            safe_helper_content = stripped_class_content[safe_helper_obj['start']:safe_helper_obj['end']]
                            if re.search(rf'\b{helper["name"]}\s*\(', safe_helper_content):
                                called_helpers.add(helper['name'])
                                changed = True
                                break

        # Find all ref.listen and ref.watch calls
        ref_listen_pattern = re.compile(r'\bref\.listen\s*\(')
        ref_watch_pattern = re.compile(r'\bref\.watch\s*\(')

        # Helper function to check if position is in a safe location
        def is_in_safe_context(call_pos):
            # 1. Inside main build() method
            if build_start <= call_pos <= build_end:
                return True

            # 2. Inside Widget-returning helper method called from build()
            for helper in widget_helper_methods:
                if helper['start'] <= call_pos <= helper['end']:
                    # Only safe if this helper is actually called from build
                    if helper['name'] in called_helpers:
                        return True

            # 3. Inside Consumer builder callback
            # Pattern: Consumer(builder: (context, ref, _) { ... })
            # Find all Consumer/Consumer2 builder callbacks
            consumer_pattern = re.compile(r'Consumer\d*\s*\(\s*builder:\s*\([^)]*\)\s*\{')
            for consumer_match in consumer_pattern.finditer(stripped_class_content):
                consumer_start = consumer_match.end()
                consumer_end = self._find_method_end(stripped_class_content, consumer_start)
                if consumer_start <= call_pos <= consumer_end:
                    return True

            return False

        # Check ref.listen calls
        for listen_match in ref_listen_pattern.finditer(stripped_class_content):
            call_pos = listen_match.start()

            # Check if this call is in a safe context
            if not is_in_safe_context(call_pos):
                # Map stripped position back to original position for accurate line numbers
                original_pos = class_position_map.get(class_start + call_pos, class_start + call_pos)
                abs_line = full_content[:original_pos].count('\n') + 1
                snippet_start = max(0, abs_line - 3)
                snippet_end = min(len(lines), abs_line + 5)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
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
"""
                ))

        # Check ref.watch calls (outside build method - less common but still wrong)
        for watch_match in ref_watch_pattern.finditer(stripped_class_content):
            call_pos = watch_match.start()

            # Check if this call is in a safe context
            if not is_in_safe_context(call_pos):
                # Map stripped position back to original position for accurate line numbers
                original_pos = class_position_map.get(class_start + call_pos, class_start + call_pos)
                abs_line = full_content[:original_pos].count('\n') + 1
                snippet_start = max(0, abs_line - 3)
                snippet_end = min(len(lines), abs_line + 5)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
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
"""
                ))

        return violations

    def _check_widget_lifecycle_unsafe_ref(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str]
    ) -> List[Violation]:
        """Check for VIOLATION 9: Unsafe ref usage in widget lifecycle methods"""
        violations = []

        # Widget lifecycle methods that are risky for ref usage
        risky_lifecycle_methods = {
            'didUpdateWidget': 'WARN',  # Can be called during disposal
            'deactivate': 'ERROR',       # Called during unmount - DEADLY
            'reassemble': 'WARN',        # Hot reload - widget may be unstable
        }

        for method_name, severity in risky_lifecycle_methods.items():
            # Find the lifecycle method
            lifecycle_pattern = re.compile(
                rf'@override\s+void\s+{method_name}\s*\([^)]*\)\s*\{{',
                re.DOTALL
            )

            for method_match in lifecycle_pattern.finditer(class_content):
                method_start = method_match.end()
                method_end = self._find_method_end(class_content, method_start)
                method_body = class_content[method_start:method_end]

                # Check for ref.read/watch/listen in the method
                has_ref_usage = re.search(r'\bref\.(read|watch|listen)\(', method_body)

                if has_ref_usage:
                    abs_line = full_content[:class_start + method_match.start()].count('\n') + 1
                    snippet_start = max(0, abs_line - 1)
                    snippet_end = min(len(lines), abs_line + 10)
                    snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                    context_msg = f"{severity}: ref usage in {method_name}() - widget may be unmounting"
                    if severity == 'ERROR':
                        context_msg = f"DEADLY: ref usage in {method_name}() - widget IS unmounting, will crash"

                    violations.append(Violation(
                        file_path=str(file_path),
                        class_name=class_name,
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

{f'''OPTION 1: Remove all ref operations from {method_name}()
   @override
   void {method_name}(...) {{
     super.{method_name}(...);
     // NO ref operations here - this is disposal time
     _subscription?.cancel();
     _controller?.close();
   }}''' if method_name == 'deactivate' else f'''OPTION 1: Capture dependencies BEFORE {method_name}() is called
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
   }}'''}

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                    ))

                # Special check for addPostFrameCallback in didUpdateWidget
                if method_name == 'didUpdateWidget':
                    postframe_pattern = re.compile(r'addPostFrameCallback\s*\([^)]*\)\s*\{')
                    for postframe_match in postframe_pattern.finditer(method_body):
                        callback_start = postframe_match.end()
                        callback_end = self._find_callback_end(method_body, callback_start - 1)
                        callback_content = method_body[callback_start:callback_end]

                        # Check if callback has mounted check
                        has_mounted_check = re.search(r'if\s*\(\s*mounted\s*\)', callback_content)

                        # Check if callback calls async methods
                        async_call_pattern = re.compile(r'_\w+\s*\(')
                        for call_match in async_call_pattern.finditer(callback_content):
                            method_called = call_match.group(0).strip('(').strip()

                            # Check if this is an async method we detected
                            if any(method_called.startswith('_' + am) for am in self._find_async_methods(class_content)):
                                if not has_mounted_check:
                                    abs_line = full_content[:class_start + method_start + postframe_match.start()].count('\n') + 1
                                    snippet_start = max(0, abs_line - 1)
                                    snippet_end = min(len(lines), abs_line + 8)
                                    snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                                    violations.append(Violation(
                                        file_path=str(file_path),
                                        class_name=class_name,
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

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                                    ))

        return violations

    def _check_deferred_callback_unsafe_ref(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str]
    ) -> List[Violation]:
        """Check for VIOLATION 10: Timer/Future.delayed callbacks without mounted checks"""
        violations = []

        # Pattern 1: Future.delayed
        future_delayed_pattern = re.compile(r'Future\.delayed\s*\([^)]*\)\s*,\s*\(\)\s*\{')

        for delayed_match in future_delayed_pattern.finditer(class_content):
            callback_start = delayed_match.end()
            callback_end = self._find_callback_end(class_content, callback_start - 1)
            callback_content = class_content[callback_start:callback_end]

            # Check if callback has mounted check
            has_mounted_check = re.search(r'if\s*\(\s*!?mounted\s*\)', callback_content)

            # Check if callback uses ref
            has_ref_usage = re.search(r'\bref\.(read|watch|listen)\(', callback_content)

            # Check if callback calls methods that might use ref
            has_method_calls = re.search(r'_\w+\s*\(', callback_content)

            if (has_ref_usage or has_method_calls) and not has_mounted_check:
                abs_line = full_content[:class_start + delayed_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 8)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
                    violation_type=ViolationType.DEFERRED_CALLBACK_UNSAFE_REF,
                    line_number=abs_line,
                    context="WARNING: Future.delayed callback without mounted check before ref usage",
                    code_snippet=snippet,
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

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                ))

        # Pattern 2: Timer.periodic and Timer constructors
        timer_pattern = re.compile(r'Timer(?:\.periodic)?\s*\([^,]+,\s*\([^)]*\)\s*\{')

        for timer_match in timer_pattern.finditer(class_content):
            callback_start = timer_match.end()
            callback_end = self._find_callback_end(class_content, callback_start - 1)
            callback_content = class_content[callback_start:callback_end]

            # Check if callback has mounted check
            has_mounted_check = re.search(r'if\s*\(\s*!?mounted\s*\)', callback_content)

            # Check if callback uses ref
            has_ref_usage = re.search(r'\bref\.(read|watch|listen)\(', callback_content)

            if has_ref_usage and not has_mounted_check:
                abs_line = full_content[:class_start + timer_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 8)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
                    violation_type=ViolationType.DEFERRED_CALLBACK_UNSAFE_REF,
                    line_number=abs_line,
                    context="WARNING: Timer callback without mounted check before ref usage",
                    code_snippet=snippet,
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

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                ))

        # Pattern 3: addPostFrameCallback
        postframe_pattern = re.compile(r'addPostFrameCallback\s*\(\s*\([^)]*\)\s*\{', re.DOTALL)

        for postframe_match in postframe_pattern.finditer(class_content):
            callback_start = postframe_match.end()
            callback_end = self._find_callback_end(class_content, callback_start - 1)
            callback_content = class_content[callback_start:callback_end]

            # Check if callback has mounted check
            has_mounted_check = re.search(r'if\s*\(\s*!?mounted\s*\)', callback_content)

            # Check if callback uses ref directly
            has_ref_usage = re.search(r'\bref\.(read|watch|listen)\(', callback_content)

            # Check if callback uses lazy getters (methods that internally use ref.read)
            # Common pattern: logger.logInfo, getter.method, etc.
            has_getter_usage = re.search(r'\b(logger|[a-z][a-zA-Z]*Notifier|[a-z][a-zA-Z]*Service)\s*\.', callback_content)

            if (has_ref_usage or has_getter_usage) and not has_mounted_check:
                abs_line = full_content[:class_start + postframe_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 8)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
                    violation_type=ViolationType.DEFERRED_CALLBACK_UNSAFE_REF,
                    line_number=abs_line,
                    context="CRITICAL: addPostFrameCallback without mounted check - caused production crash",
                    code_snippet=snippet,
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
Sentry Issue: #7364580c89a044b387aafbb7a997a682 (iOS production crash)"""
                ))

        # Pattern 4: .then() callbacks (deferred Future completion handlers)
        # Matches: .then((value) { ... }) or .then((_) { ... })
        then_pattern = re.compile(r'\.then\s*\(\s*\([^)]*\)\s*\{', re.DOTALL)

        for then_match in then_pattern.finditer(class_content):
            callback_start = then_match.end()
            callback_end = self._find_callback_end(class_content, callback_start - 1)
            callback_content = class_content[callback_start:callback_end]

            # Check if callback has mounted check
            has_mounted_check = re.search(r'if\s*\(\s*!?mounted\s*\)', callback_content)

            # Check if callback uses ref directly
            has_ref_usage = re.search(r'\bref\.(read|watch|listen)\(', callback_content)

            # Check if callback uses lazy getters
            has_getter_usage = re.search(r'\b(logger|[a-z][a-zA-Z]*Notifier|[a-z][a-zA-Z]*Service)\s*\.', callback_content)

            if (has_ref_usage or has_getter_usage) and not has_mounted_check:
                abs_line = full_content[:class_start + then_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 8)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
                    violation_type=ViolationType.DEFERRED_CALLBACK_UNSAFE_REF,
                    line_number=abs_line,
                    context="CRITICAL: .then() callback without mounted check",
                    code_snippet=snippet,
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

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                ))

        # Pattern 5: .catchError() callbacks
        catcherror_pattern = re.compile(r'\.catchError\s*\(\s*\([^)]*\)\s*\{', re.DOTALL)

        for catch_match in catcherror_pattern.finditer(class_content):
            callback_start = catch_match.end()
            callback_end = self._find_callback_end(class_content, callback_start - 1)
            callback_content = class_content[callback_start:callback_end]

            has_mounted_check = re.search(r'if\s*\(\s*!?mounted\s*\)', callback_content)
            has_ref_usage = re.search(r'\bref\.(read|watch|listen)\(', callback_content)
            has_getter_usage = re.search(r'\b(logger|[a-z][a-zA-Z]*Notifier|[a-z][a-zA-Z]*Service)\s*\.', callback_content)

            if (has_ref_usage or has_getter_usage) and not has_mounted_check:
                abs_line = full_content[:class_start + catch_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 8)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
                    violation_type=ViolationType.DEFERRED_CALLBACK_UNSAFE_REF,
                    line_number=abs_line,
                    context="CRITICAL: .catchError() callback without mounted check",
                    code_snippet=snippet,
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

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                ))

        # Pattern 6: .whenComplete() callbacks
        whencomplete_pattern = re.compile(r'\.whenComplete\s*\(\s*\([^)]*\)\s*\{', re.DOTALL)

        for complete_match in whencomplete_pattern.finditer(class_content):
            callback_start = complete_match.end()
            callback_end = self._find_callback_end(class_content, callback_start - 1)
            callback_content = class_content[callback_start:callback_end]

            has_mounted_check = re.search(r'if\s*\(\s*!?mounted\s*\)', callback_content)
            has_ref_usage = re.search(r'\bref\.(read|watch|listen)\(', callback_content)
            has_getter_usage = re.search(r'\b(logger|[a-z][a-zA-Z]*Notifier|[a-z][a-zA-Z]*Service)\s*\.', callback_content)

            if (has_ref_usage or has_getter_usage) and not has_mounted_check:
                abs_line = full_content[:class_start + complete_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 8)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
                    violation_type=ViolationType.DEFERRED_CALLBACK_UNSAFE_REF,
                    line_number=abs_line,
                    context="CRITICAL: .whenComplete() callback without mounted check",
                    code_snippet=snippet,
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

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                ))

        return violations

    def _check_async_event_handler_callbacks(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str]
    ) -> List[Violation]:
        """Check for VIOLATION 15: Async event handler callbacks without mounted checks

        Detects async lambda functions in event handlers (onTap, onPressed, etc.) that
        use ref after await without checking ref.mounted.

        This caused production crash Sentry #7230735475 - ref used in onTap callback
        after widget was unmounted.
        """
        violations = []

        # Common event handler patterns that accept async callbacks
        # Pattern: onTap: () async { ... }, onPressed: () async { ... }, etc.
        event_handlers = [
            'onTap', 'onPressed', 'onLongPress', 'onChanged', 'onSubmitted',
            'onSaved', 'onEditingComplete', 'onFieldSubmitted', 'onRefresh',
            'onPageChanged', 'onReorder', 'onAccept', 'onWillAccept', 'onEnd'
        ]

        # Build regex pattern for async event handlers
        # Matches: onTap: () async { ... }
        for handler in event_handlers:
            pattern = re.compile(
                rf'{handler}\s*:\s*\(\)\s*async\s*\{{',
                re.DOTALL
            )

            for match in pattern.finditer(class_content):
                callback_start = match.end()
                callback_end = self._find_callback_end(class_content, callback_start - 1)
                callback_content = class_content[callback_start:callback_end]

                # Check if callback has await statements
                await_pattern = re.compile(r'\bawait\s+')
                await_matches = list(await_pattern.finditer(callback_content))

                if not await_matches:
                    # No await, no risk of unmounting during execution
                    continue

                # Check if callback uses ref after any await
                ref_usages = []
                ref_pattern = re.compile(r'\bref\.(read|watch|listen)\(')

                for ref_match in ref_pattern.finditer(callback_content):
                    ref_pos = ref_match.start()

                    # Check if this ref usage is after any await
                    for await_match in await_matches:
                        if ref_pos > await_match.end():
                            # This ref usage is after an await
                            ref_usages.append(ref_match)
                            break

                if not ref_usages:
                    # No ref usage after await, safe
                    continue

                # Now check if there's a mounted check before the ref usage
                # Look for: if (!ref.mounted) return; or if (!mounted) return;
                mounted_checks = list(re.finditer(
                    r'if\s*\(\s*!\s*(ref\.)?mounted\s*\)\s*return',
                    callback_content
                ))

                # For each ref usage after await, verify there's a mounted check
                for ref_usage in ref_usages:
                    ref_pos = ref_usage.start()

                    # Find the last mounted check before this ref usage
                    last_mounted_check = None
                    for mounted_check in mounted_checks:
                        if mounted_check.start() < ref_pos:
                            last_mounted_check = mounted_check

                    # Check if there's an await between the last mounted check and ref usage
                    has_await_after_check = False
                    if last_mounted_check:
                        check_pos = last_mounted_check.end()
                        for await_match in await_matches:
                            if check_pos < await_match.start() < ref_pos:
                                has_await_after_check = True
                                break
                    else:
                        # No mounted check at all before ref usage
                        has_await_after_check = True

                    if has_await_after_check or last_mounted_check is None:
                        # VIOLATION: ref used after await without proper mounted check
                        abs_line = full_content[:class_start + match.start()].count('\n') + 1
                        snippet_start = max(0, abs_line - 1)
                        snippet_end = min(len(lines), abs_line + 15)
                        snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                        violations.append(Violation(
                            file_path=str(file_path),
                            class_name=class_name,
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
Caused by: Sentry #7230735475 - StateError in TournamentGameCardContent.build"""
                        ))
                        # Only report once per callback
                        break

        return violations

    def _check_untyped_lazy_getters(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str],
        has_async_methods: bool
    ) -> List[Violation]:
        """Check for VIOLATION 11: Untyped var lazy getters (defensive)"""
        violations = []

        if not has_async_methods:
            return violations

        # Find untyped fields: var _fieldName;
        var_field_pattern = re.compile(r'\bvar\s+(_\w+);')

        for field_match in var_field_pattern.finditer(class_content):
            field_name = field_match.group(1)
            base_name = field_name[1:]  # Remove underscore

            # Check for getter that uses ref.read
            getter_pattern = re.compile(
                rf'get\s+{base_name}\s*(?:=>|\{{)[^}}]*ref\.read\(',
                re.DOTALL
            )

            getter_match = getter_pattern.search(class_content)
            if getter_match:
                abs_getter_line = full_content[:class_start + getter_match.start()].count('\n') + 1

                snippet_start = max(0, abs_getter_line - 2)
                snippet_end = min(len(lines), abs_getter_line + 5)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
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

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                ))

        return violations

    def _check_mounted_confusion(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str],
        async_methods: List[str]
    ) -> List[Violation]:
        """Check for VIOLATION 12: mounted vs ref.mounted confusion (educational)"""
        violations = []

        for method_name in async_methods:
            # Find the async method (Future, FutureOr, or Stream)
            method_pattern = re.compile(
                rf'(?:Future<[^>]+>|FutureOr<[^>]+>|Stream<[^>]+>)\s+{method_name}\s*\([^)]*\)\s+async\*?\s*\{{',
                re.DOTALL
            )
            method_match = method_pattern.search(class_content)

            if not method_match:
                continue

            method_start = method_match.end()
            method_end = self._find_method_end(class_content, method_start)
            method_body = class_content[method_start:method_end]

            # Check if method has 'mounted' checks but NO 'ref.mounted' checks
            has_widget_mounted = re.search(r'if\s*\(\s*!mounted\s*\)', method_body)
            has_ref_mounted = re.search(r'if\s*\(\s*!ref\.mounted\s*\)', method_body)
            has_ref_usage = re.search(r'\bref\.(read|watch|listen)\(', method_body)

            # Only flag if:
            # 1. Has widget mounted checks
            # 2. Does NOT have ref.mounted checks
            # 3. DOES use ref operations
            if has_widget_mounted and not has_ref_mounted and has_ref_usage:
                abs_line = full_content[:class_start + method_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 15)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
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
See also: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                ))

        return violations

    def _check_initstate_field_access_before_caching(
        self, file_path: Path, class_name: str, class_content: str,
        full_content: str, class_start: int, lines: List[str]
    ) -> List[Violation]:
        """
        Check for VIOLATION 13: initState field access before caching

        Detects when initState() (or methods called from it) accesses
        cached fields that are only initialized in build().

        This is a critical production crash pattern that causes:
        - Null pointer exceptions
        - Silent query failures
        - "You are not a member" type errors when database queries fail

        Example bug (real production crash):
          BackendService? _backendService;
          BackendService get backendService => _backendService!;

          initState() {
            _getOrCreateRoom();  // ← Called BEFORE build()
          }

          _getOrCreateRoom() async {
            await backendService.client.from('rooms')...  // ← CRASH! _backendService is null
          }

          build() {
            _backendService ??= ref.read(backendServiceProvider);  // ← Too late!
          }
        """
        violations = []

        # Only check ConsumerStatefulWidget State classes (they have initState)
        if not re.search(r'extends\s+ConsumerState<', class_content):
            return violations

        # Find nullable fields with force-unwrap getters
        # Pattern: Type? _fieldName; ... Type get fieldName => _fieldName!;
        field_getter_pattern = re.compile(
            r'(\w+)\?\s+(_\w+)\s*;.*?'
            r'\1\s+get\s+(\w+)\s*=>\s*\2!',
            re.DOTALL
        )

        fields_with_getters = {}  # field_name -> (type, getter_name)
        for match in field_getter_pattern.finditer(class_content):
            field_type = match.group(1)
            field_name = match.group(2)
            getter_name = match.group(3)
            fields_with_getters[field_name] = (field_type, getter_name)

        if not fields_with_getters:
            return violations

        # Find where fields are cached (typically in build)
        field_caching_locations = {}  # field_name -> line_number
        for field_name in fields_with_getters.keys():
            # Pattern: _fieldName ??= ref.read(...)
            caching_pattern = re.compile(rf'{re.escape(field_name)}\s*\?\?=\s*ref\.read\(')
            match = caching_pattern.search(class_content)
            if match:
                line_num = class_content[:match.start()].count('\n')
                field_caching_locations[field_name] = line_num

        # Find initState() method
        initstate_pattern = re.compile(r'void\s+initState\s*\(\s*\)\s*\{', re.DOTALL)
        initstate_match = initstate_pattern.search(class_content)

        if not initstate_match:
            return violations

        initstate_start = initstate_match.end()
        initstate_end = self._find_method_end(class_content, initstate_start)
        initstate_body = class_content[initstate_start:initstate_end]

        # Strip comments from initState body to avoid false positives from comments
        initstate_body_stripped, _ = self._strip_comments(initstate_body)

        # Find methods called DIRECTLY from initState (not inside callbacks)
        # Exclude methods called inside addPostFrameCallback

        # First, remove addPostFrameCallback blocks from initstate_body
        initstate_body_no_callbacks = initstate_body_stripped
        callback_pattern = re.compile(r'addPostFrameCallback\s*\([^)]*\)\s*\{', re.DOTALL)
        callback_match = callback_pattern.search(initstate_body_no_callbacks)
        if callback_match:
            # Find end of callback block
            callback_start = callback_match.end()
            callback_end = self._find_block_end(initstate_body_no_callbacks, callback_start)
            # Remove the callback block content
            initstate_body_no_callbacks = (
                initstate_body_no_callbacks[:callback_match.start()] +
                initstate_body_no_callbacks[callback_end+1:]
            )

        # Pattern: methodName() or _methodName() or await methodName()
        method_call_pattern = re.compile(r'(?:await\s+)?([_\w]+)\s*\(')
        called_methods = set()
        for match in method_call_pattern.finditer(initstate_body_no_callbacks):
            method_name = match.group(1)
            # Filter out common built-in methods and initState itself
            if method_name not in ['super', 'setState', 'addPostFrameCallback', 'addListener', 'initState']:
                called_methods.add(method_name)

        # Check each field to see if its getter is accessed before caching
        for field_name, (field_type, getter_name) in fields_with_getters.items():
            # Check if field is cached (if not, it's a different issue)
            if field_name not in field_caching_locations:
                continue

            caching_line = field_caching_locations[field_name]

            # Check if getter is used directly in initState (excluding callbacks)
            if re.search(rf'\b{getter_name}\b', initstate_body_no_callbacks):
                abs_line = full_content[:class_start + initstate_match.start()].count('\n') + 1
                snippet_start = max(0, abs_line - 1)
                snippet_end = min(len(lines), abs_line + 20)
                snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                violations.append(Violation(
                    file_path=str(file_path),
                    class_name=class_name,
                    violation_type=ViolationType.INITSTATE_FIELD_ACCESS_BEFORE_CACHING,
                    line_number=abs_line,
                    context=f"initState() directly accesses {getter_name} before {field_name} is cached in build()",
                    code_snippet=snippet,
                    fix_instructions=f"""CRITICAL: Widget lifecycle timing bug - Null pointer exception risk

❌ VIOLATION: initState() accesses {getter_name} but {field_name} only cached in build()
   Line {abs_line}: initState() uses {getter_name}
   Field {field_name} is cached at line {class_start + caching_line} (in build method)

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
See also: Flutter widget lifecycle documentation"""
                ))
                continue

            # Check methods called from initState to see if they use the getter
            for method_name in called_methods:
                # Find the method definition
                method_pattern = re.compile(
                    rf'(?:Future<[^>]*>|void)\s+{method_name}\s*\([^)]*\)\s+(?:async\s+)?\{{',
                    re.DOTALL
                )
                method_match = method_pattern.search(class_content)

                if not method_match:
                    continue

                method_start = method_match.end()
                method_end = self._find_method_end(class_content, method_start)
                method_body = class_content[method_start:method_end]

                # Check if this method uses the getter
                if re.search(rf'\b{getter_name}\b', method_body):
                    abs_line = full_content[:class_start + initstate_match.start()].count('\n') + 1
                    snippet_start = max(0, abs_line - 1)
                    snippet_end = min(len(lines), abs_line + 20)
                    snippet = '\n'.join(f"  {i+1:4d} | {lines[i]}" for i in range(snippet_start, snippet_end))

                    violations.append(Violation(
                        file_path=str(file_path),
                        class_name=class_name,
                        violation_type=ViolationType.INITSTATE_FIELD_ACCESS_BEFORE_CACHING,
                        line_number=abs_line,
                        context=f"initState() calls {method_name}() which accesses {getter_name} before {field_name} is cached",
                        code_snippet=snippet,
                        fix_instructions=f"""CRITICAL: Widget lifecycle timing bug - Null pointer exception risk

❌ VIOLATION: initState() → {method_name}() → accesses {getter_name} before caching
   Line {abs_line}: initState() calls {method_name}()
   Method {method_name}() uses {getter_name} getter
   Field {field_name} is only cached at line {class_start + caching_line} (in build method)

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

Reference: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/GUIDE.md"""
                    ))

        return violations

    def _infer_type_from_provider(self, provider_expr: str) -> str:
        """
        Infer the correct type from a provider expression.

        Examples:
        - 'invitationWizardStateProvider.notifier' -> 'InvitationWizardState'
        - 'scoreboardProvider(gameId).notifier' -> 'Scoreboard'
        - 'myLoggerProvider' -> 'MyLogger'
        """
        # Remove .notifier suffix if present
        if '.notifier' in provider_expr:
            # Pattern: someProviderName.notifier -> SomeProviderName class
            provider_name = provider_expr.split('.')[0]
            # Remove 'Provider' suffix if present
            if provider_name.endswith('Provider'):
                provider_name = provider_name[:-8]  # Remove 'Provider'

            # Handle family providers: scoreboardProvider(gameId) -> scoreboardProvider
            provider_name = re.sub(r'\([^)]*\)', '', provider_name)

            # Convert to PascalCase class name
            # Examples:
            # - invitationWizardState -> InvitationWizardState
            # - scoreboard -> Scoreboard
            # - footballControls -> FootballControls
            class_name = provider_name[0].upper() + provider_name[1:]

            return class_name
        else:
            # Provider without .notifier - return the provider's data type
            # This is harder to infer, suggest checking the provider definition
            return "Check provider definition for return type"

    def _resolve_variable_to_class(self, variable_name: str, class_content: str, full_content: str = None) -> str:
        """Resolve a variable name to its class type using cross-file database"""
        search_content = full_content if full_content else class_content

        # Pattern 1: final Type variable = ref.read(provider(...).notifier) - WITH parameters
        var_decl_typed_param = re.compile(rf'(\w+)\s+{variable_name}\s*=\s*ref\.read\((\w+)\([^)]*\)\.notifier\)')
        match = var_decl_typed_param.search(search_content)
        if match:
            provider_name = match.group(2)
            return self.provider_to_class.get(provider_name, None)

        # Pattern 2: final variable = ref.read(someProvider(...).notifier) - WITH parameters
        var_decl_simple_param = re.compile(rf'final\s+{variable_name}\s*=\s*ref\.read\((\w+)\([^)]*\)\.notifier\)')
        match = var_decl_simple_param.search(search_content)
        if match:
            provider_name = match.group(1)
            return self.provider_to_class.get(provider_name, None)

        # Pattern 3: final Type variable = ref.read(provider.notifier) - WITHOUT parameters
        var_decl_typed = re.compile(rf'(\w+)\s+{variable_name}\s*=\s*ref\.read\((\w+)\.notifier\)')
        match = var_decl_typed.search(search_content)
        if match:
            provider_name = match.group(2)
            return self.provider_to_class.get(provider_name, None)

        # Pattern 4: final variable = ref.read(someProvider.notifier) - WITHOUT parameters
        var_decl_simple = re.compile(rf'final\s+{variable_name}\s*=\s*ref\.read\((\w+)\.notifier\)')
        match = var_decl_simple.search(search_content)
        if match:
            provider_name = match.group(1)
            return self.provider_to_class.get(provider_name, None)

        # Pattern 3: variable = ref.read(someProvider.notifier) (assignment without final)
        var_assign = re.compile(rf'{variable_name}\s*=\s*ref\.read\((\w+)\.notifier\)')
        match = var_assign.search(search_content)
        if match:
            provider_name = match.group(1)
            return self.provider_to_class.get(provider_name, None)

        # Pattern 4: ref.read(someProvider.notifier).someMethod() - inline call
        # Variable might be result of inline ref.read
        inline_pattern = re.compile(rf'{variable_name}\s*=\s*ref\.read\((\w+)\)')
        match = inline_pattern.search(search_content)
        if match:
            provider_name = match.group(1)
            # Remove .notifier if present
            provider_name = provider_name.replace('.notifier', '')
            return self.provider_to_class.get(provider_name, None)

        return None

    def _find_methods_using_ref(self, class_content: str) -> Set[str]:
        """Find all method names in a class that use ref.read/watch/listen"""
        methods_with_ref = set()

        # Find all method definitions (including FutureOr for Riverpod build methods)
        method_pattern = re.compile(r'(?:Future<[^>]+>|FutureOr<[^>]+>|void|[A-Z]\w+)\s+(\w+)\s*\([^)]*\)\s*(?:async\s*)?\{')

        for method_match in method_pattern.finditer(class_content):
            method_name = method_match.group(1)
            method_start = method_match.end() - 1  # Start at {
            method_end = self._find_method_end(class_content, method_start + 1)
            method_body = class_content[method_start:method_end]

            # Remove comments to avoid false positives from comments containing "ref.read"
            method_body_no_comments = self._remove_comments(method_body)

            # Check if this method uses ref operations (excluding comments)
            if re.search(r'\bref\.(read|watch|listen)\(', method_body_no_comments):
                methods_with_ref.add(method_name)

        return methods_with_ref

    def _remove_comments(self, code: str) -> str:
        """Remove single-line and multi-line comments from code"""
        # Remove multi-line comments /* ... */
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        # Remove single-line comments //...
        code = re.sub(r'//.*?$', '', code, flags=re.MULTILINE)
        return code

    def _find_callback_end(self, content: str, callback_start: int) -> int:
        """Find the end of a callback function (closure)"""
        # Skip to first {
        brace_start = content.find('{', callback_start)
        if brace_start == -1:
            return len(content)

        brace_count = 1
        for i in range(brace_start + 1, len(content)):
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    return i + 1

        return len(content)

    def _find_statement_end(self, content: str, statement_start: int) -> int:
        """Find the end of a statement (ends at semicolon or closing paren at depth 0)"""
        paren_depth = 0
        brace_depth = 0

        for i in range(statement_start, len(content)):
            char = content[i]

            if char == '(':
                paren_depth += 1
            elif char == ')':
                paren_depth -= 1
            elif char == '{':
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1
            elif char == ';' and paren_depth == 0 and brace_depth == 0:
                return i

            # Also end at closing paren if we started inside parens
            if paren_depth == 0 and brace_depth == 0 and i > statement_start:
                # Check for end of function call
                if content[i:i+2] == ');':
                    return i + 1

        return len(content)

    def _find_method_end(self, content: str, method_start: int) -> int:
        """Find the end of a method"""
        brace_count = 1
        for i in range(method_start, len(content)):
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    return i
        return len(content)

    def _find_block_end(self, content: str, block_start: int) -> int:
        """Find the end of a block (catch, try, etc.)"""
        brace_count = 1
        for i in range(block_start, len(content)):
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    return i
        return len(content)

    def _has_significant_code_after_await(self, next_lines: str) -> bool:
        """
        Check if there's significant code after an await that requires a mounted check.

        Returns True ONLY if there's:
        - ref operations (ref.read/watch/listen/invalidate)
        - state assignments or access (state = or state.)

        Returns False for:
        - closing braces
        - whitespace/comments
        - void return (just 'return;')
        - return with value (safe - no ref access)
        - method calls on the await result (safe - no ref access)
        - conditional checks on await result (safe - no ref access)

        The key insight: We only need mounted check if ref or state is accessed AFTER the await.
        Simply using the await's result value does not require a mounted check.
        """
        # Strip whitespace and check if empty
        stripped = next_lines.strip()
        if not stripped:
            return False

        # Only closing braces
        if re.match(r'^}+\s*$', stripped):
            return False

        # Check for ref operations (read, watch, listen, invalidate)
        if re.search(r'ref\.(read|watch|listen|invalidate)', next_lines):
            return True

        # Check for state assignment or access
        if re.search(r'\bstate\s*[.=]', next_lines):
            return True

        # No ref/state access found - safe
        return False

    def _get_field_caching_fix(self, field_name: str, async_methods: List[str], is_consumer_state: bool = False) -> str:
        """Get fix instructions for field caching violation"""
        base_name = field_name[1:]
        mounted_check = "if (!mounted) return;" if is_consumer_state else "if (!ref.mounted) return;"
        return f"""1. Remove: {field_name} field and getter
2. In async methods ({', '.join(async_methods)}), use:
   {mounted_check}
   final {base_name} = ref.read(provider);
   await operation();
   {mounted_check}
   {base_name}.method();"""

    def _get_lazy_getter_fix(self, getter_name: str) -> str:
        """Get fix instructions for lazy getter violation"""
        return f"""1. Remove: lazy getter 'get {getter_name} => ref.read(...)'
2. In async methods, read just-in-time:
   if (!ref.mounted) return;
   final {getter_name} = ref.read(provider);"""

    def _get_async_getter_fix(self, field_name: str) -> str:
        """Get fix instructions for async getter violation"""
        base_name = field_name[1:]
        return f"""1. Remove: {field_name} field and async getter
2. In async methods, use:
   if (!ref.mounted) return;
   final {base_name} = await ref.read(provider.future);
   if (!ref.mounted) return;"""

    def _get_ref_read_before_mounted_fix(self) -> str:
        """Get fix instructions for ref operation (read/watch/listen) before mounted check"""
        return """Add at method entry BEFORE any ref operation (read/watch/listen):
   if (!ref.mounted) return;
   final dep = ref.read(provider);
   // OR
   ref.watch(someProvider);
   // OR
   ref.listen(someProvider, (prev, next) { ... });"""

    def _get_missing_mounted_after_await_fix(self) -> str:
        """Get fix instructions for missing mounted after await"""
        return """Add after EVERY await:
   await operation();
   if (!ref.mounted) return;"""

    def _get_missing_mounted_in_catch_fix(self) -> str:
        """Get fix instructions for missing mounted in catch"""
        return """Add at start of catch block:
   catch (e, st) {
     if (!ref.mounted) return;
     final logger = ref.read(myLoggerProvider);
     logger.logError(...);
   }"""

    def _get_ref_in_lifecycle_fix(self, ref_or_method: str, is_direct: bool = True, is_cross_class: bool = False, callback_type: str = "ref.onDispose") -> str:
        """Get fix instructions for ref operations in lifecycle callbacks"""
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

    def scan_directory(self, directory: Path, pattern: str = "**/*.dart") -> List[Violation]:
        """Scan all Dart files in a directory with comprehensive cross-file analysis"""
        violations = []

        dart_files = list(directory.glob(pattern))
        dart_files = [f for f in dart_files if f.is_file() and not str(f).endswith('.g.dart') and not str(f).endswith('.freezed.dart')]
        total_files = len(dart_files)

        if self.verbose:
            print(f"\n📁 Scanning {total_files} Dart files in {directory}...")

        # PASS 1: Build comprehensive cross-file reference database
        if self.verbose:
            print(f"🔍 PASS 1: Building cross-file reference database...")

        for dart_file in dart_files:
            self._build_ref_database(dart_file)

        if self.verbose:
            print(f"   ✅ Indexed {len(self.methods_using_ref)} classes")
            print(f"   ✅ Mapped {len(self.provider_to_class)} providers to classes")
            total_methods = sum(len(methods) for methods in self.methods_using_ref.values())
            print(f"   ✅ Found {total_methods} methods using ref operations")

        # PASS 1.5: Build complete method database (all methods with metadata)
        if self.verbose:
            print(f"🔍 PASS 1.5: Building complete method database...")

        for dart_file in dart_files:
            self._build_method_database(dart_file)

        if self.verbose:
            print(f"   ✅ Indexed {len(self.all_methods)} total methods")

        # PASS 2: Build async callback call-graph
        if self.verbose:
            print(f"🔍 PASS 2: Tracing async callback call-graph...")

        for dart_file in dart_files:
            self._trace_async_callbacks(dart_file)

        if self.verbose:
            print(f"   ✅ Found {len(self.methods_called_from_async)} methods called directly from async contexts")

        # PASS 2.5: Propagate async context transitively (recursive call-graph)
        if self.verbose:
            print(f"🔍 PASS 2.5: Propagating async context transitively...")

        self._propagate_async_context_transitively()

        if self.verbose:
            print(f"   ✅ Total methods in async context (after propagation): {len(self.methods_called_from_async)}")

        # PASS 3: Scan for violations with full call-graph context
        if self.verbose:
            print(f"🔍 PASS 3: Scanning for violations with call-graph analysis...")

        scanned = 0
        for file_path in dart_files:
            scanned += 1
            if self.verbose and scanned % 50 == 0:
                print(f"   Progress: {scanned}/{total_files} files scanned...")

            file_violations = self.scan_file(file_path)
            violations.extend(file_violations)

        return violations

    def _build_ref_database(self, file_path: Path):
        """Build database of which classes/methods use ref operations (PASS 1)"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return

        # Pattern 1: Find all Riverpod provider classes
        provider_pattern = re.compile(r'class\s+(\w+)\s+extends\s+_\$(\w+)')

        for provider_match in provider_pattern.finditer(content):
            class_name = provider_match.group(1)
            class_start = provider_match.start()
            class_end = self._find_class_end(content, class_start)
            class_content = content[class_start:class_end]

            # Store class-to-file mapping
            self.class_to_file[class_name] = file_path

            # Find methods that use ref
            methods_with_ref = self._find_methods_using_ref(class_content)
            if methods_with_ref:
                self.methods_using_ref[class_name] = methods_with_ref

        # Pattern 2: Find all ConsumerStatefulWidget State classes
        consumer_state_pattern = re.compile(r'class\s+(\w+)\s+extends\s+ConsumerState<(\w+)>')

        for consumer_match in consumer_state_pattern.finditer(content):
            class_name = consumer_match.group(1)
            class_start = consumer_match.start()
            class_end = self._find_class_end(content, class_start)
            class_content = content[class_start:class_end]

            # Store class-to-file mapping
            self.class_to_file[class_name] = file_path

            # Find methods that use ref
            methods_with_ref = self._find_methods_using_ref(class_content)
            if methods_with_ref:
                self.methods_using_ref[class_name] = methods_with_ref

        # Find provider definitions and map to class names
        # Look for: final someProviderNameProvider = ...
        # Also look for: @riverpod annotations followed by class definition
        provider_annotation = re.compile(r'@[Rr]iverpod.*?\nclass\s+(\w+)\s+extends', re.DOTALL)
        for match in provider_annotation.finditer(content):
            class_name = match.group(1)

            # Generate provider name from class name following Riverpod codegen rules:
            # - XxxNotifier -> xxxProvider (remove "Notifier" suffix)
            # - XxxService -> xxxServiceProvider (keep "Service")
            # - Xxx -> xxxProvider
            base_name = class_name
            if class_name.endswith('Notifier'):
                base_name = class_name[:-8]  # Remove "Notifier"

            provider_name = base_name[0].lower() + base_name[1:] + 'Provider'
            self.provider_to_class[provider_name] = class_name

    def format_violation(self, violation: Violation) -> str:
        """Format a violation for display"""
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

    def print_summary(self, violations: List[Violation], path: Path):
        """Print comprehensive summary"""
        print(f"\n{'=' * 80}")
        print(f"🔍 RIVERPOD 3.0 COMPLIANCE SCAN COMPLETE")
        print(f"{'=' * 80}")
        print(f"📁 Scanned: {path}")
        print(f"🚨 Total violations: {len(violations)}")
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
                print(self.format_violation(violation))

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


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Comprehensive Riverpod 3.0 compliance scanner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 riverpod_3_scanner.py lib
  python3 riverpod_3_scanner.py lib/presentation
  python3 riverpod_3_scanner.py lib/data/managers/schedule_manager.dart
  python3 riverpod_3_scanner.py lib --verbose

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
        help='Path to scan (file or directory, default: lib)'
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable verbose output'
    )
    parser.add_argument(
        '--pattern',
        type=str,
        default='**/*.dart',
        help='Glob pattern for files to scan (default: **/*.dart)'
    )

    args = parser.parse_args()

    scanner = RiverpodScanner(verbose=args.verbose)
    path = Path(args.path)

    if not path.exists():
        print(f"❌ Error: Path does not exist: {path}", file=sys.stderr)
        sys.exit(2)

    if path.is_file():
        violations = scanner.scan_file(path)
    else:
        violations = scanner.scan_directory(path, args.pattern)

    scanner.print_summary(violations, path)

    if violations:
        sys.exit(1)  # Exit with error code
    else:
        sys.exit(0)  # Success


if __name__ == '__main__':
    main()
