# Riverpod 3.0 Safety Scanner - Complete Guide

**Package**: `riverpod_3_scanner`
**Version**: 1.0.0
**Applies To**: Riverpod 3.0+, Flutter/Dart projects
**Pattern Status**: Official Riverpod 3.0 recommendation
**Reference**: https://riverpod.dev/docs/whats_new#refmounted

---

## 🎯 QUICK REFERENCE

### Critical Rule

**ALWAYS check `ref.mounted` BEFORE `ref.read()` and AFTER every `await`**

```dart
// ✅ CORRECT - Riverpod 3.0 Official Pattern
Future<void> myMethod() async {
  if (!ref.mounted) return;  // Check BEFORE ref.read()

  final logger = ref.read(myLoggerProvider);
  final service = ref.read(myServiceProvider);

  await someAsyncOperation();

  if (!ref.mounted) return;  // Check AFTER await

  logger.logInfo('Done');
}
```

### Class Type Detection

| Class Type | Mounted Check | Ref Type | Example |
|------------|---------------|----------|---------|
| **@riverpod provider** | `if (!ref.mounted) return;` | `Ref` | `class MyNotifier extends _$MyNotifier` |
| **ConsumerStatefulWidget** | `if (!mounted) return;` | `WidgetRef` | `class _MyState extends ConsumerState<MyWidget>` |

**Why Different**:
- `Ref` (in providers) has `.mounted` property
- `WidgetRef` (in widgets) does NOT have `.mounted` property - use State's `mounted` instead

### Scanner Commands

```bash
# Scan entire project
python3 riverpod_3_scanner.py lib

# Scan specific directory
python3 riverpod_3_scanner.py lib/features

# Scan single file
python3 riverpod_3_scanner.py lib/path/to/file.dart

# Verbose output
python3 riverpod_3_scanner.py lib --verbose

# Custom pattern
python3 riverpod_3_scanner.py lib --pattern "**/*_notifier.dart"
```

### Exit Codes

- `0` - No violations (clean)
- `1` - Violations found (must be fixed)
- `2` - Error (invalid path, etc.)

---

## 📊 VIOLATION TYPES (25 TYPES)

The authoritative list is `ViolationType` / `VIOLATION_SEVERITY` in
`riverpod_3_scanner/models.py`; the `type` column is the value the scanner prints.

### CRITICAL (Will crash in production)

| Type | Detection | Impact |
|------|-----------|--------|
| `field_caching` | Nullable fields with getters in async classes | Production crash on unmount |
| `lazy_getter` | `get x => ref.read()` in async classes | Production crash on unmount |
| `async_getter` | `Future<T> get x async` with field caching | Production crash on unmount |
| `ref_read_before_mounted` | ref operations before the entry mounted check | Production crash |
| `missing_mounted_after_await` | No mounted check after an async gap | Production crash |
| `missing_mounted_in_catch` | A `ref` / `state` use in a catch block before its mounted guard (judged over the whole catch body) | Production crash |
| `missing_mounted_in_finally` | A `ref` / `state` use in a finally block before a mounted guard — finally runs after every early `if (!ref.mounted) return;` in its try | Production crash |
| `nullable_field_access` | Direct `_field?.method()` when a getter exists | Bypasses safety |
| `ref_in_lifecycle_callback` | `ref.read()` in `ref.onDispose` / `ref.listen` callbacks | AssertionError crash |
| `ref_listen_outside_build` | `ref.listen` called outside `build()` | Listener leak / crash |
| `initstate_field_access_before_caching` | Accessing cached fields in `initState` before `build()` caches them | Production crash |
| `sync_method_without_mounted_check` | A sync method with `ref.read()` called from an async context | Production crash |
| `ref_stored_as_field` | `final Ref` / `final WidgetRef` field in a plain class | Crash after the owner disposes |
| `ref_passed_to_plain_class` | A constructor parameter typed `Ref` / `WidgetRef` in a plain class | Crash after the owner disposes |
| `state_assign_await` | `state = await …` with no mounted check between the await and the assignment | Production crash |
| `async_star_ref_before_mounted` | An `async*` function provider whose first `ref.read/watch/listen` precedes `if (!ref.mounted)` | Production crash |
| `build_listen_sync_state_mutation` | A `build()`-registered `ref.listen` on a sync provider whose callback mutates `state` synchronously | Build-phase modification crash |
| `catch_guard_returns_success` | A catch block whose mounted guard returns `Right(...)` / `true` while the catch otherwise returns `Left(...)` / `false` | A failed operation is reported to its live caller as a success |
| `use_in_disposed_branch` | A `ref` / notifier `state` / `setState` / host `context` use in code that runs only once the host is gone: the branch of `if (!ref.mounted)`, the else of `if (ref.mounted)`, the matching ternary operand, or a condition operand like `!ref.mounted && state.x` | Throws on the exact path meant to handle disposal |

