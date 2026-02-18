"""
Multi-pass call-graph analysis module for the Riverpod 3.0 Safety Scanner.

Implements Passes 1, 1.5, 2, and 2.5 of the cross-file analysis pipeline:
  - Pass 1:   Build ref database (which classes/methods use ref operations)
  - Pass 1.5: Build complete method database with metadata
  - Pass 2:   Trace async callbacks (which methods are called from async contexts)
  - Pass 2.5: Propagate async context transitively through call graph

Author: Steven Day
Company: DayLight Creative Technologies
License: MIT
"""

import re
from pathlib import Path
from typing import Dict, Set, List, Optional, Tuple

from .models import MethodKey, MethodMetadata
from .utils import (
    FileCache, find_matching_brace, find_async_methods, find_methods_using_ref,
    resolve_variable_to_class, resolve_method_calls_in_body, remove_comments,
    RE_PROVIDER_CLASS, RE_CONSUMER_STATE_CLASS, RE_METHOD, RE_REF_READ,
    RE_MOUNTED_PROVIDER, RE_MOUNTED_WIDGET, RE_MOUNTED_ANY,
    RE_METHOD_CALL, RE_CALLBACK_START, RE_AWAIT, RE_RIVERPOD_ANNOTATION,
    SKIP_METHODS, FRAMEWORK_LIFECYCLE_METHODS, ASYNC_CALLBACK_PARAMS,
)


# ---------------------------------------------------------------------------
# AnalysisContext — cross-file analysis state
# ---------------------------------------------------------------------------

class AnalysisContext:
    """Holds ALL cross-file analysis state across all passes.

    Each pass reads from and writes to this shared context so that later
    passes have full visibility into earlier results without re-reading files.
    """

    def __init__(self, file_cache: FileCache, verbose: bool = False):
        self.file_cache = file_cache
        self.verbose = verbose

        # Pass 1
        self.methods_using_ref: Dict[str, Set[str]] = {}   # class_name -> method names
        self.class_to_file: Dict[str, Path] = {}            # class_name -> file path
        self.provider_to_class: Dict[str, str] = {}         # provider_name -> class_name

        # Pass 1.5
        self.all_methods: Dict[MethodKey, MethodMetadata] = {}
        self._class_method_index: Dict[Tuple[str, str], MethodKey] = {}  # (class, method) -> key

        # Pass 2 + 2.5
        self.methods_called_from_async: Set[MethodKey] = set()

    # -- Secondary-index helpers ------------------------------------------

    def add_method(self, key: MethodKey, metadata: MethodMetadata) -> None:
        """Add a method with secondary indexing for O(1) lookups."""
        self.all_methods[key] = metadata
        _, class_name, method_name = key
        self._class_method_index[(class_name, method_name)] = key

    def lookup_method(self, class_name: str, method_name: str) -> Optional[MethodKey]:
        """O(1) lookup by class and method name."""
        return self._class_method_index.get((class_name, method_name))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_all_passes(dart_files: List[Path], ctx: AnalysisContext) -> None:
    """Execute all four analysis passes in order.

    Args:
        dart_files: Pre-filtered list of .dart files (no .g.dart / .freezed.dart).
        ctx: Shared analysis context that accumulates cross-file state.
    """
    # PASS 1: Build cross-file reference database
    if ctx.verbose:
        print(f"\U0001f50d PASS 1: Building cross-file reference database...")

    for dart_file in dart_files:
        _pass1_build_ref_database(dart_file, ctx)

    if ctx.verbose:
        print(f"   \u2705 Indexed {len(ctx.methods_using_ref)} classes")
        print(f"   \u2705 Mapped {len(ctx.provider_to_class)} providers to classes")
        total_methods = sum(len(methods) for methods in ctx.methods_using_ref.values())
        print(f"   \u2705 Found {total_methods} methods using ref operations")

    # PASS 1.5: Build complete method database
    if ctx.verbose:
        print(f"\U0001f50d PASS 1.5: Building complete method database...")

    for dart_file in dart_files:
        _pass15_build_method_database(dart_file, ctx)

    if ctx.verbose:
        print(f"   \u2705 Indexed {len(ctx.all_methods)} total methods")

    # PASS 2: Build async callback call-graph
    if ctx.verbose:
        print(f"\U0001f50d PASS 2: Tracing async callback call-graph...")

    for dart_file in dart_files:
        _pass2_trace_async_callbacks(dart_file, ctx)

    if ctx.verbose:
        print(f"   \u2705 Found {len(ctx.methods_called_from_async)} methods called directly from async contexts")

    # PASS 2.5: Propagate async context transitively
    if ctx.verbose:
        print(f"\U0001f50d PASS 2.5: Propagating async context transitively...")

    _pass25_propagate_async_context(ctx)

    if ctx.verbose:
        print(f"   \u2705 Total methods in async context (after propagation): {len(ctx.methods_called_from_async)}")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _extract_class_content(content: str, class_start: int) -> str:
    """Extract class content from a class declaration start position.

    Finds the opening '{' of the class body, then uses find_matching_brace to
    locate the matching '}'. Returns content[class_start:closing_brace + 1] so
    the result includes the full class declaration through the closing brace.
    This matches the behavior of the original scanner._find_class_end().

    Args:
        content: The full file source code.
        class_start: Position of the 'class' keyword.

    Returns:
        The class source from 'class' through closing '}'.
    """
    brace_pos = content.find('{', class_start)
    if brace_pos == -1:
        return content[class_start:]
    # find_matching_brace expects position after '{', returns position of '}'
    closing_brace = find_matching_brace(content, brace_pos + 1)
    return content[class_start:closing_brace + 1]


