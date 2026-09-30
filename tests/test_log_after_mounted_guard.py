"""VIOLATION 16 (LOG_AFTER_MOUNTED_GUARD): a failure handler that logs only
once the host is known to be mounted.

The log-first rule: in every ``catch``, log the failure FIRST through a logger
captured while mounted, THEN guard before touching ref / context / state. A
handler that guards first and logs after drops every failure that lands after a
back-out. The check runs at file scope, so a catch anywhere in the file is
judged: notifier, ConsumerState, widget callback, plain State, top-level code.
"""

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner


def _wrap(handler_body: str, head: str = "catch (e, st)") -> str:
    """A ConsumerState method whose try's handler is ``head { handler_body }``."""
    return f"""\
import 'package:flutter_riverpod/flutter_riverpod.dart';

class Probe extends ConsumerStatefulWidget {{
  const Probe({{super.key}});
  @override
  ConsumerState<Probe> createState() => _ProbeState();
}}

class _ProbeState extends ConsumerState<Probe> {{
  bool _pending = false;

  Future<void> _doWork() async {{
    if (!mounted) return;
    final logger = ref.read(unifiedLoggerProvider);
    try {{
      await Future<void>.delayed(Duration.zero);
      if (!mounted) return;
    }} {head} {{
{handler_body}
    }}
  }}

  @override
  Widget build(BuildContext context) => const SizedBox();
}}
"""


def _found(tmp_path, source):
    f = tmp_path / "probe.dart"
    f.write_text(source)
    return [v for v in RiverpodScanner().scan_file(f) if v.violation_type == ViolationType.LOG_AFTER_MOUNTED_GUARD]


class TestFlagged:
    def test_guard_then_log(self, tmp_path):
        source = _wrap("      if (!mounted) return;\n      logger.logError('Failed', error: e, stackTrace: st);")
        (violation,) = _found(tmp_path, source)
        assert violation.line_number == source[:source.index('} catch')].count('\n') + 1
        assert 'first log at line' in violation.context

    def test_guard_then_a_logger_read_from_ref(self, tmp_path):
        source = _wrap("      if (!mounted) return;\n      ref.read(unifiedLoggerProvider).logError('Failed', error: e);")
        assert len(_found(tmp_path, source)) == 1

    def test_block_form_guard_then_log(self, tmp_path):
        source = _wrap("      if (!mounted) {\n        return;\n      }\n      logger.logWarning('Failed');")
        assert len(_found(tmp_path, source)) == 1

    def test_ref_mounted_guard(self, tmp_path):
        source = _wrap("      if (!ref.mounted) return;\n      logger.logError('Failed');")
        assert len(_found(tmp_path, source)) == 1

    def test_context_mounted_disjunct_guard(self, tmp_path):
        source = _wrap("      if (!context.mounted || _pending) return;\n      logger.logError('Failed');")
        assert len(_found(tmp_path, source)) == 1

    def test_route_presence_guard(self, tmp_path):
        source = _wrap("      if (!isOnActiveRoute) return;\n      logger.logError('Failed');")
        assert len(_found(tmp_path, source)) == 1

    def test_log_only_inside_a_positive_mounted_check(self, tmp_path):
        source = _wrap("      if (mounted) {\n        logger.logError('Failed');\n        setState(() => _pending = false);\n      }")
        assert len(_found(tmp_path, source)) == 1

    def test_log_only_inside_a_positive_mounted_conjunction(self, tmp_path):
        source = _wrap("      if (mounted && _pending) logger.logError('Failed');")
        assert len(_found(tmp_path, source)) == 1

    def test_log_nested_in_a_block_after_the_guard(self, tmp_path):
        source = _wrap("      if (!mounted) return;\n      if (e is StateError) {\n        logger.logError('Failed');\n      }")
        assert len(_found(tmp_path, source)) == 1

    def test_on_type_catch(self, tmp_path):
        source = _wrap("      if (!mounted) return;\n      logger.logError('Failed');", head="on StateError catch (e)")
        assert len(_found(tmp_path, source)) == 1

    def test_a_log_in_a_callback_before_the_guard_does_not_record_the_failure(self, tmp_path):
        source = _wrap("      scheduleRetry(onGiveUp: (reason) {\n        logger.logWarning('Gave up: $reason');\n      });\n      if (!mounted) return;\n      logger.logError('Failed', error: e);")
        assert len(_found(tmp_path, source)) == 1

    def test_a_binding_less_on_clause(self, tmp_path):
        source = _wrap("      if (!mounted) return;\n      logger.logWarning('Timed out');", head="on TimeoutException")
        assert len(_found(tmp_path, source)) == 1

    def test_every_log_level_counts(self, tmp_path):
        for level in ('Error', 'Warning', 'Critical', 'Info', 'Debug', 'Verbose'):
            source = _wrap(f"      if (!mounted) return;\n      logger.log{level}('Failed');")
            assert len(_found(tmp_path, source)) == 1, level

    def test_catch_error_callback_that_guards_then_logs(self, tmp_path):
        source = """\
class _S extends State<W> {
  void go(UnifiedLogger logger) {
    work().catchError((e) {
      if (!mounted) return;
      logger.logError('Failed', error: e);
    });
  }
}
"""
        (violation,) = _found(tmp_path, source)
        assert violation.context.startswith('.catchError callback')
        assert 'try / await / catch' in violation.fix_instructions

    def test_on_error_callback_that_guards_then_logs(self, tmp_path):
        source = """\
class _S extends State<W> {
  void listen(UnifiedLogger logger) {
    _sub = events.listen(
      _onEvent,
      onError: (Object e, StackTrace st) {
        if (!mounted) return;
        logger.logError('Stream failed', error: e, stackTrace: st);
      },
    );
  }
}
"""
        (violation,) = _found(tmp_path, source)
        assert violation.context.startswith('onError callback')
        assert 'before subscribing' in violation.fix_instructions

    def test_a_catch_in_a_plain_state_is_judged(self, tmp_path):
        source = """\
class _S extends State<W> {
  Future<void> go(UnifiedLogger logger) async {
    try {
      await work();
    } catch (e) {
      if (!mounted) return;
      logger.logError('Failed', error: e);
    }
  }
}
"""
        assert len(_found(tmp_path, source)) == 1

    def test_advice_teaches_log_first_then_guard(self, tmp_path):
        (violation,) = _found(tmp_path, _wrap("      if (!mounted) return;\n      logger.logError('Failed');"))
        advice = violation.fix_instructions
        example_catch = advice[advice.index('} catch (e, st) {'):]
        assert example_catch.index("logger.logError('Failed'") < example_catch.index('if (!mounted) return;')
        assert 'capture it before the try' in advice


    def test_on_done_callback_that_guards_then_logs(self, tmp_path):
        source = """\
class AthletesService extends _$AthletesService {
  void subscribe(UnifiedLogger logger) {
    _sub = events.listen(
      _onEvent,
      onDone: () {
        _sub = null;
        if (!ref.mounted) return;
        final logger = ref.read(unifiedLoggerProvider);
        logger.logWarning('Realtime stream closed');
      },
    );
  }
}
"""
        (violation,) = _found(tmp_path, source)
        assert violation.context.startswith('onDone callback')
        assert 'before subscribing' in violation.fix_instructions


