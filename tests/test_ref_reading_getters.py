"""VIOLATION 2 (LAZY_GETTER) — a getter whose body reads ref, in a class with
ANY async code.

The rule used to match only `Type get x => ref.read(...);` and only in a class
with an `async` METHOD. SocialScoreKeeper gap #833: EventProcessor hid six
`ref.read` getters behind block bodies (`get logger { if (!ref.mounted) throw …;
return ref.read(…); }`) in a class whose async work lived in closures handed to
a mutex, and CheerServiceInitializer cached `_logger ??= ref.read(…)` in a class
with no async method at all. A getter hides every ref use behind it from the
mounted-guard checks; a getter that answers its own disposal with a VALUE
(`ref.mounted ? ref.read(p) : fallback`, `if (!ref.mounted) return …;`) hides
nothing and never throws, so it is not flagged.
"""

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner


def _found(tmp_path, source):
    f = tmp_path / "probe.dart"
    f.write_text(source)
    return [v for v in RiverpodScanner().scan_file(f) if v.violation_type == ViolationType.LAZY_GETTER]


def _notifier(members: str, work: str = "  Future<void> go() async {\n    await Future<void>.delayed(Duration.zero);\n  }\n") -> str:
    return f"""\
class Probe extends _$Probe {{
  @override
  int build() => 0;

{members}

{work}}}
"""


_CLOSURE_ONLY = "  void go() {\n    gate.runExclusive(() async {\n      await Future<void>.delayed(Duration.zero);\n    });\n  }\n"


class TestFlagged:
    def test_block_bodied_getter_that_throws_when_disposed(self, tmp_path):
        source = _notifier(
            "  UnifiedLogger get logger {\n    if (!ref.mounted) throw StateError('disposed');\n    return ref.read(unifiedLoggerProvider);\n  }"
        )
        (violation,) = _found(tmp_path, source)
        assert "get logger" in violation.context

    def test_a_class_whose_async_work_lives_only_in_closures(self, tmp_path):
        source = _notifier("  UnifiedLogger get logger => ref.read(unifiedLoggerProvider);", work=_CLOSURE_ONLY)
        assert len(_found(tmp_path, source)) == 1

    def test_a_field_cache_behind_a_getter_in_a_closure_async_class(self, tmp_path):
        source = _notifier(
            "  UnifiedLogger? _logger;\n  UnifiedLogger get logger {\n    _logger ??= ref.read(unifiedLoggerProvider);\n    return _logger!;\n  }",
            work=_CLOSURE_ONLY,
        )
        assert len(_found(tmp_path, source)) == 1

    def test_a_getter_that_reads_ref_inside_an_expression(self, tmp_path):
        source = _notifier(
            "  Config get _config => Factory.narrow(ref.read(scoreboardProvider(gameId))?.config);"
        )
        assert len(_found(tmp_path, source)) == 1

    def test_ref_watch_in_a_getter(self, tmp_path):
        source = _notifier("  int get total => ref.watch(countProvider);")
        assert len(_found(tmp_path, source)) == 1


class TestClean:
    def test_a_getter_that_degrades_with_a_value_on_disposal(self, tmp_path):
        source = _notifier(
            "  UnifiedLogger get consumerLogger => ref.mounted ? ref.read(unifiedLoggerProvider) : UnifiedLogger.console();"
        )
        assert _found(tmp_path, source) == []

    def test_a_block_getter_that_returns_a_value_when_disposed(self, tmp_path):
        source = _notifier(
            "  String? get _userId {\n    if (!ref.mounted) return null;\n    return ref.read(userProvider).id;\n  }"
        )
        assert _found(tmp_path, source) == []

    def test_a_class_with_no_async_code(self, tmp_path):
        source = _notifier("  UnifiedLogger get logger => ref.read(unifiedLoggerProvider);", work="  void go() {}\n")
        assert _found(tmp_path, source) == []

    def test_a_getter_that_does_not_read_ref(self, tmp_path):
        source = _notifier("  bool get isReady => state > 0;")
        assert _found(tmp_path, source) == []

    def test_ref_in_a_comment_or_string_is_not_code(self, tmp_path):
        source = _notifier("  // get logger => ref.read(unifiedLoggerProvider);\n  String get hint => 'call ref.read(x) yourself';")
        assert _found(tmp_path, source) == []

    def test_one_finding_per_getter_when_the_arrow_rule_also_matches(self, tmp_path):
        source = _notifier("  UnifiedLogger get logger => ref.read(unifiedLoggerProvider);")
        assert len(_found(tmp_path, source)) == 1


class TestRefCachedFieldGetter:
    def test_a_getter_returning_a_field_cached_from_ref_in_an_async_class(self, tmp_path):
        source = _notifier(
            "  Router? _router;\n  Router get router => _router!;\n  void init() {\n    _router = ref.read(routerProvider.notifier);\n  }",
            work=_CLOSURE_ONLY,
        )
        (violation,) = _found(tmp_path, source)
        assert "get router" in violation.context

    def test_a_getter_returning_a_field_not_filled_from_ref(self, tmp_path):
        source = _notifier("  int? _count;\n  int get count => _count!;\n  void set(int v) {\n    _count = v;\n  }", work=_CLOSURE_ONLY)
        assert _found(tmp_path, source) == []

    def test_a_ref_cached_field_getter_in_a_class_with_no_async_code(self, tmp_path):
        source = _notifier(
            "  Router? _router;\n  Router get router => _router!;\n  void init() {\n    _router = ref.read(routerProvider.notifier);\n  }",
            work="  void go() {}\n",
        )
        assert _found(tmp_path, source) == []
