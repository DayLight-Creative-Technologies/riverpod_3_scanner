"""VIOLATION 8 (REF_IN_LIFECYCLE_CALLBACK) — ref use exactly where Riverpod asserts.

riverpod 3.x asserts "Cannot use Ref or modify other providers inside
life-cycles/selectors" only while `_debugCallbackStack > 0`: in the callbacks
`_runCallbacks` runs (onDispose, onCancel, onResume, onAddListener,
onRemoveListener) and in `select` / `selectAsync` selectors. A `ref.listen`
LISTENER is not one of them — reading ref there is legal (SocialScoreKeeper gap
#835: verified in riverpod 3.4.3 source and a debug-mode probe) — so the rule,
which used to flag it and never flagged onCancel / onResume / onAddListener /
onRemoveListener, now judges exactly the asserting set.
"""

import pytest

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner


def _found(tmp_path, body: str):
    source = f"""\
class Probe extends _$Probe {{
  @override
  int build() {{
{body}
    return 0;
  }}

  void _flush() {{
    ref.read(queueProvider).flush();
  }}
}}
"""
    f = tmp_path / "probe.dart"
    f.write_text(source)
    return [v for v in RiverpodScanner().scan_file(f) if v.violation_type == ViolationType.REF_IN_LIFECYCLE_CALLBACK]


LIFECYCLE = ["onDispose", "onCancel", "onResume", "onAddListener", "onRemoveListener"]


class TestFlagged:
    @pytest.mark.parametrize("callback", LIFECYCLE)
    def test_direct_ref_read_in_every_asserting_lifecycle_callback(self, tmp_path, callback):
        (violation,) = _found(tmp_path, f"    ref.{callback}(() {{\n      ref.read(loggerProvider).logInfo('x');\n    }});")
        assert f"ref.{callback}()" in violation.context
        assert violation.context.startswith("DIRECT")

    def test_a_same_class_method_that_uses_ref_called_from_on_cancel(self, tmp_path):
        (violation,) = _found(tmp_path, "    ref.onCancel(() {\n      _flush();\n    });")
        assert violation.context.startswith("INDIRECT (same class): _flush()")
        assert "ref.onCancel()" in violation.fix_instructions

    def test_ref_read_inside_a_selector(self, tmp_path):
        (violation,) = _found(tmp_path, "    ref.watch(userProvider.select((u) {\n      return ref.read(flagProvider) ? u.id : null;\n    }));")
        assert "select() selector" in violation.context


class TestClean:
    def test_ref_read_inside_a_ref_listen_listener_is_legal(self, tmp_path):
        assert _found(tmp_path, "    ref.listen(sourceProvider, (previous, next) {\n      ref.read(otherProvider.notifier).sync(next);\n    });") == []

    def test_a_value_captured_before_on_dispose(self, tmp_path):
        assert _found(tmp_path, "    final logger = ref.read(loggerProvider);\n    ref.onDispose(() {\n      logger.logInfo('disposed');\n    });") == []

    def test_a_selector_that_does_not_touch_ref(self, tmp_path):
        assert _found(tmp_path, "    ref.watch(userProvider.select((u) {\n      return u.id;\n    }));") == []
