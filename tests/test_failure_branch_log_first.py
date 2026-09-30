"""LOG_AFTER_MOUNTED_GUARD, failure-branch shape: a branch that opens with a
mounted guard whose only job is a logger read, so its failure log is dropped
whenever the host is gone.

``if (response == null) { if (!ref.mounted) return null; final logger =
ref.read(unifiedLoggerProvider); logger.logError(...); }`` — the guard protects
nothing but the logger, and a back-out during the await loses the failure.
42 such branches sat in SocialScoreKeeper outside any catch (2026-09-29).
"""

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner


def _method(body: str) -> str:
    return f"""\
@riverpod
class Loader extends _$Loader {{
  @override
  void build() {{}}

  Future<Game?> load(int id) async {{
    if (!ref.mounted) return null;
    final logger = ref.read(unifiedLoggerProvider);
    final response = await fetch(id);
{body}
    return response;
  }}
}}
"""


def _found(tmp_path, source):
    f = tmp_path / "probe.dart"
    f.write_text(source)
    return [
        v for v in RiverpodScanner().scan_file(f)
        if v.violation_type == ViolationType.LOG_AFTER_MOUNTED_GUARD and v.context.startswith('failure branch')
    ]


class TestFlagged:
    def test_guard_then_logger_read_then_error_in_an_if_branch(self, tmp_path):
        (violation,) = _found(tmp_path, _method("""\
    if (response == null) {
      if (!ref.mounted) return null;
      final logger = ref.read(unifiedLoggerProvider);
      logger.logError('Failed to load $id');
    }"""))
        assert violation.line_number == 11
        assert violation.context.startswith('failure branch guards only to read the logger (log at line 13)')

    def test_else_branch_with_a_warning(self, tmp_path):
        source = _method("""\
    if (response != null) {
      logger.logInfo('loaded');
    } else {
      if (!ref.mounted) return null;
      ref.read(unifiedLoggerProvider).logWarning('Nothing for $id');
    }""")
        assert [v.line_number for v in _found(tmp_path, source)] == [13]

    def test_state_class_guard(self, tmp_path):
        source = """\
class _PageState extends ConsumerState<Page> {
  Future<void> load() async {
    final response = await fetch();
    if (response == null) {
      if (!mounted) return;
      ref.read(unifiedLoggerProvider).logError('Failed');
    }
  }
}
"""
        assert len(_found(tmp_path, source)) == 1

    def test_the_advice_is_to_log_first_through_a_captured_logger(self, tmp_path):
        (violation,) = _found(tmp_path, _method("""\
    if (response == null) {
      if (!ref.mounted) return null;
      ref.read(unifiedLoggerProvider).logError('Failed');
    }"""))
        assert "logger.logError('Failed to load $id');          // log FIRST, no guard" in violation.fix_instructions


class TestClean:
    def test_log_first_through_the_captured_logger(self, tmp_path):
        assert _found(tmp_path, _method("""\
    if (response == null) {
      logger.logError('Failed to load $id');
    }""")) == []

    def test_a_guard_that_also_protects_state(self, tmp_path):
        assert _found(tmp_path, _method("""\
    if (response == null) {
      if (!ref.mounted) return null;
      ref.read(unifiedLoggerProvider).logError('Failed');
      state = const AsyncError('failed', StackTrace.empty);
    }""")) == []

    def test_a_guard_before_a_success_log_only(self, tmp_path):
        assert _found(tmp_path, _method("""\
    if (response != null) {
      if (!ref.mounted) return null;
      ref.read(unifiedLoggerProvider).logInfo('loaded');
    }""")) == []

    def test_a_method_entry_guard_is_not_a_branch(self, tmp_path):
        source = """\
@riverpod
class Loader extends _$Loader {
  Future<void> load() async {
    if (!ref.mounted) return;
    final logger = ref.read(unifiedLoggerProvider);
    logger.logWarning('starting');
  }
}
"""
        assert _found(tmp_path, source) == []

    def test_a_guard_that_falls_through_is_not_this_shape(self, tmp_path):
        assert _found(tmp_path, _method("""\
    if (response == null) {
      if (!ref.mounted) {
        logger.logInfo('gone');
      }
      ref.read(unifiedLoggerProvider).logError('Failed');
    }""")) == []

    def test_another_receivers_mounted_is_not_the_host(self, tmp_path):
        assert _found(tmp_path, _method("""\
    if (response == null) {
      if (!dialogContext.mounted) return null;
      ref.read(unifiedLoggerProvider).logError('Failed');
    }""")) == []

    def test_inside_a_catch_the_catch_shape_judges_it(self, tmp_path):
        source = _method("""\
    try {
      await save();
    } catch (e) {
      if (e is TimeoutException) {
        if (!ref.mounted) return null;
        ref.read(unifiedLoggerProvider).logError('Timed out');
      }
    }""")
        assert _found(tmp_path, source) == []
