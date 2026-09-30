"""VIOLATION 15b: a UI event-handler closure a NOTIFIER builds that uses ref /
state before a ref.mounted guard (reported as DEFERRED_CALLBACK_UNSAFE_REF).

The closure runs when the user taps, after the notifier method returned and
possibly after the notifier was disposed — every use in it is deferred, sync or
async (SocialScoreKeeper gap #822: RemoteDialogManager's dialog buttons).
"""

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner


def _notifier(footer: str) -> str:
    return f"""\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@Riverpod(keepAlive: true)
class DialogManager extends _$DialogManager {{
  @override
  void build() {{}}

  Widget _actions(BuildContext dialogContext, DialogService service) {{
    return TextButton(
{footer}
      child: const Text('OK'),
    );
  }}
}}
"""


def _found(tmp_path, source):
    f = tmp_path / "probe.dart"
    f.write_text(source)
    return [v for v in RiverpodScanner().scan_file(f)
            if v.violation_type == ViolationType.DEFERRED_CALLBACK_UNSAFE_REF and 'Notifier builds' in v.context]


class TestFlagged:
    def test_sync_on_pressed_reading_ref(self, tmp_path):
        (violation,) = _found(tmp_path, _notifier("      onPressed: () {\n        Navigator.of(dialogContext).pop();\n        ref.read(dialogServiceProvider).record();\n      },"))
        assert 'onPressed' in violation.context
        assert 'pass it in' in violation.fix_instructions

    def test_async_on_tap_reading_ref_before_any_await(self, tmp_path):
        assert len(_found(tmp_path, _notifier("      onPressed: () async {\n        ref.read(dialogServiceProvider).record();\n        await launch();\n      },"))) == 1

    def test_state_write_in_a_callback(self, tmp_path):
        assert len(_found(tmp_path, _notifier("      onPressed: () {\n        state = null;\n      },"))) == 1


class TestClean:
    def test_service_read_while_mounted_and_passed_in(self, tmp_path):
        assert _found(tmp_path, _notifier("      onPressed: () {\n        Navigator.of(dialogContext).pop();\n        service.record();\n      },")) == []

    def test_guard_first(self, tmp_path):
        assert _found(tmp_path, _notifier("      onPressed: () {\n        if (!ref.mounted) return;\n        ref.read(dialogServiceProvider).record();\n      },")) == []

    def test_positive_check_region(self, tmp_path):
        assert _found(tmp_path, _notifier("      onPressed: () {\n        if (ref.mounted) ref.read(dialogServiceProvider).record();\n      },")) == []

    def test_widget_classes_are_not_judged_by_this_rule(self, tmp_path):
        source = """\
class _S extends ConsumerState<W> {
  @override
  Widget build(BuildContext context) {
    return TextButton(onPressed: () { ref.read(p).go(); }, child: const Text('x'));
  }
}
"""
        assert _found(tmp_path, source) == []
