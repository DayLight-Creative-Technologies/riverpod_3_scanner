"""VIOLATION 6 (missing mounted in catch) under the LOG-FIRST rule.

The rule: in every ``catch``, log FIRST through a logger captured while mounted
(a value captured while mounted stays safe after unmount, so a failure is never
lost to a back-out), THEN guard before anything that touches ref / state.

Log-first puts a multi-line ``logger.logError(...)`` ahead of the guard, so the
guard sits many lines into the catch body. The check therefore judges the WHOLE
catch body — the leftmost ref/state use against the leftmost guard — instead of a
fixed look-ahead window, and its printed advice teaches log-first-then-guard.
"""

import re

import pytest

from riverpod_3_scanner.checkers import (
    _RE_POSITIVE_MOUNTED_CONDITION_NOTIFIER,
    _RE_POSITIVE_MOUNTED_CONDITION_STATE,
    _blank_mounted_guarded_regions,
    _leftmost_unguarded_danger,
)
from riverpod_3_scanner.scanner import RiverpodScanner

# The two probes that proved the miss (SSK CAMERA-2026-001 chunk 08, round 2).
# Probe A: multi-line log, then an UNGUARDED ref.read — the guard-window missed it.
PROBE_A = """\
import 'package:flutter_riverpod/flutter_riverpod.dart';

class ProbeA extends ConsumerStatefulWidget {
  const ProbeA({super.key});
  @override
  ConsumerState<ProbeA> createState() => _ProbeAState();
}

class _ProbeAState extends ConsumerState<ProbeA> {
  Future<void> _doWork() async {
    if (!mounted) return;
    final logger = ref.read(unifiedLoggerProvider);
    try {
      await Future<void>.delayed(Duration.zero);
      if (!mounted) return;
    } catch (e, st) {
      logger.logError(
        'Probe failed',
        error: e,
        stackTrace: st,
      );
      ref.read(someProvider.notifier).markFailed();
    }
  }
  @override
  Widget build(BuildContext context) => const SizedBox();
}
"""

# Probe B: single-line log, then an UNGUARDED ref.read — always caught, but the
# advice it printed taught guard-first.
PROBE_B = PROBE_A.replace(
    """      logger.logError(
        'Probe failed',
        error: e,
        stackTrace: st,
      );
""",
    "      logger.logError('Probe failed', error: e, stackTrace: st);\n",
).replace("ProbeA", "ProbeB")

# Multi-line log, then the guard, then the ref use: the canonical safe shape.
SAFE_LOG_FIRST = PROBE_A.replace(
    "      ref.read(someProvider.notifier).markFailed();\n",
    "      if (!mounted) return;\n      ref.read(someProvider.notifier).markFailed();\n",
).replace("ProbeA", "ProbeSafe")

# The logger read from ref INSIDE the catch, before the guard: a ref use.
REF_READ_LOGGER_BEFORE_GUARD = PROBE_A.replace(
    """      logger.logError(
        'Probe failed',
        error: e,
        stackTrace: st,
      );
      ref.read(someProvider.notifier).markFailed();
""",
    """      ref.read(unifiedLoggerProvider).logError(
        'Probe failed',
        error: e,
        stackTrace: st,
      );
      if (!mounted) return;
""",
).replace("ProbeA", "ProbeRefLogger")


def _scan(tmp_path, source):
    f = tmp_path / "probe.dart"
    f.write_text(source)
    return RiverpodScanner().scan_file(f)


def _catch_violations(violations):
    return [v for v in violations if v.violation_type.value == "missing_mounted_in_catch"]


class TestWholeCatchBody:
    def test_probe_a_multiline_log_then_unguarded_ref_read_is_flagged(self, tmp_path):
        found = _catch_violations(_scan(tmp_path, PROBE_A))
        assert [v.line_number for v in found] == [16]

    def test_probe_b_single_line_log_then_unguarded_ref_read_is_flagged(self, tmp_path):
        found = _catch_violations(_scan(tmp_path, PROBE_B))
        assert [v.line_number for v in found] == [16]

    def test_multiline_log_then_guard_then_ref_read_is_clean(self, tmp_path):
        assert _catch_violations(_scan(tmp_path, SAFE_LOG_FIRST)) == []

    def test_ref_read_logger_before_the_guard_is_flagged(self, tmp_path):
        found = _catch_violations(_scan(tmp_path, REF_READ_LOGGER_BEFORE_GUARD))
        assert [v.line_number for v in found] == [16]

    def test_context_names_the_use_and_its_line(self, tmp_path):
        (violation,) = _catch_violations(_scan(tmp_path, PROBE_A))
        assert "ref.read at line 22" in violation.context

    def test_snippet_reaches_the_offending_line(self, tmp_path):
        # The dangerous use is 6 lines below the `catch` line; the snippet
        # must show it, not stop at the log call.
        (violation,) = _catch_violations(_scan(tmp_path, PROBE_A))
        assert "ref.read(someProvider.notifier).markFailed()" in violation.code_snippet