### WARNINGS (High risk of crashes, or lost diagnostics)

| Type | Detection | Impact |
|------|-----------|--------|
| `ref_watch_outside_build` | `ref.watch` called outside `build()` | No rebuild / stale value |
| `widget_lifecycle_unsafe_ref` | ref in `didUpdateWidget`, `deactivate`, `reassemble` | High crash risk |
| `deferred_callback_unsafe_ref` | `Timer` / `Future.delayed` / microtask callbacks without mounted checks, and UI callbacks (`onPressed`, `onTap`, …) a notifier builds that use ref / state before `if (!ref.mounted)` | High crash risk |
| `log_after_mounted_guard` | A catch block, block-bodied `.catchError` / `onError` callback, or failure branch (an `if`/`else` block that opens with a mounted guard protecting nothing but a logger read) whose failure log runs only once the host is known to be mounted | A failure after a back-out is never recorded |

### DEFENSIVE (Type safety & best practices)

| Type | Detection | Impact |
|------|-----------|--------|
| `untyped_lazy_getter` | `var` instead of typed getters | Loses type safety |
| `mounted_vs_ref_mounted_confusion` | Using the wrong mounted check for the class type | Educational |

---

## 🛡️ SCANNER CAPABILITIES

### Multi-Pass Call-Graph Analysis

The scanner uses a **4-pass architecture** with sophisticated call-graph analysis:

**Pass 1: Cross-File Reference Database**
```
Objective: Index ALL classes, methods, and provider mappings

FOR each .dart file:
  1. Find all Riverpod provider classes (extends _$ClassName)
  2. Build mapping: providerName -> className
  3. Build mapping: className -> filePath
  4. Index methods containing ref.read/watch/listen
```

**Pass 1.5: Complete Method Database**
```
Objective: Index ALL methods with metadata

FOR each class method:
  Store: (file, class, method) -> {
    has_ref_read: bool,
    has_mounted_check: bool,
    is_async: bool,
    is_lifecycle_method: bool,
    method_body: str
  }
```

**Pass 2: Async Callback Call-Graph**
```
Objective: Trace which methods are called from async contexts

Detects:
  1. Methods called after await in async methods
  2. Methods called in callback parameters (onCompletion:, builder:, etc.)
  3. Methods called in stream.listen() callbacks
  4. Methods called in Timer/Future.delayed/addPostFrameCallback
  5. Variable resolution (basketballNotifier -> BasketballNotifier)
```

**Pass 2.5: Transitive Propagation**
```
Objective: Recursively propagate async context

FIXED-POINT ITERATION:
  IF method A calls method B AND B is in async context
  THEN A is also in async context

  REPEAT until no new methods added
```

**Pass 3: Violation Detection**
```
Objective: Find violations with zero false positives

  1. Strip comments (avoid false positives)
  2. Check lifecycle callbacks (ref.onDispose, ref.listen)
  3. Check sync methods called from async contexts
  4. Verify violations with call-graph context
```

### Comment Stripping (False Positive Prevention)

Scanner strips comments BEFORE pattern matching:

```dart
// ❌ WITHOUT comment stripping - FALSE POSITIVE
@override
void dispose() {
  // Cleanup handled by ref.onDispose() in build()  ← Scanner matches this!
  super.dispose();
}

// ✅ WITH comment stripping - ACCURATE
// Scanner ignores commented code, only flags real violations
```