class TestClean:
    def test_log_first_then_guard(self, tmp_path):
        assert _found(tmp_path, _wrap("      logger.logError('Failed', error: e);\n      if (!mounted) return;\n      setState(() => _pending = false);")) == []

    def test_no_guard(self, tmp_path):
        assert _found(tmp_path, _wrap("      logger.logError('Failed', error: e);")) == []

    def test_guard_and_no_log(self, tmp_path):
        assert _found(tmp_path, _wrap("      if (!mounted) return;\n      setState(() => _pending = false);")) == []

    def test_a_log_inside_the_guard_runs_when_unmounted(self, tmp_path):
        source = _wrap("      if (!mounted) {\n        logger.logWarning('Gone before the failure was shown');\n        return;\n      }\n      logger.logError('Failed');")
        assert _found(tmp_path, source) == []

    def test_a_guard_in_a_block_that_does_not_contain_the_log(self, tmp_path):
        source = _wrap("      if (_pending) {\n        if (!mounted) return;\n        setState(() => _pending = false);\n      }\n      logger.logError('Failed');")
        assert _found(tmp_path, source) == []

    def test_a_guard_that_does_not_exit_is_not_a_guard(self, tmp_path):
        source = _wrap("      if (!mounted) {\n        _pending = true;\n      }\n      logger.logError('Failed');")
        assert _found(tmp_path, source) == []

    def test_a_conditional_conjunction_is_not_a_guard(self, tmp_path):
        source = _wrap("      if (!mounted && _pending) return;\n      logger.logError('Failed');")
        assert _found(tmp_path, source) == []

    def test_the_else_branch_of_a_positive_check_runs_unmounted(self, tmp_path):
        source = _wrap("      if (mounted) {\n        setState(() => _pending = false);\n      } else {\n        logger.logError('Failed');\n      }")
        assert _found(tmp_path, source) == []

    def test_a_callback_inside_the_catch_is_outside_its_flow(self, tmp_path):
        source = _wrap("      logger.logError('Failed');\n      Future.microtask(() {\n        if (!mounted) return;\n        logger.logInfo('Retrying');\n      });")
        assert _found(tmp_path, source) == []

    def test_a_catch_whose_only_log_is_in_a_callback_is_not_judged_on_it(self, tmp_path):
        source = _wrap("      unawaited(retry().then((_) async {\n        if (!mounted) return;\n        logger.logInfo('Retried');\n      }));")
        assert _found(tmp_path, source) == []

    def test_a_log_in_a_callback_defined_after_the_guard_is_not_the_catch_logging(self, tmp_path):
        source = _wrap("      if (!mounted) return;\n      showDialog(context: context, builder: (ctx) {\n        logger.logInfo('Showing the failure dialog');\n        return const SizedBox();\n      });")
        assert _found(tmp_path, source) == []

    def test_comments_and_strings_are_not_code(self, tmp_path):
        source = _wrap("      logger.logError('if (!mounted) return; then logError', error: e);\n      // if (!mounted) return;\n      if (!mounted) return;")
        assert _found(tmp_path, source) == []

    def test_an_arrow_catch_error_callback_holds_no_guard(self, tmp_path):
        source = """\
class _S extends State<W> {
  void go(UnifiedLogger logger) {
    work().catchError((e) => logger.logError('Failed', error: e));
  }
}
"""
        assert _found(tmp_path, source) == []

    def test_an_on_error_callback_that_logs_first(self, tmp_path):
        source = """\
class _S extends State<W> {
  void listen(UnifiedLogger logger) {
    _sub = events.listen(_onEvent, onError: (Object e) {
      logger.logError('Stream failed', error: e);
      if (!mounted) return;
      setState(() => _failed = true);
    });
  }
}
"""
        assert _found(tmp_path, source) == []

    def test_extension_and_mixin_on_clauses_are_not_handlers(self, tmp_path):
        source = """\
extension Tools on Widget {
  void go(UnifiedLogger logger) {
    if (!mounted) return;
    logger.logInfo('x');
  }
}

mixin Helper on State<W> {
  void go(UnifiedLogger logger) {
    if (!mounted) return;
    logger.logInfo('x');
  }
}
"""
        assert _found(tmp_path, source) == []

    def test_an_on_error_tear_off_is_not_a_literal(self, tmp_path):
        source = """\
class _S extends State<W> {
  void listen() {
    _sub = events.listen(_onEvent, onError: _onError);
  }
}
"""
        assert _found(tmp_path, source) == []

    def test_a_log_before_the_guard_records_the_failure_even_with_more_after(self, tmp_path):
        source = _wrap("      logger.logError('Failed', error: e);\n      if (!mounted) return;\n      logger.logInfo('Showing the failure');")
        assert _found(tmp_path, source) == []

    def test_an_on_done_callback_that_logs_first(self, tmp_path):
        source = """\
class _S extends State<W> {
  void listen(UnifiedLogger logger) {
    _sub = events.listen(_onEvent, onDone: () {
      logger.logWarning('Stream closed');
      if (!mounted) return;
      setState(() => _sub = null);
    });
  }
}
"""
        assert _found(tmp_path, source) == []

    def test_a_synchronous_error_arm_is_not_judged(self, tmp_path):
        # AsyncValue.when calls the arm synchronously, right after the guard that
        # precedes it: the arm's own guard is dead code and nothing is lost —
        # the reason .fold callbacks are not judged either.
        source = """\
class Scorekeeper extends _$Scorekeeper {
  ScoreboardState build() {
    return ref.watch(gameProvider).when(
      data: (game) => ScoreboardState.from(game),
      loading: () => ScoreboardState.initial(),
      error: (error, stackTrace) {
        if (!ref.mounted) return ScoreboardState.initial();
        final logger = ref.read(unifiedLoggerProvider);
        logger.logError('Error fetching game', error: error, stackTrace: stackTrace);
        return ScoreboardState.initial();
      },
    );
  }
}
"""
        assert _found(tmp_path, source) == []

    def test_an_arrow_error_arm_holds_no_guard(self, tmp_path):
        source = """\
class Scorekeeper extends _$Scorekeeper {
  ScoreboardState build() => ref.watch(gameProvider).when(
        data: ScoreboardState.from,
        loading: ScoreboardState.initial,
        error: (e, st) => ScoreboardState.initial(),
      );
}
"""
        assert _found(tmp_path, source) == []

    def test_an_error_named_argument_is_not_a_handler(self, tmp_path):
        source = _wrap("      logger.logError('Failed', error: (e as StateError).message);\n      if (!mounted) return;")
        assert _found(tmp_path, source) == []

    def test_an_on_done_tear_off_is_not_a_literal(self, tmp_path):
        source = """\
class _S extends State<W> {
  void listen() {
    _sub = events.listen(_onEvent, onDone: _onDone);
  }
}
"""
        assert _found(tmp_path, source) == []
