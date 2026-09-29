"""A string interpolation that reads ``state`` is a state access — in EVERY check.

``'$state'`` and ``'${state}'`` call the notifier's ``state`` getter when the
string is built, and the getter throws on a disposed notifier (riverpod 3.4.3
``lib/src/core/provider/notifier_provider.dart:81-85``, ``_throwIfInvalidUsage()``).
1.14.1 taught the catch-block check (VIOLATION 6) that; the three other places
that decide "does this code touch ``state``" matched ``\\bstate\\s*[.=]`` on raw
text and so missed a bare interpolation:

* VIOLATION 4 — the entry-guard check (first lines of an async method);
* VIOLATION 5 — the after-await check (``has_significant_code_after_await``);
* VIOLATION 10 — the sync-method check (``_find_sync_methods_with_ref_operations``).

They now all go through ``utils.first_state_access``, which blanks comments and
string-literal text first, so ``r'$state'``, ``'\\$state'``, ``'$stateful'`` and
prose like ``'Could not restore state.'`` are not accesses.
"""

import pytest

from riverpod_3_scanner.checkers import _find_sync_methods_with_ref_operations
from riverpod_3_scanner.scanner import RiverpodScanner
from riverpod_3_scanner.utils import (
    RE_STATE_INTERPOLATION,
    first_state_access,
    has_significant_code_after_await,
)

# ---------------------------------------------------------------------------
# Bodies. FLAGGED bodies read state through an interpolation; CLEAN bodies only
# look like they do.
# ---------------------------------------------------------------------------

READS_STATE = [
    pytest.param("logger.logInfo('last value $state');", id="simple-bare"),
    pytest.param('logger.logInfo("last value $state");', id="simple-double-quoted"),
    pytest.param("logger.logInfo('last value ${state}');", id="braced-bare"),
    pytest.param("logger.logInfo('last value ${ state }');", id="braced-bare-spaced"),
    pytest.param("logger.logInfo('last value ${this.state}');", id="braced-this-state"),
    pytest.param("logger.logInfo('last value $state.');", id="simple-then-period"),
    pytest.param("logger.logInfo('''\n  last value $state\n''');", id="triple-quoted"),
    pytest.param("logger.logInfo('done ' 'last value $state');", id="adjacent-strings"),
    pytest.param("logger.logInfo('done ${'last value $state'}');", id="nested-in-braced"),
]

ONLY_LOOKS_LIKE_STATE = [
    pytest.param("logger.logInfo(r'last value $state');", id="raw-string"),
    pytest.param("logger.logInfo(r'last value ${state}');", id="raw-string-braced"),
    pytest.param("logger.logInfo('last value \\$state');", id="escaped-dollar"),
    pytest.param("logger.logInfo('last value \\${state}');", id="escaped-dollar-braced"),
    pytest.param("logger.logInfo('last value $stateful');", id="longer-identifier-stateful"),
    pytest.param("logger.logInfo('last value $state_x $state2 $statement');", id="longer-identifiers"),
    pytest.param("logger.logInfo('last value ${stateful}');", id="braced-longer-identifier"),
    pytest.param("logger.logInfo('last value $this.state');", id="this-then-literal-dot-state"),
    pytest.param("logger.logInfo('Could not restore state.');", id="prose-mentioning-state"),
    pytest.param("logger.logInfo('done'); // last value $state", id="line-comment"),
]

GUARDED_THEN_READS_STATE = [
    pytest.param(
        "if (!ref.mounted) return;\nlogger.logInfo('last value $state');",
        id="guard-then-simple",
    ),
    pytest.param(
        "if (!ref.mounted) return;\nlogger.logInfo('last value ${state}');",
        id="guard-then-braced",
    ),
]


def _scan(tmp_path, source):
    f = tmp_path / "foo.dart"
    f.write_text(source)
    return RiverpodScanner().scan_file(f)


def _types(violations):
    return sorted(v.violation_type.value for v in violations)


def _template(head, body, tail):
    indented = "\n".join(f"    {line}" if line else line for line in body.split("\n"))
    return head + indented + "\n" + tail


# ---------------------------------------------------------------------------
# The shared matcher
# ---------------------------------------------------------------------------