### Variable Resolution

Scanner resolves variable names to class names:

```dart
// Variable assignment
final basketballNotifier = ref.read(basketballProvider(gameId).notifier);

// Method call in callback
onCompletion: () {
  basketballNotifier.completeGame();
  //  ↓ Scanner resolves ↓
  // BasketballNotifier.completeGame()
}
```

Supports:
- Parameterized providers: `provider(id).notifier`
- Non-parameterized providers: `provider.notifier`
- Riverpod codegen naming: `XxxNotifier` → `xxxProvider`

---

## ❌ FORBIDDEN PATTERNS

### Pattern 1: Field Caching (Pre-Riverpod 3.0)

```dart
// ❌ WRONG - Outdated workaround, creates race conditions
class MyNotifier extends _$MyNotifier {
  MyLogger? _logger;
  MyLogger get logger {
    final l = _logger;
    if (l == null) throw StateError('Disposed');
    return l;
  }

  @override
  build() {
    _logger = ref.read(myLoggerProvider);
    ref.onDispose(() => _logger = null);
    return State.initial();
  }

  Future<void> doWork() async {
    await operation();
    logger.logInfo('Done');  // CRASH: _logger set to null during await
  }
}
```

**Why Wrong**:
- Adds unnecessary complexity
- Race condition between `ref.mounted` check and field access
- Riverpod 3.0 `ref.mounted` eliminates need for this pattern

### Pattern 2: Lazy Getters

```dart
// ❌ WRONG - Most common production crash pattern
class _MyWidgetState extends ConsumerState<MyWidget> {
  MyLogger get logger => ref.read(myLoggerProvider);

  Future<void> doWork() async {
    logger.logInfo('Start');  // Safe initially
    await operation();
    logger.logInfo('Done');   // CRASH: widget unmounted during await
  }
}
```

**Production Error**:
```
StateError: Using "ref" when a widget is about to or has been unmounted
```

### Pattern 3: ref Operations in Lifecycle Callbacks (DEADLY)

```dart
// ❌ DEADLY - Causes AssertionError in production
ref.onDispose(() {
  final logger = ref.read(myLoggerProvider);  // CRASH
  logger.logInfo('Disposing');
});

ref.listen(someProvider, (previous, next) {
  final logger = ref.read(myLoggerProvider);  // CRASH
  logger.logInfo('Provider changed');
});
```

**Production Error**:
```
AssertionError: 'package:riverpod/src/core/ref.dart':
Failed assertion: line 216 pos 7: '_debugCallbackStack == 0':
Cannot use Ref or modify other providers inside life-cycles/selectors.
```

**Correct Pattern**:
```dart
// ✅ CORRECT - Capture dependencies BEFORE callback
final logger = ref.read(myLoggerProvider);

ref.onDispose(() {
  logger.logInfo('Disposing');  // Uses captured logger
});

ref.listen(someProvider, (previous, next) {
  logger.logInfo('Provider changed');  // Uses captured logger
});
```

### Pattern 4: Sync Methods Without Mounted Check (NEW - Call-Graph Detection)

```dart
// ❌ DEADLY - Sync method called from async callback
class BasketballNotifier extends _$BasketballNotifier {
  void completeGame() {  // No mounted check
    try {
      ref.read(myLoggerProvider).logInfo('...');  // CRASH POINT
      state = state.copyWith(isComplete: true);
    }
  }
}

// Called from async callback:
await gameService.handleCompletion(
  onCompletion: () {
    basketballNotifier.completeGame();  // Provider disposed during await!
  }
);
```

**Fix**:
```dart
// ✅ CORRECT - Add mounted check at entry
void completeGame() {
  if (!ref.mounted) return;  // Protects ALL ref.read() calls

  try {
    ref.read(myLoggerProvider).logInfo('...');  // Now safe
    state = state.copyWith(isComplete: true);
  }
}
```

---

## ✅ CORRECT PATTERNS (Riverpod 3.0)

### Basic Template (Provider Classes)