def _find_method_body(class_content: str, method_match_end: int) -> str:
    """Extract method body from a method match end position.

    The regex match ends right after the opening '{'. find_matching_brace
    is called with the position after '{' and returns the position of '}'.
    The body is the content between '{' and '}' (exclusive of both).
    This matches the behavior of the original scanner._find_method_end().

    Args:
        class_content: Source code of the enclosing class.
        method_match_end: Position right after the opening '{' from the regex match.

    Returns:
        The method body text (excludes the opening and closing braces).
    """
    closing_brace = find_matching_brace(class_content, method_match_end)
    return class_content[method_match_end:closing_brace]


# ---------------------------------------------------------------------------
# Pass 1 — Build ref database
# ---------------------------------------------------------------------------

def _pass1_build_ref_database(file_path: Path, ctx: AnalysisContext) -> None:
    """PASS 1: Build database of which classes/methods use ref operations.

    Indexes every Riverpod provider class and ConsumerState class found in
    *file_path*.  For each class it records:
      - class_to_file mapping
      - methods_using_ref mapping (methods that call ref.read/watch/listen)
      - provider_to_class mapping (from @riverpod annotations)
    """
    content = ctx.file_cache.read_text(file_path)
    if content is None:
        return

    # --- Riverpod provider classes (extends _$ClassName) ---
    for provider_match in RE_PROVIDER_CLASS.finditer(content):
        class_name = provider_match.group(1)
        class_content = _extract_class_content(content, provider_match.start())

        ctx.class_to_file[class_name] = file_path

        methods_with_ref = find_methods_using_ref(class_content)
        if methods_with_ref:
            ctx.methods_using_ref[class_name] = methods_with_ref

    # --- ConsumerStatefulWidget State classes (extends ConsumerState<T>) ---
    for consumer_match in RE_CONSUMER_STATE_CLASS.finditer(content):
        class_name = consumer_match.group(1)
        class_content = _extract_class_content(content, consumer_match.start())

        ctx.class_to_file[class_name] = file_path

        methods_with_ref = find_methods_using_ref(class_content)
        if methods_with_ref:
            ctx.methods_using_ref[class_name] = methods_with_ref

    # --- Provider annotations -> class name mapping ---
    for match in RE_RIVERPOD_ANNOTATION.finditer(content):
        class_name = match.group(1)

        # Generate provider name from class name following Riverpod codegen rules:
        # - XxxNotifier -> xxxProvider (remove "Notifier" suffix)
        # - XxxService -> xxxServiceProvider (keep "Service")
        # - Xxx -> xxxProvider
        base_name = class_name
        if class_name.endswith('Notifier'):
            base_name = class_name[:-8]  # Remove "Notifier"

        provider_name = base_name[0].lower() + base_name[1:] + 'Provider'
        ctx.provider_to_class[provider_name] = class_name


# ---------------------------------------------------------------------------
# Pass 1.5 — Build method database
# ---------------------------------------------------------------------------