class TestAdviceTeachesLogFirst:
    """The printed advice is what a developer follows — it must not teach the
    guard-first order the rule replaced."""

    def test_notifier_advice_logs_first_then_guards_with_ref_mounted(self, tmp_path):
        source = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class Counter extends _$Counter {
  @override
  Future<int> build() async => 0;

  Future<void> refresh() async {
    if (!ref.mounted) return;
    final logger = ref.read(myLoggerProvider);
    try {
      await work();
      if (!ref.mounted) return;
    } catch (e, st) {
      logger.logError('Failed', error: e, stackTrace: st);
      state = AsyncError(e, st);
    }
  }
}
"""
        (violation,) = _catch_violations(_scan(tmp_path, source))
        advice = violation.fix_instructions
        assert "log FIRST" in advice
        assert "captured" in advice
        assert "if (!ref.mounted) return;" in advice
        assert "state = AsyncError(e, st);" in advice
        # log line precedes the guard inside the catch sample
        catch_sample = advice[advice.index("} catch (e, st) {"):]
        assert catch_sample.index("logger.logError") < catch_sample.index("if (!ref.mounted)")
        assert "Add at start of catch block" not in advice

    def test_consumer_state_advice_uses_state_mounted_and_set_state(self, tmp_path):
        (violation,) = _catch_violations(_scan(tmp_path, PROBE_A))
        advice = violation.fix_instructions
        assert "if (!mounted) return;" in advice
        assert "ref.mounted" not in advice
        assert "setState(" in advice
        catch_sample = advice[advice.index("} catch (e, st) {"):]
        assert catch_sample.index("logger.logError") < catch_sample.index("if (!mounted)")

    def test_advice_says_a_ref_read_logger_is_a_ref_use(self, tmp_path):
        (violation,) = _catch_violations(_scan(tmp_path, PROBE_A))
        assert "including ref.read(myLoggerProvider)" in violation.fix_instructions

    def test_catch_error_callback_advice_stays_guard_first_and_points_to_try_catch(self, tmp_path):
        source = """\
import 'package:flutter_riverpod/flutter_riverpod.dart';

class Probe extends ConsumerStatefulWidget {
  const Probe({super.key});
  @override
  ConsumerState<Probe> createState() => _ProbeState();
}

class _ProbeState extends ConsumerState<Probe> {
  void _kick() {
    work().catchError((e) {
      ref.read(someProvider.notifier).markFailed();
    });
  }
  @override
  Widget build(BuildContext context) => const SizedBox();
}
"""
        found = [
            v for v in _scan(tmp_path, source)
            if v.violation_type.value == "deferred_callback_unsafe_ref"
        ]
        assert len(found) == 1
        advice = found[0].fix_instructions
        assert "MUST check mounted before ref operations" in advice
        assert "requires the guard FIRST" in advice
        assert "try { await ... } catch" in advice
        assert "LOG FIRST" in advice

    def test_microtask_advice_logs_first_in_the_catch_sample(self, tmp_path):
        source = """\
import 'package:flutter_riverpod/flutter_riverpod.dart';

class Probe extends ConsumerStatefulWidget {
  const Probe({super.key});
  @override
  ConsumerState<Probe> createState() => _ProbeState();
}