```dart
@riverpod
class MyNotifier extends _$MyNotifier {
  @override
  State build() => State.initial();

  Future<void> doWork() async {
    // 1. Check mounted BEFORE reading
    if (!ref.mounted) return;

    // 2. Read dependencies when needed
    final logger = ref.read(myLoggerProvider);
    final service = ref.read(myServiceProvider);

    // 3. Async work
    await someOperation();

    // 4. Check mounted AFTER async gap
    if (!ref.mounted) return;

    // 5. Safe to use dependencies
    logger.logInfo('Done');
  }
}
```

### Basic Template (ConsumerStatefulWidget)

```dart
class _MyWidgetState extends ConsumerState<MyWidget> {
  Future<void> doWork() async {
    // 1. Check widget mounted BEFORE reading
    if (!mounted) return;

    // 2. Read dependencies when needed
    final logger = ref.read(myLoggerProvider);
    final service = ref.read(myServiceProvider);

    // 3. Async work
    await someOperation();

    // 4. Check widget mounted AFTER async gap
    if (!mounted) return;

    // 5. Safe to use dependencies
    logger.logInfo('Done');
  }
}
```

### Multiple Dependencies

```dart
Future<void> complexWork() async {
  // Entry check
  if (!ref.mounted) return;

  // Read all dependencies
  final logger = ref.read(myLoggerProvider);
  final service = ref.read(myServiceProvider);
  final manager = ref.read(myManagerProvider);

  // First async operation
  await service.fetch();
  if (!ref.mounted) return;

  logger.logInfo('Fetched');

  // Second async operation
  await manager.process();
  if (!ref.mounted) return;

  logger.logInfo('Processed');
}
```

### Error Handling

```dart
Future<void> workWithErrors() async {
  if (!ref.mounted) return;

  final logger = ref.read(myLoggerProvider);

  try {
    await riskyOperation();
    if (!ref.mounted) return;

    logger.logInfo('Success');
  } catch (e, st) {
    // Log FIRST through the logger captured above: a value captured while
    // mounted stays safe after unmount, so the failure is never lost.
    logger.logError('Failed', error: e, stackTrace: st);

    // CRITICAL: guard BEFORE anything that touches ref / state.
    if (!ref.mounted) return;
    state = AsyncError(e, st);
  }
}
```

### Lifecycle Callbacks (ref.listen)

```dart
@override
build() {
  // Capture dependencies BEFORE ref.listen
  final logger = ref.read(myLoggerProvider);

  ref.listen(gameProvider, (previous, current) {
    // One mounted check at entry is sufficient for synchronous callbacks
    if (!ref.mounted) return;

    // Use captured logger - NO ref.read() here
    if (current.isComplete && !(previous?.isComplete ?? false)) {
      logger.logInfo('Game complete: ${current.score}');
    }
  });

  return State.initial();
}
```

---

## 🔍 DECISION TREES

### Determining Which Mounted Check to Use

```
WHICH_MOUNTED_CHECK:
  ↓
  Q: What is the class type?

  CLASS extends _$ClassName?
    ✅ USE: if (!ref.mounted) return;

  CLASS extends ConsumerState<T>?
    ✅ USE: if (!mounted) return;

  ConsumerWidget with async operations?
    ⚠️  REFACTOR: Move async logic to provider
         ConsumerWidget should only build UI
```

### When to Use @Riverpod(keepAlive: true)

```
KEEPALIVE_DECISION:
  ↓
  Q: Is provider called from deferred context?

  YES (addPostFrameCallback, Timer, Future.delayed)
    ✅ USE: @Riverpod(keepAlive: true)
    ✅ REASON: Prevents disposal during deferred execution

  YES (Reactive Business Logic Coordinator)
    ✅ USE: @Riverpod(keepAlive: true)
    ✅ REASON: Must persist throughout app lifecycle

  YES (Revenue-critical service)
    ✅ USE: @Riverpod(keepAlive: true)
    ✅ REASON: Never dispose payment/subscription logic

  NO (Regular UI provider)
    ✅ USE: @riverpod (default auto-dispose)
    ✅ REASON: Cleaned up when no longer watched
```