def _pass15_build_method_database(file_path: Path, ctx: AnalysisContext) -> None:
    """PASS 1.5: Build complete database of all methods with metadata.

    Stores (file, class, method) -> MethodMetadata for every method found in
    Riverpod provider and ConsumerState classes.
    """
    content = ctx.file_cache.read_text(file_path)
    if content is None:
        return

    for pattern, is_consumer in [(RE_PROVIDER_CLASS, False), (RE_CONSUMER_STATE_CLASS, True)]:
        for class_match in pattern.finditer(content):
            class_name = class_match.group(1)
            class_start = class_match.start()
            class_content = _extract_class_content(content, class_start)

            # Determine mounted pattern for this class type
            mounted_pattern = RE_MOUNTED_WIDGET if is_consumer else RE_MOUNTED_PROVIDER

            # Find all methods (both async and sync)
            for method_match in RE_METHOD.finditer(class_content):
                method_name = method_match.group(1)

                # Skip getters (different pattern) — check region around match in full content
                lookback_start = max(0, method_match.start() - 20)
                lookback_end = method_match.start() + 20
                lookback_region = content[max(0, class_start + lookback_start):class_start + lookback_end]
                if 'get ' in lookback_region:
                    continue

                method_body = _find_method_body(class_content, method_match.end())

                # Check metadata
                sig_start = max(0, method_match.start() - 50)
                full_signature = class_content[sig_start:method_match.end() + 20]
                is_async = bool(re.search(r'\basync\b', full_signature))
                has_ref_read = bool(RE_REF_READ.search(method_body))

                # Check if mounted appears BEFORE first ref.read()
                has_mounted_check = False
                if has_ref_read:
                    ref_read_matches = list(RE_REF_READ.finditer(method_body))
                    if ref_read_matches:
                        first_ref_read_pos = ref_read_matches[0].start()
                        before_first_ref_read = method_body[:first_ref_read_pos]
                        has_mounted_check = bool(mounted_pattern.search(before_first_ref_read))

                is_lifecycle = method_name in FRAMEWORK_LIFECYCLE_METHODS

                key: MethodKey = (str(file_path), class_name, method_name)
                metadata = MethodMetadata(
                    has_ref_read=has_ref_read,
                    has_mounted_check=has_mounted_check,
                    is_async=is_async,
                    is_lifecycle_method=is_lifecycle,
                    method_body=method_body,
                    is_consumer_state=is_consumer,
                )
                ctx.add_method(key, metadata)


# ---------------------------------------------------------------------------
# Pass 2 — Trace async callbacks
# ---------------------------------------------------------------------------

def _pass2_trace_async_callbacks(file_path: Path, ctx: AnalysisContext) -> None:
    """PASS 2: Trace which methods are called from async contexts.

    Detects:
      1. Methods called directly in async methods (after await)
      2. Methods called in async callback parameters (onCompletion:, builder:, etc.)
      3. Methods called in stream.listen() callbacks
      4. Methods called in Timer/Future.delayed callbacks
      5. Methods called in addPostFrameCallback

    Populates: ctx.methods_called_from_async
    """
    content = ctx.file_cache.read_text(file_path)
    if content is None:
        return

    # Process both Riverpod provider and ConsumerState classes
    for pattern in [RE_PROVIDER_CLASS, RE_CONSUMER_STATE_CLASS]:
        for class_match in pattern.finditer(content):
            class_name = class_match.group(1)
            class_content = _extract_class_content(content, class_match.start())

            # Run all four sub-traces — all share the same content (read ONCE)
            _trace_async_method_calls(file_path, class_name, class_content, content, ctx)
            _trace_callback_parameter_calls(file_path, class_name, class_content, content, ctx)
            _trace_stream_listen_calls(file_path, class_name, class_content, content, ctx)
            _trace_deferred_calls(file_path, class_name, class_content, content, ctx)


# -- Sub-trace 1: Async method calls (after await) -------------------------

def _trace_async_method_calls(
    file_path: Path,
    class_name: str,
    class_content: str,
    full_file_content: str,
    ctx: AnalysisContext,
) -> None:
    """Find all method calls inside async methods (after await statements)."""
    # Find all async methods (including FutureOr for Riverpod build methods)
    async_pattern = re.compile(
        r'(?:Future<[^>]+>|FutureOr<[^>]+>|Stream<[^>]+>)\s+(\w+)\s*\([^)]*\)\s*async\s*\{',
        re.DOTALL,
    )

    for async_match in async_pattern.finditer(class_content):
        method_name = async_match.group(1)
        method_body = _find_method_body(class_content, async_match.end())

        # Find all 'await' statements
        await_positions = [m.start() for m in RE_AWAIT.finditer(method_body)]

        # For each await, find method calls that come AFTER it
        for await_pos in await_positions:
            after_await = method_body[await_pos:]

            # Find next mounted check (if any)
            mounted_check_match = RE_MOUNTED_ANY.search(after_await)

            # Danger zone: code between await and next mounted check (or end)
            search_end = mounted_check_match.start() if mounted_check_match else len(after_await)
            danger_zone = after_await[:search_end]

            # Resolve all method calls in the danger zone
            resolve_method_calls_in_body(
                danger_zone, file_path, class_name, class_content,
                full_file_content, ctx,
            )


# -- Sub-trace 2: Callback parameter calls ---------------------------------

