# [Tool] I created a static analyzer for Riverpod 3.0 that prevented 47 production crashes - now on PyPI

After experiencing multiple production crashes from unmounted provider references in my Flutter app (47 crashes in 3 days!), I built a comprehensive scanner that detects 14 types of Riverpod 3.0 async safety violations.

## Install

```bash
pip install riverpod-3-scanner
riverpod-3-scanner lib
```

## The Problem

Riverpod 3.0 added `ref.mounted` to handle async safety, but it's easy to miss checks. Common crash patterns:

❌ Lazy getters in async classes
❌ Missing `ref.mounted` after `await`
❌ `ref.read()` inside `ref.listen()` callbacks
❌ Sync methods with `ref.read()` called from async callbacks
❌ Field caching patterns (pre-Riverpod 3.0 workarounds)

Real crashes I experienced:
- **Lazy Logger Getter** - 47 crashes in 3 days (Sentry #7055596134)
- **Sync Method from Async Callback** - 23 crashes in 2 days (Sentry #7109530155)
- **ref.read in ref.listen** - 15 crashes in 1 day (AssertionError)

## What It Does

- 🔍 Detects 14 violation types with **zero false positives**
- 📊 Uses 4-pass call-graph analysis (traces method calls across files)
- 🎯 Resolves variables to classes (knows `basketballNotifier` → `BasketballNotifier`)
- 📚 Provides detailed fix instructions for each violation
- 🚀 CI/CD ready (exit codes, pre-commit hooks, GitHub Actions)
- 💯 No external dependencies (Python stdlib only)

## Real Impact

**Before:** 252 violations, 12+ crashes/week
**After:** 0 violations, 0 crashes for 30+ days

**Crash Reduction by Type:**
- Lazy getters: 2.1% crash rate → 0%
- Sync methods from async: 1.4% crash rate → 0%
- ref in lifecycle callbacks: 12% crash rate → 0%

**Codebase:** 200k+ lines of Dart, 50k+ DAU, production Flutter app

## Resources

- 📦 **PyPI**: https://pypi.org/project/riverpod-3-scanner/
- 💻 **GitHub**: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner
- 📖 **Complete Guide**: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/docs/GUIDE.md
- 💥 **Production Crash Case Studies**: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/docs/EXAMPLES.md

## Quick Example

### ❌ Before (Crashes)
```dart
class _GameScaffoldState extends ConsumerState<GameScaffold> {
  MyLogger get logger => ref.read(myLoggerProvider);  // CRASH

  @override
  void initState() {
    super.initState();
    _initializeGame();
  }

  Future<void> _initializeGame() async {
    logger.logInfo('Initializing game');

    await gameService.loadGame(widget.gameId);

    // User navigated away during await → widget unmounted
    logger.logInfo('Game loaded');  // CRASHES HERE
  }
}
```

### ✅ After (Safe)
```dart
class _GameScaffoldState extends ConsumerState<GameScaffold> {
  @override
  void initState() {
    super.initState();
    _initializeGame();
  }

  Future<void> _initializeGame() async {
    if (!mounted) return;
    final logger = ref.read(myLoggerProvider);
    logger.logInfo('Initializing game');

    await gameService.loadGame(widget.gameId);

    if (!mounted) return;  // Check after async gap
    final loggerAfter = ref.read(myLoggerProvider);
    loggerAfter.logInfo('Game loaded');  // Safe
  }
}
```

## CI/CD Integration

Add to GitHub Actions:
```yaml
name: Riverpod Safety Check
on: [push, pull_request]

jobs:
  riverpod-safety:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run Riverpod Scanner
        run: |
          pip install riverpod-3-scanner
          riverpod-3-scanner lib
```

Or use as a pre-commit hook:
```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Running Riverpod 3.0 compliance check..."
python3 -m pip install riverpod-3-scanner
python3 -m riverpod_3_scanner lib || exit 1
dart analyze lib/ || exit 1
echo "✅ All checks passed!"
```

## Tech Details

The scanner uses sophisticated call-graph analysis:

**Pass 1:** Build cross-file reference database
**Pass 1.5:** Index all methods with metadata (has_ref_read, has_mounted_check, is_async)
**Pass 2:** Build async callback call-graph and detect callbacks
**Pass 2.5:** Propagate async context transitively
**Pass 3:** Detect violations with full context (zero false positives)

Key innovation: Detects sync methods with `ref.read()` that are called from async callbacks - this was causing the 23 crashes in Sentry #7109530155.

## Open Source & Community

- **License**: MIT
- **Zero external dependencies** (Python 3.7+)
- **Works on:** macOS, Linux, Windows
- **Feedback welcome**: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/issues

Built at DayLight Creative Technologies while developing SocialScoreKeeper. Hope this helps prevent production crashes in your Riverpod projects!

---

**Questions?** Happy to discuss the call-graph analysis, why other tools miss these violations, or help you integrate this into your CI/CD pipeline.