### Invalidate vs Clear Cache Pattern

```
NEED_TO_RESET_STATE:
  ↓
  Q: Does provider have lifecycle subscriptions?
     (connection monitors, listeners, timers)

  YES
    ✅ USE: clearCache() method
    ✅ RESULT: Provider stays alive, monitors preserved, cache cleared

  NO
    ✅ USE: ref.invalidate()
    ✅ RESULT: Provider fully reset, re-created on next access
```

---

## 🛠️ SCANNER USAGE

### Installation

```bash
# Download scanner
curl -O https://raw.githubusercontent.com/DayLight-Creative-Technologies/riverpod_3_scanner/main/riverpod_3_scanner.py

# Or clone repository
git clone https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner.git
cd riverpod_3_scanner
```

### Basic Usage

```bash
# Scan entire lib directory
python3 riverpod_3_scanner.py lib

# Scan specific subdirectory
python3 riverpod_3_scanner.py lib/presentation

# Scan single file
python3 riverpod_3_scanner.py lib/features/game/notifiers/game_notifier.dart

# Verbose mode (shows analysis details)
python3 riverpod_3_scanner.py lib --verbose
```

### Advanced Usage

```bash
# Custom glob pattern
python3 riverpod_3_scanner.py lib --pattern "**/*_notifier.dart"

# Scan only widgets
python3 riverpod_3_scanner.py lib --pattern "**/widgets/**/*.dart"

# Scan only services
python3 riverpod_3_scanner.py lib --pattern "**/services/**/*.dart"
```

### Output Format

```
🔍 RIVERPOD 3.0 COMPLIANCE SCAN COMPLETE
📁 Scanned: lib
🚨 Total violations: 5

VIOLATIONS BY TYPE:
🔴 FIELD CACHING: 3
🔴 MISSING MOUNTED AFTER AWAIT: 2

================================================================================
AFFECTED FILES:
================================================================================

📄 lib/services/my_service.dart (5 violation(s))
   • Line 25: field_caching
   • Line 85: missing_mounted_after_await
   • Line 120: ref_in_lifecycle_callback

================================================================================
DETAILED VIOLATION REPORTS:
================================================================================

[1/5]
FILE: lib/services/my_service.dart
CLASS: MyService
TYPE: field_caching
LINE: 25

CONTEXT: Field caching: _logger with getter in async class

CODE SNIPPET:
   24 |   MyLogger? _logger;
   25 |   MyLogger get logger {
   26 |     final l = _logger;
   27 |     if (l == null) throw StateError('Disposed');
   28 |     return l;
   29 |   }

FIX INSTRUCTIONS:
❌ PROBLEM: Field caching pattern in async class
   Line 25: MyLogger? _logger with enhanced getter

✅ FIX: Remove field and getter, use just-in-time ref.read()

BEFORE (CRASHES):
   MyLogger? _logger;
   MyLogger get logger {
     final l = _logger;
     if (l == null) throw StateError('Disposed');
     return l;
   }

AFTER (SAFE):
   // Remove field and getter entirely

   Future<void> myMethod() async {
     if (!ref.mounted) return;
     final logger = ref.read(myLoggerProvider);
     logger.logInfo('Start');

     await operation();
     if (!ref.mounted) return;

     logger.logInfo('Done');
   }
```

---

## 🚀 CI/CD INTEGRATION

### GitHub Actions

```yaml
# .github/workflows/riverpod-safety-check.yml
name: Riverpod 3.0 Safety Check
on: [push, pull_request]

jobs:
  riverpod-safety:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.x'

      - name: Download Riverpod Scanner
        run: |
          curl -O https://raw.githubusercontent.com/DayLight-Creative-Technologies/riverpod_3_scanner/main/riverpod_3_scanner.py
          chmod +x riverpod_3_scanner.py

      - name: Run Riverpod 3.0 Safety Scanner
        run: python3 riverpod_3_scanner.py lib

      - name: Run Dart Analyze
        run: dart analyze lib/
```

### Pre-commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Running Riverpod 3.0 compliance check..."