class _ProbeState extends ConsumerState<Probe> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() async {
      final logger = ref.read(loggerProvider);
      logger.info('boom');
    });
  }
  @override
  Widget build(BuildContext context) => const SizedBox();
}
"""
        (violation,) = [
            v for v in _scan(tmp_path, source)
            if v.violation_type.value == "deferred_callback_unsafe_ref"
        ]
        advice = violation.fix_instructions
        after = advice[advice.index("AFTER (SAFE):"):]
        catch_sample = after[after.index("} catch (e) {"):]
        assert catch_sample.index("logger.logError") < catch_sample.index("if (!context.mounted)")


class TestLeftmostUnguardedDanger:
    """The one shared owner of 'the guard must PRECEDE the first dangerous use'."""

    DANGER = [re.compile(r"ref\.read")]
    GUARD = re.compile(r"if\s*\(\s*!mounted\s*\)")

    def test_returns_none_when_nothing_is_dangerous(self):
        assert _leftmost_unguarded_danger("logger.log(x);", self.DANGER, self.GUARD) is None

    def test_returns_none_when_the_first_danger_is_guarded(self):
        code = "if (!mounted) return;\nref.read(p);"
        assert _leftmost_unguarded_danger(code, self.DANGER, self.GUARD) is None

    def test_returns_the_danger_when_the_guard_comes_after_it(self):
        code = "ref.read(p);\nif (!mounted) return;"
        match = _leftmost_unguarded_danger(code, self.DANGER, self.GUARD)
        assert match is not None and match.start() == 0

    def test_returns_the_leftmost_danger_across_patterns(self):
        code = "a.state = 1;\nref.read(p);"
        danger = [re.compile(r"ref\.read"), re.compile(r"state\s*=")]
        match = _leftmost_unguarded_danger(code, danger, self.GUARD)
        assert match is not None and match.group(0).startswith("state")

    def test_a_guard_far_from_the_use_still_protects_it(self):
        # The point of the whole-body scan: no line window.
        code = "if (!mounted) return;\n" + "log(x);\n" * 50 + "ref.read(p);"
        assert _leftmost_unguarded_danger(code, self.DANGER, self.GUARD) is None

    def test_a_danger_far_past_the_start_is_still_found(self):
        code = "log(x);\n" * 50 + "ref.read(p);"
        assert _leftmost_unguarded_danger(code, self.DANGER, self.GUARD) is not None


@pytest.mark.parametrize(
    "danger_line",
    [
        "ref.read(p);",
        "ref.watch(p);",
        "ref.invalidate(p);",
        "ref.invalidateSelf();",
        "state = AsyncError(e, st);",
        "state.whenData(print);",
        "this.state = AsyncError(e, st);",
    ],
)
def test_every_dangerous_use_is_flagged_after_a_multiline_log(tmp_path, danger_line):
    source = f"""\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class Counter extends _$Counter {{
  @override
  Future<int> build() async => 0;

  Future<void> refresh() async {{
    if (!ref.mounted) return;
    final logger = ref.read(myLoggerProvider);
    try {{
      await work();
      if (!ref.mounted) return;
    }} catch (e, st) {{
      logger.logError(
        'Failed',
        error: e,
        stackTrace: st,
      );
      {danger_line}
    }}
  }}
}}
"""
    assert len(_catch_violations(_scan(tmp_path, source))) == 1


class TestBlankMountedGuardedRegions:
    """A positive check guards a lexical region, not everything after it."""

    STATE = _RE_POSITIVE_MOUNTED_CONDITION_STATE
    NOTIFIER = _RE_POSITIVE_MOUNTED_CONDITION_NOTIFIER

    def test_braced_block_is_blanked_and_length_and_lines_are_kept(self):
        code = "if (mounted) {\n  ref.read(p);\n}\nref.read(q);"
        out = _blank_mounted_guarded_regions(code, self.STATE)
        assert len(out) == len(code) and out.count("\n") == code.count("\n")
        assert "ref.read(p)" not in out
        assert "ref.read(q)" in out

    def test_brace_less_statement_is_blanked(self):
        out = _blank_mounted_guarded_regions("if (mounted) ref.read(p);\nref.read(q);", self.STATE)
        assert "ref.read(p)" not in out and "ref.read(q)" in out

    def test_compound_condition_is_a_positive_check(self):
        out = _blank_mounted_guarded_regions("if (mounted && f(x)) { ref.read(p); }", self.STATE)
        assert "ref.read" not in out

    def test_else_branch_is_not_guarded(self):
        out = _blank_mounted_guarded_regions("if (mounted) { a(); } else { ref.read(p); }", self.STATE)
        assert "a()" not in out and "ref.read(p)" in out

    def test_early_return_guard_is_not_a_positive_check(self):
        code = "if (!mounted) return;\nref.read(p);"
        assert _blank_mounted_guarded_regions(code, self.STATE) == code

    def test_notifier_form_uses_ref_mounted_and_state_form_does_not(self):
        code = "if (ref.mounted) { ref.read(p); }"
        assert "ref.read" not in _blank_mounted_guarded_regions(code, self.NOTIFIER)
        assert _blank_mounted_guarded_regions(code, self.STATE) == code

    def test_unrelated_conditions_are_untouched(self):
        code = "if (retries < 3) { ref.read(p); }"
        assert _blank_mounted_guarded_regions(code, self.STATE) == code