class TestFirstStateAccess:
    def test_direct_access_is_found(self):
        assert first_state_access("state = 1;").start() == 0
        assert first_state_access("final n = state.length;").group(0).startswith("state")

    @pytest.mark.parametrize("body", READS_STATE)
    def test_interpolated_read_is_found(self, body):
        assert first_state_access(body) is not None

    @pytest.mark.parametrize("body", ONLY_LOOKS_LIKE_STATE)
    def test_text_that_only_looks_like_state_is_not_found(self, body):
        assert first_state_access(body) is None

    def test_returns_the_leftmost_of_the_two_forms(self):
        code = "log('$state');\nstate = 1;"
        assert first_state_access(code).start() == code.index("$state")
        code = "state = 1;\nlog('$state');"
        assert first_state_access(code).start() == 0

    def test_positions_are_positions_in_the_original_text(self):
        # Length-preserving blanking: the match position indexes `code` itself.
        code = "log('a very long message that is blanked away');\nlog('$state');"
        assert code[first_state_access(code).start():].startswith("$state")

    def test_the_interpolation_pattern_is_the_one_the_catch_check_uses(self):
        from riverpod_3_scanner.checkers import _CATCH_DANGER_PATTERNS

        assert RE_STATE_INTERPOLATION in _CATCH_DANGER_PATTERNS


# ---------------------------------------------------------------------------
# VIOLATION 5 — after an await
# ---------------------------------------------------------------------------

AFTER_AWAIT_HEAD = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'foo.g.dart';

@riverpod
class Foo extends _$Foo {
  @override
  int build() => 0;

  Future<void> doIt(Logger logger) async {
    if (!ref.mounted) return;
    await Future<void>.delayed(Duration.zero);
"""
AFTER_AWAIT_TAIL = """\
  }
}
"""


class TestAfterAwait:
    @pytest.mark.parametrize("body", READS_STATE)
    def test_unguarded_interpolated_state_after_an_await_is_flagged(self, tmp_path, body):
        source = _template(AFTER_AWAIT_HEAD, body, AFTER_AWAIT_TAIL)
        assert _types(_scan(tmp_path, source)) == ["missing_mounted_after_await"]

    @pytest.mark.parametrize("body", ONLY_LOOKS_LIKE_STATE)
    def test_text_that_only_looks_like_state_after_an_await_is_clean(self, tmp_path, body):
        source = _template(AFTER_AWAIT_HEAD, body, AFTER_AWAIT_TAIL)
        assert _scan(tmp_path, source) == []

    @pytest.mark.parametrize("body", GUARDED_THEN_READS_STATE)
    def test_guarded_then_interpolated_state_is_clean(self, tmp_path, body):
        source = _template(AFTER_AWAIT_HEAD, body, AFTER_AWAIT_TAIL)
        assert _scan(tmp_path, source) == []

    def test_reports_the_await_line(self, tmp_path):
        source = _template(AFTER_AWAIT_HEAD, "logger.logInfo('last value $state');", AFTER_AWAIT_TAIL)
        (violation,) = _scan(tmp_path, source)
        assert violation.line_number == source.split("\n").index("    await Future<void>.delayed(Duration.zero);") + 1

    def test_helper_sees_interpolated_state_as_significant(self):
        assert has_significant_code_after_await("logger.logInfo('last value $state');")
        assert has_significant_code_after_await("logger.logInfo('last value ${state}');")

    def test_helper_ignores_text_that_only_looks_like_state(self):
        assert not has_significant_code_after_await("logger.logInfo(r'last value $state');")
        assert not has_significant_code_after_await("logger.logInfo('last value \\$state');")
        assert not has_significant_code_after_await("logger.logInfo('last value $stateful');")


# ---------------------------------------------------------------------------
# VIOLATION 4 — the entry-guard check (first lines of an async method)
# ---------------------------------------------------------------------------

ENTRY_HEAD = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'foo.g.dart';

@riverpod
class Foo extends _$Foo {
  @override
  int build() => 0;

  Future<void> doIt(Logger logger) async {
"""
ENTRY_TAIL = """\
    await Future<void>.delayed(Duration.zero);
    if (!ref.mounted) return;
    state = 1;
  }
}
"""