# Run scanner
python3 riverpod_3_scanner.py lib || {
  echo "❌ Riverpod 3.0 violations found!"
  echo "Fix violations before committing."
  exit 1
}

# Run dart analyze
dart analyze lib/ || {
  echo "❌ Dart analyze errors found!"
  exit 1
}

echo "✅ All compliance checks passed!"
exit 0
```

### Make it executable

```bash
chmod +x .git/hooks/pre-commit
```

### GitLab CI

```yaml
# .gitlab-ci.yml
riverpod_safety_check:
  stage: test
  image: cirrusci/flutter:stable
  script:
    - curl -O https://raw.githubusercontent.com/DayLight-Creative-Technologies/riverpod_3_scanner/main/riverpod_3_scanner.py
    - python3 riverpod_3_scanner.py lib
    - dart analyze lib/
  only:
    - merge_requests
    - main
```

### Bitbucket Pipelines

```yaml
# bitbucket-pipelines.yml
pipelines:
  default:
    - step:
        name: Riverpod 3.0 Safety Check
        image: cirrusci/flutter:stable
        script:
          - curl -O https://raw.githubusercontent.com/DayLight-Creative-Technologies/riverpod_3_scanner/main/riverpod_3_scanner.py
          - python3 riverpod_3_scanner.py lib
          - dart analyze lib/
```

---

## 📋 COMPLETION CHECKLIST

### For @riverpod Provider Classes (extends _$ClassName)

**Async Method is SAFE when**:
- ✅ `if (!ref.mounted) return;` BEFORE any `ref.read()`
- ✅ `if (!ref.mounted) return;` AFTER every `await`
- ✅ Every `catch` block logs through a logger captured while mounted, THEN `if (!ref.mounted) return;` before any `ref` / `state` use
- ✅ Dependencies read just-in-time, not cached in fields
- ✅ `@Riverpod(keepAlive: true)` if called from deferred contexts
- ✅ `dart analyze` returns "No issues found!"
- ✅ Scanner returns 0 violations

**Lifecycle Callback is SAFE when**:
- ✅ NO `ref.read/watch/listen()` calls inside `ref.onDispose()` callbacks
- ✅ NO `ref.read/watch/listen()` calls inside `ref.listen()` callbacks
- ✅ All dependencies captured BEFORE the callback
- ✅ No methods called that use ref internally (direct or indirect)

### For ConsumerStatefulWidget State Classes (extends ConsumerState<T>)

**Async Method is SAFE when**:
- ✅ `if (!mounted) return;` BEFORE any `ref.read()` (widget's mounted, NOT ref.mounted)
- ✅ `if (!mounted) return;` AFTER every `await`
- ✅ Every `catch` block logs through a logger captured while mounted, THEN `if (!mounted) return;` before any `ref` use
- ✅ NO lazy getters in classes with async methods
- ✅ NO field caching patterns in classes with async methods
- ✅ Dependencies read just-in-time with mounted checks
- ✅ `dart analyze` returns "No issues found!"
- ✅ Scanner returns 0 violations

### Project-Wide Safety

**Project is SAFE when**:
- ✅ No field caching patterns exist in async classes
- ✅ All async provider methods follow correct pattern for their class type
- ✅ All lifecycle callbacks follow pattern
- ✅ Scanner returns 0 violations: `python3 riverpod_3_scanner.py lib`
- ✅ Zero production StateError/UnmountedRefException for 30 days

---

## 🔧 COMMON FIX PATTERNS

### Scenario 1: Multiple Logger Calls in ref.listen

**Problem**: Need to log in multiple places inside callback
```dart
// ❌ WRONG
ref.listen(provider, (prev, next) {
  logger.logInfo('Start');  // VIOLATION
  processData();
  logger.logInfo('End');    // VIOLATION
});
```

**Solution**: Capture once, use everywhere
```dart
// ✅ CORRECT
final logger = ref.read(myLoggerProvider);
ref.listen(provider, (prev, next) {
  if (!ref.mounted) return;
  logger.logInfo('Start');
  processData();
  logger.logInfo('End');
});
```

### Scenario 2: Need Fresh State Inside ref.listen

**Problem**: Using .select() but need full state
```dart
// ❌ WRONG
ref.listen(
  gameProvider.select((s) => s.isComplete),
  (prev, isComplete) {
    final game = ref.read(gameProvider);  // VIOLATION
  }
);
```

**Solution A**: Listen to full provider
```dart
// ✅ CORRECT
final logger = ref.read(myLoggerProvider);
ref.listen(gameProvider, (previous, current) {
  if (!ref.mounted) return;

  if (current.isComplete && !(previous?.isComplete ?? false)) {
    logger.logInfo('Score: ${current.homeScore}');
  }
});
```

**Solution B**: Capture state before callback (only if state won't change)
```dart
// ✅ CORRECT (only if state doesn't change)
final initialGameState = ref.read(gameProvider);
final logger = ref.read(myLoggerProvider);

