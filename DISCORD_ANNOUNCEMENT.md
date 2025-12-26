🎯 NEW TOOL: Riverpod 3.0 Safety Scanner

I just published a comprehensive static analyzer for detecting Riverpod 3.0 async safety violations!

📦 **Install:**
```bash
pip install riverpod-3-scanner
riverpod-3-scanner lib
```

**Why I Built This:**
After experiencing 47 production crashes in 3 days from a single unmounted ref violation, I created a scanner that detects 14 types of async safety issues. The scanner uses 4-pass call-graph analysis to achieve **zero false positives** while catching violations across files.

**What It Detects:**
✅ Lazy getters in async classes (26% of violations)
✅ Field caching patterns (pre-Riverpod 3.0 workarounds)
✅ Missing `ref.mounted` checks before/after async operations
✅ `ref.read()` inside lifecycle callbacks (`ref.onDispose`, `ref.listen`)
✅ Sync methods with `ref.read()` called from async contexts
✅ Plus 9 more violation types

**Key Features:**
🔍 Zero false positives (call-graph analysis)
📊 Cross-file violation detection (indirect method calls)
🎯 Variable resolution (knows `basketballNotifier` → `BasketballNotifier`)
📚 Detailed fix instructions for each violation
🚀 CI/CD ready (GitHub Actions, pre-commit hooks, exit codes)

**Real Impact:**
• Before: 252 violations in 200k-line codebase, 12+ crashes/week
• After: 0 violations, 0 crashes for 30+ days
• Crash reduction: 2.1% → 0% (lazy getter), 1.4% → 0% (sync method)

**Resources:**
📦 PyPI: https://pypi.org/project/riverpod-3-scanner/
💻 GitHub: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner
📖 Full Guide: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/docs/GUIDE.md
💥 Production Crash Examples: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/blob/main/docs/EXAMPLES.md

MIT open source. Built while developing SocialScoreKeeper. Feedback welcome!
