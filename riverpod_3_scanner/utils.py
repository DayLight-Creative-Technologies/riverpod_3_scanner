"""Shared utilities for the Riverpod 3.0 Safety Scanner.

Contains pre-compiled regex patterns, constant sets, file caching, string-aware
Dart parsing, comment stripping, method discovery helpers, type inference,
call resolution, snippet extraction, and suppression comment support.

All regex patterns are compiled at module level to avoid redundant compilation
inside hot-loop methods.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .models import MethodKey, MethodMetadata


# =============================================================================
# 1. Pre-compiled regex patterns (module-level constants)
# =============================================================================

# Class detection patterns
RE_PROVIDER_CLASS = re.compile(r'class\s+(\w+)\s+extends\s+_\$(\w+)')
RE_CONSUMER_STATE_CLASS = re.compile(
    r'class\s+(\w+)\s+extends\s+ConsumerState<(\w+)>'
)
RE_CONSUMER_WIDGET_CLASS = re.compile(
    r'class\s+(\w+)\s+extends\s+ConsumerWidget'
)

# Async method signatures
RE_ASYNC_FUTURE = re.compile(
    r'Future<.+?>\s+(\w+)\s*\(.*?\)\s+async(?:\s|{)', re.DOTALL
)
RE_ASYNC_FUTUREOR = re.compile(
    r'FutureOr<.+?>\s+(\w+)\s*\(.*?\)\s+async(?:\s|{)', re.DOTALL
)
RE_ASYNC_STREAM = re.compile(
    r'Stream<.+?>\s+(\w+)\s*\(.*?\)\s+async\*(?:\s|{)', re.DOTALL
)

# General method pattern (both sync and async)
RE_METHOD = re.compile(
    r'(?:Future<[^>]+>|Stream<[^>]+>|void|bool|String|int|double|num|\w+\?)'
    r'\s+(\w+)\s*\([^)]*\)\s*(?:async\s*)?\{',
    re.DOTALL,
)

# Ref operation patterns
RE_REF_OPERATION = re.compile(r'ref\.(read|watch|listen)\(')
RE_REF_READ = re.compile(r'ref\.read\(')
RE_REF_ALL_OPERATIONS = re.compile(
    r'\bref\.'
    r'(read|watch|listen|invalidateSelf|invalidate|refresh|'
    r'notifyListeners|onDispose|onCancel|onResume|'
    r'onAddListener|onRemoveListener|state)'
    r'\s*[(\.]'
)

# Mounted check patterns
RE_MOUNTED_PROVIDER = re.compile(r'if\s*\(\s*!ref\.mounted\s*\)\s*return')
RE_MOUNTED_WIDGET = re.compile(r'if\s*\(\s*!mounted\s*\)\s*return')
RE_MOUNTED_ANY = re.compile(r'if\s*\(\s*!(?:ref\.)?mounted\s*\)\s*return')
RE_MOUNTED_CHECK_PROVIDER = re.compile(r'if\s*\(\s*!ref\.mounted\s*\)')
RE_MOUNTED_CHECK_WIDGET = re.compile(r'if\s*\(\s*!mounted\s*\)')
RE_MOUNTED_CHECK_BROAD = re.compile(
    r'if\s*\(\s*!?\s*(ref\.)?\s*mounted\s*\)'
)

# Method call detection
RE_METHOD_CALL = re.compile(
    r'(?:^|[^\w])(\w+)\.(\w+)\(|(?:^|[^\w])(\w+)\('
)

# Callback detection
RE_CALLBACK_START = re.compile(
    r'(\w+):\s*\([^)]*\)\s*(?:async\s*)?\{', re.DOTALL
)

# Await patterns
RE_AWAIT = re.compile(r'\bawait\s+')
RE_RETURN_AWAIT = re.compile(r'\breturn\s+await\s+')

# Riverpod annotation pattern
RE_RIVERPOD_ANNOTATION = re.compile(
    r'@[Rr]iverpod.*?\nclass\s+(\w+)\s+extends', re.DOTALL
)

# Field patterns
RE_GENERIC_NULLABLE_FIELD = re.compile(
    r'(\w+(?:<.+?>)?)\?\s+(_\w+);', re.DOTALL
)
RE_DYNAMIC_FIELD = re.compile(r'\bdynamic\s+(_\w+);')
RE_LATE_FINAL_FIELD = re.compile(
    r'late\s+final\s+(\w+(?:<.+?>)?)\??\s+(_\w+);', re.DOTALL
)
RE_VAR_FIELD = re.compile(r'\bvar\s+(_\w+);')

# Build method and widget helper patterns
RE_BUILD_METHOD = re.compile(
    r'(@override\s+)?Widget\s+build\s*\([^)]*\)\s*\{', re.DOTALL
)
RE_WIDGET_HELPER = re.compile(
    r'Widget\s+(_\w+)\s*\([^)]*\)\s*\{', re.DOTALL
)

# Suppression comment patterns
RE_IGNORE_LINE = re.compile(r'//\s*riverpod_scanner:ignore\b')
RE_IGNORE_FILE = re.compile(r'//\s*riverpod_scanner:ignore-file\b')


# =============================================================================
# 2. Constant sets
# =============================================================================

SKIP_METHODS: frozenset = frozenset({
    'read', 'watch', 'listen', 'mounted', 'setState',
})

FRAMEWORK_LIFECYCLE_METHODS: frozenset = frozenset({
    'initState', 'dispose', 'didUpdateWidget',
    'didChangeDependencies', 'deactivate', 'reassemble', 'build',
})

ASYNC_CALLBACK_PARAMS: frozenset = frozenset({
    'onCompletion', 'onComplete', 'onSuccess', 'onFailure', 'onError',
    'builder', 'onPressed', 'onTap', 'onLongPress', 'onChanged',
    'onSubmitted', 'onFieldSubmitted', 'onSaved', 'listener',
    'requiresGameCompletion', 'requiresStart', 'requiresResume',
})

EVENT_HANDLERS: List[str] = [
    'onTap', 'onPressed', 'onLongPress', 'onChanged', 'onSubmitted',
    'onSaved', 'onEditingComplete', 'onFieldSubmitted', 'onRefresh',
    'onPageChanged', 'onReorder', 'onAccept', 'onWillAccept', 'onEnd',
]


# =============================================================================
# 3. FileCache class
# =============================================================================

class FileCache:
    """Caches file contents to eliminate redundant disk reads across passes.

    The scanner reads the same file in multiple passes (PASS 1, 1.5, 2, 3).
    This cache ensures each file is read from disk exactly once.
    """

    def __init__(self) -> None:
        """Initialize an empty file cache."""
        self._text_cache: Dict[Path, str] = {}
        self._lines_cache: Dict[Path, List[str]] = {}

    def read_text(self, path: Path) -> str:
        """Read a file's full text content, returning cached copy if available.

        Args:
            path: Absolute path to the file.

        Returns:
            The file's text content.

        Raises:
            OSError: If the file cannot be read.
        """
        if path not in self._text_cache:
            self._text_cache[path] = path.read_text(encoding='utf-8')
        return self._text_cache[path]

    def read_lines(self, path: Path) -> List[str]:
        """Read a file's lines, returning cached copy if available.

        Args:
            path: Absolute path to the file.

        Returns:
            List of lines (split on newline).

        Raises:
            OSError: If the file cannot be read.
        """
        if path not in self._lines_cache:
            text = self.read_text(path)
            self._lines_cache[path] = text.split('\n')
        return self._lines_cache[path]

    def clear(self) -> None:
        """Clear all cached file data."""
        self._text_cache.clear()
        self._lines_cache.clear()


# =============================================================================
# 4. String-aware Dart parsing
# =============================================================================

def find_matching_brace(content: str, start: int) -> int:
    """Find the matching closing brace from position right after opening '{'.

    Correctly skips string literals (single-quoted, double-quoted, triple-quoted,
    raw strings), single-line comments (//), and multi-line comments (/* */).

    This is a critical improvement over the old _find_class_end / _find_method_end /
    _find_block_end / _find_callback_end functions which did not handle strings or
    comments, leading to incorrect brace matching when code contained braces inside
    strings (e.g., interpolation, JSON templates, regex patterns).

    Args:
        content: The full source content.
        start: Position immediately after the opening '{' (i.e., the first character
               inside the block). The opening '{' at content[start-1] is already counted.

    Returns:
        Position of the matching '}', or len(content) if not found.
    """
    depth = 1
    length = len(content)
    i = start

    while i < length and depth > 0:
        ch = content[i]

        # --- Single-line comment ---
        if ch == '/' and i + 1 < length:
            next_ch = content[i + 1]
            if next_ch == '/':
                # Skip to end of line
                nl = content.find('\n', i + 2)
                i = nl + 1 if nl != -1 else length
                continue
            if next_ch == '*':
                # Multi-line comment: skip to */
                end = content.find('*/', i + 2)
                i = end + 2 if end != -1 else length
                continue

        # --- Raw strings (r'...' or r"...") ---
        if ch == 'r' and i + 1 < length and content[i + 1] in ("'", '"'):
            i = _skip_raw_string(content, i + 1, length)
            continue

        # --- Triple-quoted strings ---
        if ch in ("'", '"') and i + 2 < length:
            triple = ch * 3
            if content[i:i + 3] == triple:
                i = _skip_triple_string(content, i, length, triple)
                continue

        # --- Single-quoted or double-quoted strings ---
        if ch in ("'", '"'):
            i = _skip_simple_string(content, i, length, ch)
            continue

        # --- Brace counting ---
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i

        i += 1

    return length


def _skip_raw_string(content: str, quote_pos: int, length: int) -> int:
    """Skip past a raw string starting at the quote character position.

    Raw strings in Dart do not process escape sequences, so we simply scan
    for the matching closing quote (or triple-quote).

    Args:
        content: Source content.
        quote_pos: Position of the opening quote character (after 'r').
        length: Length of content.

    Returns:
        Position after the closing quote.
    """
    quote_ch = content[quote_pos]

    # Check for raw triple-quoted string: r''' or r\"\"\"
    if quote_pos + 2 < length and content[quote_pos:quote_pos + 3] == quote_ch * 3:
        triple = quote_ch * 3
        end = content.find(triple, quote_pos + 3)
        return end + 3 if end != -1 else length

    # Simple raw string: scan for unescaped closing quote
    # (raw strings have no escapes, so just find next quote)
    i = quote_pos + 1
    while i < length:
        if content[i] == quote_ch:
            return i + 1
        if content[i] == '\n':
            # Raw single-line strings cannot span lines — treat as terminated
            return i
        i += 1
    return length


def _skip_triple_string(
    content: str, start: int, length: int, triple: str
) -> int:
    """Skip past a triple-quoted string.

    Triple-quoted strings can span multiple lines and support escape sequences
    (including escaped quotes). We scan for the closing triple-quote while
    skipping any backslash-escaped characters.

    Args:
        content: Source content.
        start: Position of the first quote of the opening triple.
        length: Length of content.
        triple: The triple-quote delimiter (either ''' or \"\"\").

    Returns:
        Position after the closing triple-quote.
    """
    i = start + 3  # Skip opening triple
    while i < length:
        if content[i] == '\\':
            i += 2  # Skip escaped character
            continue
        if content[i:i + 3] == triple:
            return i + 3
        i += 1
    return length


def _skip_simple_string(
    content: str, start: int, length: int, quote_ch: str
) -> int:
    """Skip past a simple (single or double) quoted string.

    Handles backslash escape sequences. The string terminates at the matching
    unescaped quote or at a newline (Dart single-line strings cannot span lines).

    Args:
        content: Source content.
        start: Position of the opening quote.
        length: Length of content.
        quote_ch: The quote character (' or ").

    Returns:
        Position after the closing quote.
    """
    i = start + 1
    while i < length:
        ch = content[i]
        if ch == '\\':
            i += 2  # Skip escaped character
            continue
        if ch == quote_ch:
            return i + 1
        if ch == '\n':
            # Single-line string terminated by newline
            return i
        i += 1
    return length


def find_statement_end(content: str, start: int) -> int:
    """Find the end of a Dart statement with string/comment awareness.

    Scans forward from ``start`` looking for a semicolon at depth 0 (parentheses
    and braces both tracked). Correctly skips strings and comments.

    Args:
        content: Source content.
        start: Position to start scanning from.

    Returns:
        Position of the terminating semicolon, or len(content) if not found.
    """
    paren_depth = 0
    brace_depth = 0
    length = len(content)
    i = start

    while i < length:
        ch = content[i]

        # --- Comments ---
        if ch == '/' and i + 1 < length:
            next_ch = content[i + 1]
            if next_ch == '/':
                nl = content.find('\n', i + 2)
                i = nl + 1 if nl != -1 else length
                continue
            if next_ch == '*':
                end = content.find('*/', i + 2)
                i = end + 2 if end != -1 else length
                continue

        # --- Raw strings ---
        if ch == 'r' and i + 1 < length and content[i + 1] in ("'", '"'):
            i = _skip_raw_string(content, i + 1, length)
            continue

        # --- Triple-quoted strings ---
        if ch in ("'", '"') and i + 2 < length and content[i:i + 3] == ch * 3:
            i = _skip_triple_string(content, i, length, ch * 3)
            continue

        # --- Simple strings ---
        if ch in ("'", '"'):
            i = _skip_simple_string(content, i, length, ch)
            continue

        # --- Depth tracking ---
        if ch == '(':
            paren_depth += 1
        elif ch == ')':
            paren_depth -= 1
        elif ch == '{':
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
        elif ch == ';' and paren_depth == 0 and brace_depth == 0:
            return i

        i += 1

    return length


# =============================================================================
# 5. Comment stripping (unified)
# =============================================================================

def strip_comments(content: str) -> Tuple[str, Dict[int, int]]:
    """Strip comments from Dart code while preserving position mapping.

    Removes both single-line (//) and multi-line (/* */) comments. Newlines
    inside multi-line comments are preserved to keep line numbers accurate.
    Builds a position map from stripped-content positions back to original
    positions for accurate violation line-number reporting.

    This is the position-preserving variant used by checkers that need to map
    stripped positions back to original line numbers.

    Args:
        content: Raw Dart source code.

    Returns:
        A tuple of (stripped_content, position_map) where position_map maps
        each index in stripped_content to its corresponding index in the
        original content.
    """
    position_map: Dict[int, int] = {}
    stripped_parts: List[str] = []
    stripped_pos = 0
    i = 0
    length = len(content)

    while i < length:
        # Single-line comment
        if i < length - 1 and content[i:i + 2] == '//':
            while i < length and content[i] != '\n':
                i += 1
            # Keep the newline to preserve line numbers
            if i < length:
                stripped_parts.append('\n')
                position_map[stripped_pos] = i
                stripped_pos += 1
                i += 1
            continue

        # Multi-line comment
        if i < length - 1 and content[i:i + 2] == '/*':
            i += 2
            while i < length - 1:
                if content[i:i + 2] == '*/':
                    i += 2
                    break
                # Preserve newlines for line-number accuracy
                if content[i] == '\n':
                    stripped_parts.append('\n')
                    position_map[stripped_pos] = i
                    stripped_pos += 1
                i += 1
            else:
                # Reached end without closing */
                if i < length and content[i] == '\n':
                    stripped_parts.append('\n')
                    position_map[stripped_pos] = i
                    stripped_pos += 1
                i += 1
            continue

        # Regular character
        stripped_parts.append(content[i])
        position_map[stripped_pos] = i
        stripped_pos += 1
        i += 1

    return ''.join(stripped_parts), position_map


def remove_comments(code: str) -> str:
    """Remove single-line and multi-line comments from Dart code.

    This is the simple regex-based variant used when position mapping is not
    needed (e.g., checking whether a method body contains a specific pattern
    without caring about exact line numbers).

    Args:
        code: Dart source code (possibly a fragment).

    Returns:
        The code with all comments removed.
    """
    # Remove multi-line comments first (greedy within DOTALL)
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    # Remove single-line comments
    code = re.sub(r'//.*?$', '', code, flags=re.MULTILINE)
    return code


# =============================================================================
# 6. Method discovery helpers
# =============================================================================

def find_async_methods(class_content: str) -> List[str]:
    """Find all async method names in a class, including stream generators.

    Detects three patterns:
    - Future<T> methodName(...) async   (standard async)
    - FutureOr<T> methodName(...) async (Riverpod build methods)
    - Stream<T> methodName(...) async*  (stream generators)

    Args:
        class_content: The source code of a single class.

    Returns:
        List of method names that are async.
    """
    methods: List[str] = []
    methods.extend(m.group(1) for m in RE_ASYNC_FUTURE.finditer(class_content))
    methods.extend(
        m.group(1) for m in RE_ASYNC_FUTUREOR.finditer(class_content)
    )
    methods.extend(m.group(1) for m in RE_ASYNC_STREAM.finditer(class_content))
    return methods


def find_methods_using_ref(class_content: str) -> Set[str]:
    """Find all method names in a class that use ref.read/watch/listen.

    Uses find_matching_brace for correct brace-matching (string-aware) and
    remove_comments to avoid false positives from commented-out ref calls.

    Args:
        class_content: The source code of a single class.

    Returns:
        Set of method names that contain ref operations.
    """
    methods_with_ref: Set[str] = set()

    # Match methods including FutureOr for Riverpod build methods
    method_pattern = re.compile(
        r'(?:Future<[^>]+>|FutureOr<[^>]+>|void|[A-Z]\w+)'
        r'\s+(\w+)\s*\([^)]*\)\s*(?:async\s*)?\{'
    )

    for method_match in method_pattern.finditer(class_content):
        method_name = method_match.group(1)
        # Position of the opening '{' is at method_match.end() - 1
        brace_pos = method_match.end()  # Right after '{'
        method_end = find_matching_brace(class_content, brace_pos)
        method_body = class_content[brace_pos:method_end]

        # Strip comments to avoid false positives
        method_body_clean = remove_comments(method_body)

        if RE_REF_OPERATION.search(method_body_clean):
            methods_with_ref.add(method_name)

    return methods_with_ref


def has_significant_code_after_await(next_lines: str) -> bool:
    """Check if code after an await requires a mounted check.

    Returns True ONLY if there are:
    - ref operations (ref.read/watch/listen/invalidate)
    - state assignments or access (state = or state.)

    Returns False for closing braces, whitespace, comments, void returns,
    return-with-value, and method calls on the await result.

    The key insight: we only need a mounted check if ref or state is accessed
    AFTER the await. Simply using the await's result value does not require one.

    Args:
        next_lines: The lines of code following the await statement.

    Returns:
        True if significant ref/state code follows the await.
    """
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

    return False


# =============================================================================
# 7. Type inference & variable resolution
# =============================================================================

def infer_type_from_provider(provider_expr: str) -> str:
    """Infer the Dart type from a Riverpod provider expression.

    Handles two cases:
    - Provider with .notifier: strips 'Provider' suffix, converts to PascalCase
    - Provider without .notifier: cannot infer, returns guidance string

    Examples:
        'invitationWizardStateProvider.notifier' -> 'InvitationWizardState'
        'scoreboardProvider(gameId).notifier'    -> 'Scoreboard'
        'myLoggerProvider'                       -> 'Check provider definition...'

    Args:
        provider_expr: The provider expression as it appears in ref.read().

    Returns:
        The inferred class name, or a guidance string if inference is not possible.
    """
    if '.notifier' in provider_expr:
        provider_name = provider_expr.split('.')[0]

        # Handle family providers first: scoreboardProvider(gameId) -> scoreboardProvider
        provider_name = re.sub(r'\([^)]*\)', '', provider_name)

        # Then remove 'Provider' suffix if present
        if provider_name.endswith('Provider'):
            provider_name = provider_name[:-8]  # Remove 'Provider'

        # Convert to PascalCase
        class_name = provider_name[0].upper() + provider_name[1:]
        return class_name
    else:
        return "Check provider definition for return type"


def resolve_variable_to_class(
    variable_name: str,
    class_content: str,
    full_content: str,
    provider_to_class: Dict[str, str],
) -> Optional[str]:
    """Resolve a variable name to its provider class type.

    Searches through multiple declaration patterns to find how a variable was
    assigned from a ref.read() call, then uses the provider_to_class mapping
    to resolve the provider name to a class name.

    Patterns checked (in order):
    1. final Type variable = ref.read(provider(args).notifier)
    2. final variable = ref.read(provider(args).notifier)
    3. Type variable = ref.read(provider.notifier)
    4. final variable = ref.read(provider.notifier)
    5. variable = ref.read(provider.notifier)
    6. variable = ref.read(provider)

    Args:
        variable_name: The variable name to resolve.
        class_content: The class source code.
        full_content: The full file source code.
        provider_to_class: Mapping of provider names to class names.

    Returns:
        The resolved class name, or None if resolution fails.
    """
    search_content = full_content if full_content else class_content

    # Pattern 1: final Type variable = ref.read(provider(...).notifier)
    pat = re.compile(
        rf'(\w+)\s+{re.escape(variable_name)}'
        rf'\s*=\s*ref\.read\((\w+)\([^)]*\)\.notifier\)'
    )
    match = pat.search(search_content)
    if match:
        return provider_to_class.get(match.group(2))

    # Pattern 2: final variable = ref.read(provider(...).notifier)
    pat = re.compile(
        rf'final\s+{re.escape(variable_name)}'
        rf'\s*=\s*ref\.read\((\w+)\([^)]*\)\.notifier\)'
    )
    match = pat.search(search_content)
    if match:
        return provider_to_class.get(match.group(1))

    # Pattern 3: Type variable = ref.read(provider.notifier)
    pat = re.compile(
        rf'(\w+)\s+{re.escape(variable_name)}'
        rf'\s*=\s*ref\.read\((\w+)\.notifier\)'
    )
    match = pat.search(search_content)
    if match:
        return provider_to_class.get(match.group(2))

    # Pattern 4: final variable = ref.read(provider.notifier)
    pat = re.compile(
        rf'final\s+{re.escape(variable_name)}'
        rf'\s*=\s*ref\.read\((\w+)\.notifier\)'
    )
    match = pat.search(search_content)
    if match:
        return provider_to_class.get(match.group(1))

    # Pattern 5: variable = ref.read(provider.notifier) (assignment)
    pat = re.compile(
        rf'{re.escape(variable_name)}\s*=\s*ref\.read\((\w+)\.notifier\)'
    )
    match = pat.search(search_content)
    if match:
        return provider_to_class.get(match.group(1))

    # Pattern 6: variable = ref.read(provider) (no .notifier)
    pat = re.compile(
        rf'{re.escape(variable_name)}\s*=\s*ref\.read\((\w+)\)'
    )
    match = pat.search(search_content)
    if match:
        provider_name = match.group(1).replace('.notifier', '')
        return provider_to_class.get(provider_name)

    return None


# =============================================================================
# 8. Shared call resolution helper
# =============================================================================

def resolve_method_calls_in_body(
    callback_body: str,
    file_path,
    class_name: str,
    class_content: str,
    full_content: str,
    ctx,
) -> None:
    """Resolve method calls in a code body and mark them as async-context.

    This is the shared implementation extracted from the four _trace_* methods
    (_trace_async_method_calls, _trace_callback_parameter_calls,
    _trace_stream_listen_calls, _trace_deferred_calls) which all contained
    identical method-call resolution loops.

    For each method call found in callback_body:
    1. If it is a qualified call (object.method()), attempt to resolve the
       object variable to a class name, then look up that class+method in
       ctx.all_methods.
    2. If it is an unqualified call (method()), look it up in the current
       class within ctx.all_methods.
    3. If found, add the method key to ctx.methods_called_from_async.

    Args:
        callback_body: Source code of the callback/method body to scan.
        file_path: Path of the current file (str or Path).
        class_name: Name of the class containing the callback.
        class_content: Source code of the containing class.
        full_content: Full file source code.
        ctx: AnalysisContext with all_methods, methods_called_from_async,
             provider_to_class, and lookup_method().
    """
    file_path_str = str(file_path)

    for call_match in RE_METHOD_CALL.finditer(callback_body):
        called_method = (
            call_match.group(2) if call_match.group(2)
            else call_match.group(3)
        )
        object_name = (
            call_match.group(1) if call_match.group(2)
            else None
        )

        if not called_method or called_method in SKIP_METHODS:
            continue

        if object_name:
            # Qualified call: object.method() -- resolve object to class
            resolved_class = resolve_variable_to_class(
                object_name, class_content, full_content, ctx.provider_to_class
            )
            if resolved_class:
                # Use O(1) secondary index from AnalysisContext
                key = ctx.lookup_method(resolved_class, called_method)
                if key is not None:
                    ctx.methods_called_from_async.add(key)
        else:
            # Unqualified call: method() -- try current class
            key = (file_path_str, class_name, called_method)
            if key in ctx.all_methods:
                ctx.methods_called_from_async.add(key)


# =============================================================================
# 9. Snippet extraction helpers
# =============================================================================

def extract_snippet(
    lines: List[str],
    center_line: int,
    before: int = 1,
    after: int = 5,
) -> str:
    """Extract a code snippet from a list of lines centered on a given line.

    Formats each line with a line number prefix for display in violation reports.

    Args:
        lines: All lines of the file.
        center_line: The 1-based line number to center on.
        before: Number of lines to include before center_line.
        after: Number of lines to include after center_line.

    Returns:
        Formatted snippet string with line numbers.
    """
    # Convert to 0-based index
    start_idx = max(0, center_line - 1 - before)
    end_idx = min(len(lines), center_line - 1 + after + 1)

    return '\n'.join(
        f"  {i + 1:4d} | {lines[i]}"
        for i in range(start_idx, end_idx)
    )


def get_abs_line(content: str, position: int) -> int:
    """Get the 1-based line number for a character position in content.

    Args:
        content: The full source content.
        position: A character offset (0-based) within content.

    Returns:
        The 1-based line number at the given position.
    """
    return content[:position].count('\n') + 1


# =============================================================================
# 10. Suppression helpers
# =============================================================================

def is_line_suppressed(lines: List[str], line_number: int) -> bool:
    """Check if a violation at the given line is suppressed by a comment.

    A line is suppressed if ``// riverpod_scanner:ignore`` appears on:
    - The same line (inline suppression), OR
    - The line immediately above (preceding-line suppression).

    Args:
        lines: All lines of the file (0-indexed).
        line_number: The 1-based line number of the violation.

    Returns:
        True if the violation should be suppressed.
    """
    idx = line_number - 1  # Convert to 0-based

    # Check the violation line itself
    if 0 <= idx < len(lines) and RE_IGNORE_LINE.search(lines[idx]):
        return True

    # Check the line above
    if 0 <= idx - 1 < len(lines) and RE_IGNORE_LINE.search(lines[idx - 1]):
        return True

    return False


def is_file_suppressed(content: str) -> bool:
    """Check if an entire file is suppressed by a file-level ignore comment.

    Scans the first 20 lines of the file for ``// riverpod_scanner:ignore-file``.

    Args:
        content: The full file content.

    Returns:
        True if the file should be skipped entirely.
    """
    first_lines = content.split('\n', 20)[:20]
    for line in first_lines:
        if RE_IGNORE_FILE.search(line):
            return True
    return False