ref.listen(
  gameProvider.select((s) => s.isComplete),
  (prev, isComplete) {
    if (!ref.mounted) return;
    logger.logInfo('Score: ${initialGameState.homeScore}');
  }
);
```

### Scenario 3: Calling Methods from Callbacks

**Problem**: Method uses ref internally
```dart
// ❌ WRONG
ref.onDispose(() {
  _cleanup();  // VIOLATION if _cleanup() uses ref
});

void _cleanup() {
  final logger = ref.read(myLoggerProvider);  // Causes violation
  logger.logInfo('Cleanup');
}
```

**Solution A**: Refactor method to accept dependencies
```dart
// ✅ CORRECT
final logger = ref.read(myLoggerProvider);
ref.onDispose(() {
  _cleanupNoRef(logger);  // Pass dependency
});

void _cleanupNoRef(MyLogger logger) {
  logger.logInfo('Cleanup');  // Uses parameter
}
```

**Solution B**: Remove logging from disposal entirely
```dart
// ✅ CORRECT
ref.onDispose(() {
  _subscription?.cancel();
  _controller?.close();
  // No logging - just cleanup
});
```

---

## 📚 REFERENCES

### Official Riverpod Documentation

- [What's New in Riverpod 3.0 - ref.mounted](https://riverpod.dev/docs/whats_new#refmounted)
- [Riverpod 3.0 Migration Guide](https://riverpod.dev/docs/3.0_migration)
- [AsyncNotifierProvider](https://riverpod.dev/docs/providers/async_notifier_provider)

### Community Resources

- [Andrea Bizzotto: How to Check if an AsyncNotifier is Mounted](https://codewithandrea.com/articles/async-notifier-mounted-riverpod/)

### Scanner Updates

- **2025-12-14**: Added full call-graph analysis with variable resolution, transitive propagation, and async context detection. Detects sync methods called from async callbacks. **Zero false positives, zero false negatives.**
- **2025-11-23**: Correctly distinguishes between `mounted` (ConsumerStatefulWidget) and `ref.mounted` (provider classes). Eliminated 144 false positives.

---

## 🎓 CRITICAL RULES SUMMARY

### Rule 1: Check mounted BEFORE ref.read()

```
❌ NEVER: ref.read() then check mounted
✅ ALWAYS: Check mounted then ref.read()
```

### Rule 2: Check mounted AFTER await

```dart
await operation();
if (!ref.mounted) return;  // MANDATORY
```

### Rule 3: Check mounted in Catch Blocks

```dart
final logger = ref.read(myLoggerProvider);  // captured while mounted
try {
  await work();
} catch (e) {
  logger.logError('Failed', error: e);  // captured logger: log FIRST
  if (!ref.mounted) return;             // MANDATORY before any ref / state use
}
```

### Rule 4: Use keepAlive for Deferred Execution

```dart
// If provider called from:
// - addPostFrameCallback
// - Timer
// - Future.delayed
// - Any deferred context