class TestEntryGuard:
    @pytest.mark.parametrize("body", READS_STATE)
    def test_interpolated_state_before_any_guard_is_flagged(self, tmp_path, body):
        source = _template(ENTRY_HEAD, body, ENTRY_TAIL)
        (violation,) = _scan(tmp_path, source)
        assert violation.violation_type.value == "ref_read_before_mounted"
        assert "state access before mounted check" in violation.context

    @pytest.mark.parametrize("body", ONLY_LOOKS_LIKE_STATE)
    def test_text_that_only_looks_like_state_is_clean(self, tmp_path, body):
        source = _template(ENTRY_HEAD, body, ENTRY_TAIL)
        assert _scan(tmp_path, source) == []

    @pytest.mark.parametrize("body", GUARDED_THEN_READS_STATE)
    def test_guarded_then_interpolated_state_is_clean(self, tmp_path, body):
        source = _template(ENTRY_HEAD, body, ENTRY_TAIL)
        assert _scan(tmp_path, source) == []

    def test_interpolated_state_right_after_an_await_is_flagged(self, tmp_path):
        # An await inside the first lines does not move the entry guard: the
        # interpolation still runs with no guard before it.
        source = _template(
            ENTRY_HEAD,
            "await Future<void>.delayed(Duration.zero);\nlogger.logInfo('last value $state');",
            ENTRY_TAIL,
        )
        assert "ref_read_before_mounted" in _types(_scan(tmp_path, source))


# ---------------------------------------------------------------------------
# VIOLATION 10 — sync methods
# ---------------------------------------------------------------------------

SYNC_HEAD = """\
class Foo extends _$Foo {
  @override
  int build() => 0;

  void describe(Logger logger) {
"""
SYNC_TAIL = """\
  }
}
"""


def _sync_names(body, is_consumer_state=False):
    class_content = _template(SYNC_HEAD, body, SYNC_TAIL)
    return [name for name, _line, _body in _find_sync_methods_with_ref_operations(class_content, is_consumer_state)]


class TestSyncMethods:
    @pytest.mark.parametrize("body", READS_STATE)
    def test_unguarded_interpolated_state_is_found(self, body):
        assert _sync_names(body) == ["describe"]

    @pytest.mark.parametrize("body", ONLY_LOOKS_LIKE_STATE)
    def test_text_that_only_looks_like_state_is_not_found(self, body):
        assert _sync_names(body) == []

    @pytest.mark.parametrize("body", GUARDED_THEN_READS_STATE)
    def test_guarded_then_interpolated_state_is_not_found(self, body):
        assert _sync_names(body) == []

    def test_a_consumer_state_has_no_notifier_state(self):
        assert _sync_names("logger.logInfo('last value $state');", is_consumer_state=True) == []


E2E_TEMPLATE = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'foo.g.dart';

@riverpod
class Foo extends _$Foo {
  @override
  int build() => 0;

  Future<void> run(Logger logger) async {
    await Future<void>.delayed(Duration.zero);
    describe(logger);
  }

  void describe(Logger logger) {
__BODY__
  }
}
"""


class TestSyncMethodEndToEnd:
    """The sync-method check only fires for a method that runs after an await."""

    def _scan_dir(self, tmp_path, body):
        indented = "\n".join(f"    {line}" for line in body.split("\n"))
        (tmp_path / "foo.dart").write_text(E2E_TEMPLATE.replace("__BODY__", indented))
        return RiverpodScanner().scan_directory(tmp_path)

    def test_interpolated_state_in_a_method_called_after_an_await_is_flagged(self, tmp_path):
        violations = self._scan_dir(tmp_path, "logger.logInfo('last value $state');")
        assert _types(violations) == ["sync_method_without_mounted_check"]

    def test_braced_interpolated_state_is_flagged(self, tmp_path):
        violations = self._scan_dir(tmp_path, "logger.logInfo('last value ${state}');")
        assert _types(violations) == ["sync_method_without_mounted_check"]

    @pytest.mark.parametrize(
        "body",
        [
            "logger.logInfo(r'last value $state');",
            "logger.logInfo('last value \\$state');",
            "logger.logInfo('last value $stateful');",
            "if (!ref.mounted) return;\nlogger.logInfo('last value $state');",
        ],
        ids=["raw", "escaped", "longer-identifier", "guarded-then-state"],
    )
    def test_text_that_only_looks_like_state_is_clean(self, tmp_path, body):
        assert self._scan_dir(tmp_path, body) == []
