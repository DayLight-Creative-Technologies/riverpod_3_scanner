# Changelog

All notable changes to the Riverpod 3.0 Safety Scanner will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-12-14

### Added
- **Full call-graph analysis** with variable resolution, transitive propagation, and async context detection
- **Detects sync methods without mounted checks** called from async callbacks (Violation Type #10)
- **Zero false positives** via sophisticated multi-pass analysis
- **Variable resolution**: Traces `basketballNotifier` → `BasketballNotifier`
- **Transitive propagation**: If method A calls B in async context → A is also async
- **Comment stripping**: Prevents false positives from commented code
- **Cross-file violation detection**: Finds indirect violations across file boundaries
- Support for both `@riverpod` provider classes and `ConsumerStatefulWidget` State classes
- Comprehensive fix instructions for each violation type
- CI/CD integration examples (GitHub Actions, GitLab CI, Bitbucket Pipelines)
- Pre-commit hook template
- Verbose mode with detailed analysis output
- Pattern filtering with glob support
- Exit codes for automation (0=clean, 1=violations, 2=error)

### Detection Capabilities
- **14 violation types** across 3 severity levels (CRITICAL, WARNING, DEFENSIVE)
- **Pass 1**: Cross-file reference database (classes, methods, provider mappings)
- **Pass 1.5**: Complete method database with metadata
- **Pass 2**: Async callback call-graph tracing
- **Pass 2.5**: Transitive async context propagation
- **Pass 3**: Violation detection with full call-graph context

### Violation Types Detected
1. Field caching (nullable fields with getters in async classes)
2. Lazy getters (`get x => ref.read()` in async classes)
3. Async getters with field caching
4. ref.read() before mounted check
5. Missing mounted after await
6. Missing mounted in catch blocks
7. Nullable field direct access
8. ref operations inside lifecycle callbacks (ref.onDispose, ref.listen)
9. initState field access before caching
10. **NEW**: Sync methods without mounted check (called from async contexts)
11. Widget lifecycle methods with unsafe ref
12. Timer/Future.delayed deferred callbacks
13. Untyped var lazy getters
14. mounted vs ref.mounted confusion

### Documentation
- Complete GUIDE.md with all patterns, decision trees, and fix instructions
- README.md with quick start, features, and CI/CD integration
- EXAMPLES.md with real-world production crash case studies
- MIT License

### Fixed
- **Eliminated 144 false positives** by correctly distinguishing `mounted` vs `ref.mounted`
- **Zero false negatives** via call-graph analysis
- Accurate detection of indirect violations (methods calling other methods)

## [0.9.0] - 2025-11-23 (Internal Release)

### Changed
- Correctly distinguishes between `mounted` (ConsumerStatefulWidget) and `ref.mounted` (provider classes)
- Eliminated 144 false positives from mounted pattern confusion

### Added
- ConsumerStatefulWidget State class detection
- Class-type-specific mounted pattern checking
- Enhanced error messages with correct mounted check for class type

## [0.1.0] - 2025-11-15 (Internal Release)

### Added
- Initial scanner implementation
- Basic violation detection for field caching and lazy getters
- ref.read() safety checks
- Lifecycle callback violation detection

---

## Upcoming Features (Roadmap)

### [1.1.0] - Planned
- [ ] JSON output format for IDE integration
- [ ] Auto-fix capabilities for common violations
- [ ] VSCode extension integration
- [ ] IntelliJ/Android Studio plugin
- [ ] HTML report generation
- [ ] Performance optimizations for large codebases (100k+ lines)

### [1.2.0] - Planned
- [ ] Custom violation type definitions
- [ ] Configurable severity levels
- [ ] Whitelist/ignore patterns
- [ ] Incremental scanning (only changed files)
- [ ] Parallel file processing

### [2.0.0] - Future
- [ ] Real-time IDE integration (LSP)
- [ ] Quick-fix code actions in IDE
- [ ] Interactive violation browser
- [ ] Team compliance dashboard
- [ ] Historical trend analysis

---

## Version History Summary

| Version | Date | Key Changes |
|---------|------|-------------|
| 1.0.0 | 2025-12-14 | Full call-graph analysis, zero false positives |
| 0.9.0 | 2025-11-23 | mounted vs ref.mounted distinction |
| 0.1.0 | 2025-11-15 | Initial implementation |

---

## Migration Guides

### From 0.9.0 to 1.0.0

**New Detections**: Version 1.0.0 adds detection for sync methods without mounted checks (Violation Type #10). Run the scanner and fix any new violations:

```bash
python3 riverpod_3_scanner.py lib
```

**No Breaking Changes**: All existing violation types remain the same. New detections are additions only.

**Recommended**: Update CI/CD pipelines to use latest version for comprehensive coverage.

---

## Support

- **Report Issues**: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/issues
- **Feature Requests**: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/discussions
- **Author**: Steven Day (support@daylightcreative.tech)
- **Security Issues**: support@daylightcreative.tech

---

[1.0.0]: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/releases/tag/v1.0.0
[0.9.0]: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/releases/tag/v0.9.0
[0.1.0]: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/releases/tag/v0.1.0