@Riverpod(keepAlive: true)  // MANDATORY
class MyProvider extends _$MyProvider {
  // ...
}
```

### Rule 5: Never Cache Dependencies in Fields

```
❌ FORBIDDEN: Field caching pattern
✅ REQUIRED: Just-in-time ref.read() after mounted check
```

### Rule 6: Never Use ref Inside Lifecycle Callbacks

```dart
❌ FORBIDDEN: ref operations inside ref.listen/ref.onDispose callbacks
✅ REQUIRED: Capture dependencies BEFORE callback
```

---

## 🚨 PRODUCTION CRASH EXAMPLES

### Example 1: Lazy Getter Crash (Sentry #7055596134)

**Before (Crashes)**:
```dart
class _MyState extends ConsumerState<MyWidget> {
  MyLogger get logger => ref.read(myLoggerProvider);

  @override
  void initState() {
    super.initState();
    _initialize();
  }

  Future<void> _initialize() async {
    logger.logInfo('Start');
    await Future.delayed(Duration(seconds: 2));
    logger.logInfo('Done');  // CRASH if user navigates away
  }
}
```

**Error**:
```
StateError: Using "ref" when a widget is about to or has been unmounted
```

**After (Safe)**:
```dart
class _MyState extends ConsumerState<MyWidget> {
  @override
  void initState() {
    super.initState();
    _initialize();
  }

  Future<void> _initialize() async {
    if (!mounted) return;
    final logger = ref.read(myLoggerProvider);
    logger.logInfo('Start');

    await Future.delayed(Duration(seconds: 2));
    if (!mounted) return;

    logger.logInfo('Done');
  }
}
```

### Example 2: Sync Method Called from Async (Sentry #7109530155)

**Before (Crashes)**:
```dart
class BasketballNotifier extends _$BasketballNotifier {
  void completeGame() {
    try {
      ref.read(myLoggerProvider).logInfo('Completing game');
      state = state.copyWith(isComplete: true);
    }
  }
}

// Called from async callback
await gameService.handleCompletion(
  onCompletion: () {
    basketballNotifier.completeGame();  // CRASH
  }
);
```

**Error**:
```
UnmountedRefException: Cannot access ref after provider disposal
```

**After (Safe)**:
```dart
class BasketballNotifier extends _$BasketballNotifier {
  void completeGame() {
    if (!ref.mounted) return;  // ADD THIS

    try {
      ref.read(myLoggerProvider).logInfo('Completing game');
      state = state.copyWith(isComplete: true);
    }
  }
}
```

---

## 💡 TROUBLESHOOTING

### Scanner Reports False Positives

**Issue**: Scanner flags safe code as violations

**Solution**: Check if you're using correct mounted pattern for class type:
- Provider classes: `if (!ref.mounted) return;`
- ConsumerState classes: `if (!mounted) return;`

### Scanner Misses Real Violations

**Issue**: Code crashes in production but scanner doesn't detect

**Possible Causes**:
1. Code uses dynamic typing (scanner can't analyze dynamic)
2. Cross-package violations (scanner only scans specified path)
3. Runtime-only issues (state management logic errors)

**Solution**:
1. Run scanner with `--verbose` flag
2. Check scanner update history in GUIDE.md
3. Report issue with code sample

### High Number of Violations

**Issue**: Scanner reports hundreds of violations

**Strategy**:
1. **Phase 1**: Fix all CRITICAL violations first (types 1-10)
2. **Phase 2**: Fix WARNINGS (types 11-12)
3. **Phase 3**: Address DEFENSIVE items (types 13-14)
4. **Automate**: Set up pre-commit hook after Phase 1

### Scanner Performance

**Issue**: Scanner takes too long on large codebase

**Solutions**:
```bash
# Scan specific directories incrementally
python3 riverpod_3_scanner.py lib/features
python3 riverpod_3_scanner.py lib/services
python3 riverpod_3_scanner.py lib/presentation

# Use pattern filtering
python3 riverpod_3_scanner.py lib --pattern "**/*_notifier.dart"
```

---

**END OF GUIDE**

*This scanner enforces Riverpod 3.0 async safety standards to prevent production crashes. Use in CI/CD pipelines and pre-commit hooks for continuous compliance.*

**Package**: `riverpod_3_scanner` v1.0.0
**License**: MIT
**Author**: Steven Day
**Company**: DayLight Creative Technologies
**Support**: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/issues