def _trace_callback_parameter_calls(
    file_path: Path,
    class_name: str,
    class_content: str,
    full_file_content: str,
    ctx: AnalysisContext,
) -> None:
    """Find methods called inside callback parameters (onCompletion:, builder:, etc.)."""
    for callback_match in RE_CALLBACK_START.finditer(class_content):
        param_name = callback_match.group(1)

        # Find the matching closing brace — callback_match.end() is right after '{'
        callback_body = _find_method_body(class_content, callback_match.end())

        # Check if this callback is in an async context
        callback_pos = callback_match.start()
        before_callback = class_content[max(0, callback_pos - 200):callback_pos]

        # If 'await' appears within 200 chars before callback, this is async context
        has_await_before = bool(re.search(r'\bawait\s+\w+', before_callback))

        # Also check if callback contains await (callback is async)
        has_await_inside = bool(RE_AWAIT.search(callback_body))

        if has_await_before or has_await_inside or param_name in ASYNC_CALLBACK_PARAMS:
            resolve_method_calls_in_body(
                callback_body, file_path, class_name, class_content,
                full_file_content, ctx,
            )


# -- Sub-trace 3: Stream .listen() calls -----------------------------------

def _trace_stream_listen_calls(
    file_path: Path,
    class_name: str,
    class_content: str,
    full_file_content: str,
    ctx: AnalysisContext,
) -> None:
    """Find methods called inside .listen() callbacks."""
    listen_pattern = re.compile(
        r'\.listen\s*\(\s*\([^)]*\)\s*\{([^}]+)\}',
        re.DOTALL,
    )

    for listen_match in listen_pattern.finditer(class_content):
        callback_body = listen_match.group(1)

        resolve_method_calls_in_body(
            callback_body, file_path, class_name, class_content,
            full_file_content, ctx,
        )


# -- Sub-trace 4: Deferred calls (Timer / Future.delayed / postFrame) ------

def _trace_deferred_calls(
    file_path: Path,
    class_name: str,
    class_content: str,
    full_file_content: str,
    ctx: AnalysisContext,
) -> None:
    """Find methods called from Timer, Future.delayed, addPostFrameCallback."""
    # Pattern 1: Timer(duration, () { method(); })
    timer_pattern = re.compile(
        r'Timer(?:\.periodic)?\s*\([^,]+,\s*\([^)]*\)\s*\{([^}]+)\}',
        re.DOTALL,
    )

    # Pattern 2: Future.delayed(duration, () { method(); })
    delayed_pattern = re.compile(
        r'Future\.delayed\s*\([^,]+,\s*\([^)]*\)\s*\{([^}]+)\}',
        re.DOTALL,
    )

    # Pattern 3: addPostFrameCallback((_) { method(); })
    postframe_pattern = re.compile(
        r'addPostFrameCallback\s*\(\s*\([^)]*\)\s*\{([^}]+)\}',
        re.DOTALL,
    )

    for deferred_pattern in [timer_pattern, delayed_pattern, postframe_pattern]:
        for match in deferred_pattern.finditer(class_content):
            callback_body = match.group(1)

            resolve_method_calls_in_body(
                callback_body, file_path, class_name, class_content,
                full_file_content, ctx,
            )


# ---------------------------------------------------------------------------
# Pass 2.5 — Propagate async context transitively
# ---------------------------------------------------------------------------

def _pass25_propagate_async_context(ctx: AnalysisContext) -> None:
    """PASS 2.5: Propagate async context transitively through call graph.

    If method A calls method B, and B is in async context, then A is also
    in async context (recursively).

    Uses fixed-point iteration until no new methods are added.
    Max 100 iterations as a safety limit.
    """
    iteration = 0
    while True:
        iteration += 1
        initial_count = len(ctx.methods_called_from_async)

        if ctx.verbose:
            print(f"   \U0001f504 Iteration {iteration}: {initial_count} methods in async context")

        # For each method in all_methods
        for method_key, method_data in ctx.all_methods.items():
            # Skip if already marked as async context
            if method_key in ctx.methods_called_from_async:
                continue

            method_body = method_data.method_body
            file_path_str, class_name, method_name = method_key

            # Find all method calls in this method's body
            for call_match in RE_METHOD_CALL.finditer(method_body):
                called_method = call_match.group(2) if call_match.group(2) else call_match.group(3)

                if not called_method or called_method in SKIP_METHODS:
                    continue

                # Check if called method is in async context — try same class first
                called_key = (file_path_str, class_name, called_method)

                if called_key in ctx.methods_called_from_async:
                    # This method calls a method that's in async context —
                    # therefore this method is also in async context
                    ctx.methods_called_from_async.add(method_key)
                    break

        # Fixed-point reached?
        if len(ctx.methods_called_from_async) == initial_count:
            if ctx.verbose:
                print(f"   \u2705 Fixed-point reached after {iteration} iterations")
            break

        if iteration > 100:  # Safety limit
            if ctx.verbose:
                print(f"   \u26a0\ufe0f  Stopped after 100 iterations")
            break
