"""VIOLATION 6b (MISSING_MOUNTED_IN_FINALLY): a ref / state use in a finally
block before any mounted guard.

A finally block runs after every exit from its try, including each early
`if (!ref.mounted) return;`, so it is reached with the host already gone. It is
judged exactly like a catch block (VIOLATION 6): the leftmost ref / state use
must follow a mounted guard; a positive check guards its own block; a call on a
value captured while mounted is safe.
"""

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner


def _notifier(finally_body: str) -> str:
    return f"""\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@riverpod
class Probe extends _$Probe {{
  bool _isProcessing = false;

  @override
  ProbeState build() => const ProbeState();

  Future<void> run() async {{
    if (!ref.mounted) return;
    final logger = ref.read(unifiedLoggerProvider);
    try {{
      await work();
      if (!ref.mounted) return;
    }} finally {{
{finally_body}
    }}
  }}
}}
"""


def _found(tmp_path, source, kind=ViolationType.MISSING_MOUNTED_IN_FINALLY):
    f = tmp_path / "probe.dart"
    f.write_text(source)
    return [v for v in RiverpodScanner().scan_file(f) if v.violation_type == kind]


class TestFlagged:
    def test_state_assignment_in_finally(self, tmp_path):
        (violation,) = _found(tmp_path, _notifier("      state = state.copyWith(isLoading: false);"))
        assert 'finally block' in violation.context
        assert 'runs after EVERY exit from the try' in violation.fix_instructions

    def test_ref_read_in_finally(self, tmp_path):
        assert len(_found(tmp_path, _notifier("      _isProcessing = false;\n      ref.read(unifiedLoggerProvider).logWarning('done');"))) == 1

    def test_ref_use_after_the_guard_region_ends(self, tmp_path):
        source = _notifier("      if (ref.mounted) {\n        state = state.copyWith(isLoading: false);\n      }\n      ref.invalidate(otherProvider);")
        assert len(_found(tmp_path, source)) == 1

    def test_reported_as_a_finally_not_a_catch(self, tmp_path):
        source = _notifier("      state = state.copyWith(isLoading: false);")
        assert _found(tmp_path, source, ViolationType.MISSING_MOUNTED_IN_CATCH) == []


class TestClean:
    def test_plain_field_and_captured_logger(self, tmp_path):
        assert _found(tmp_path, _notifier("      _isProcessing = false;\n      logger.logInfo('done');")) == []

    def test_positive_check_guards_the_state_update(self, tmp_path):
        assert _found(tmp_path, _notifier("      if (ref.mounted) state = state.copyWith(isLoading: false);")) == []

    def test_early_return_guard_before_the_use(self, tmp_path):
        assert _found(tmp_path, _notifier("      if (!ref.mounted) return;\n      state = state.copyWith(isLoading: false);")) == []

    def test_state_mentioned_only_in_a_string(self, tmp_path):
        assert _found(tmp_path, _notifier("      logger.logInfo('state reset');")) == []
