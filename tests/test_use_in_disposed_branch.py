"""VIOLATION 18 (USE_IN_DISPOSED_BRANCH): a ref / state / setState / host-context
use in code that runs only once the host is gone.

``if (!ref.mounted) return state.value ?? fallback;`` reads ``state`` in the one
branch that exists because the notifier is disposed, and riverpod's state getter
throws UnmountedRefException there. Twelve such sites shipped in SocialScoreKeeper
(gap #825) because every guard check judges what FOLLOWS a guard, never what is
inside its own branch.

Also pins the two fixes that came with it: a negated guard whose branch does not
exit protects nothing, both in the shared dominance helper (catch / finally /
deferred-callback checks) and in the post-await check.
"""

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner


def _notifier(body: str) -> str:
    return f"""\
@riverpod
class TeamNotifier extends _$TeamNotifier {{
  @override
  Future<Team> build() async => Team.blank();

{body}
}}
"""


def _state_class(body: str) -> str:
    return f"""\
class _PageState extends ConsumerState<Page> {{
{body}
}}
"""


def _scan(tmp_path, source):
    f = tmp_path / "probe.dart"
    f.write_text(source)
    return RiverpodScanner().scan_file(f)


def _found(tmp_path, source):
    return [v for v in _scan(tmp_path, source) if v.violation_type == ViolationType.USE_IN_DISPOSED_BRANCH]


class TestFlagged:
    def test_the_gap_825_shape_state_read_in_a_negated_guard_return(self, tmp_path):
        source = _notifier("""\
  Future<Team> addAthlete(String id) async {
    if (!ref.mounted) return Team.blank();
    final result = await _useCase.execute(id);
    if (!ref.mounted) return state.value ?? Team.blank();
    return result;
  }""")
        (violation,) = _found(tmp_path, source)
        assert violation.line_number == 9
        assert violation.context.startswith('state in the branch of the mounted check at line 9')

    def test_state_write_in_a_negated_guard_block(self, tmp_path):
        source = _notifier("""\
  Future<void> load() async {
    await fetch();
    if (!ref.mounted) {
      state = const AsyncLoading();
      return;
    }
  }""")
        (violation,) = _found(tmp_path, source)
        assert violation.line_number == 9

    def test_ref_read_in_a_negated_guard_branch(self, tmp_path):
        source = _notifier("""\
  Future<void> load() async {
    await fetch();
    if (!ref.mounted) {
      ref.read(loggerProvider).logWarning('gone');
      return;
    }
  }""")
        (violation,) = _found(tmp_path, source)
        assert violation.context.startswith('ref.read in the branch')

    def test_ref_read_in_the_else_of_a_positive_check(self, tmp_path):
        source = _notifier("""\
  void onDone() {
    if (ref.mounted) {
      state = const AsyncData(Team());
    } else {
      ref.read(loggerProvider).logInfo('late');
    }
  }""")
        (violation,) = _found(tmp_path, source)
        assert violation.context.startswith('ref.read in the else branch')
        assert violation.line_number == 10

    def test_else_if_chain_after_a_positive_check_is_disposed_code(self, tmp_path):
        source = _notifier("""\
  void onDone(bool retry) {
    if (ref.mounted) {
      return;
    } else if (retry) {
      state = const AsyncLoading();
    }
  }""")
        assert [v.line_number for v in _found(tmp_path, source)] == [10]

    def test_operand_after_a_negated_host_term_in_a_conjunction(self, tmp_path):
        source = _notifier("""\
  bool gone() {
    if (!ref.mounted && state.isLoading) return true;
    return false;
  }""")
        (violation,) = _found(tmp_path, source)
        assert violation.context.startswith('state in the condition')

    def test_operand_after_a_positive_host_term_in_a_disjunction(self, tmp_path):
        source = _notifier("""\
  bool ready() {
    if (ref.mounted || state.hasValue) return true;
    return false;
  }""")
        assert len(_found(tmp_path, source)) == 1

    def test_ternary_then_operand_of_a_negated_check(self, tmp_path):
        source = _notifier("""\
  Team current() => !ref.mounted ? state.value! : Team.blank();""")
        (violation,) = _found(tmp_path, source)
        assert violation.context.startswith('state in the then-operand')

    def test_ternary_else_operand_of_a_positive_check(self, tmp_path):
        source = _notifier("""\
  Team? current() {
    return ref.mounted ? null : state.value;
  }""")
        (violation,) = _found(tmp_path, source)
        assert violation.context.startswith('state in the else-operand')

    def test_state_interpolation_in_a_disposed_branch(self, tmp_path):
        source = _notifier("""\
  String describe() {
    if (!ref.mounted) return 'gone: $state';
    return 'ok';
  }""")
        assert len(_found(tmp_path, source)) == 1

    def test_set_state_in_a_state_class_negated_branch(self, tmp_path):
        source = _state_class("""\
  Future<void> save() async {
    await persist();
    if (!mounted) {
      setState(() => _saving = false);
      return;
    }
  }""")
        (violation,) = _found(tmp_path, source)
        assert violation.context.startswith('setState(')

    def test_context_in_a_state_class_negated_branch(self, tmp_path):
        source = _state_class("""\
  Future<void> save() async {
    await persist();
    if (!mounted) return Navigator.of(context).pop();
  }""")
        (violation,) = _found(tmp_path, source)
        assert violation.context.startswith('context in the branch')

    def test_a_closure_defined_in_a_disposed_branch_still_runs_disposed(self, tmp_path):
        source = _notifier("""\
  Future<void> load() async {
    await fetch();
    if (!ref.mounted) {
      Future.microtask(() => ref.invalidateSelf());
      return;
    }
  }""")
        assert len(_found(tmp_path, source)) == 1

    def test_disjunct_that_can_run_disposed(self, tmp_path):
        source = _notifier("""\
  void sync(bool force) {
    if (force || !ref.mounted) {
      state = const AsyncLoading();
    }
  }""")
        assert len(_found(tmp_path, source)) == 1

    def test_parenthesised_and_double_negated_host_terms_are_host_terms(self, tmp_path):
        source = _notifier("""\
  void sync() {
    if (!(ref.mounted)) {
      state = const AsyncLoading();
    }
  }""")
        assert len(_found(tmp_path, source)) == 1

    def test_the_fix_advice_captures_a_value_while_mounted(self, tmp_path):
        source = _notifier("""\
  Future<Team> load() async {
    await fetch();
    if (!ref.mounted) return state.value!;
    return Team.blank();
  }""")
        (violation,) = _found(tmp_path, source)
        assert 'final previous = state.value;' in violation.fix_instructions
        assert 'if (!ref.mounted) return previous;' in violation.fix_instructions


class TestClean:
    def test_a_value_captured_while_mounted(self, tmp_path):
        source = _notifier("""\
  Future<Team> addAthlete(String id) async {
    if (!ref.mounted) return Team.blank();
    final previous = state.value;
    final result = await _useCase.execute(id);
    if (!ref.mounted) return previous ?? Team.blank();
    return result;
  }""")
        assert _found(tmp_path, source) == []

    def test_short_circuit_never_reads_state_when_disposed(self, tmp_path):
        source = _notifier("""\
  bool stale(int id) {
    if (!ref.mounted || state.value?.id != id) return true;
    return false;
  }""")
        assert _found(tmp_path, source) == []

    def test_positive_check_branch_is_mounted_code(self, tmp_path):
        source = _notifier("""\
  void onDone() {
    if (ref.mounted && state.hasValue) {
      state = const AsyncData(Team());
    }
  }""")
        assert _found(tmp_path, source) == []

    def test_ternary_mounted_side_is_clean(self, tmp_path):
        source = _notifier("""\
  UnifiedLogger log() => ref.mounted ? ref.read(unifiedLoggerProvider) : UnifiedLogger.console();""")
        assert _found(tmp_path, source) == []

    def test_another_receivers_mounted_is_not_the_host(self, tmp_path):
        source = _state_class("""\
  Future<void> open() async {
    final navigatorContext = await resolve();
    if (navigatorContext == null || !navigatorContext.mounted) {
      ref.read(unifiedLoggerProvider).logWarning('no navigator');
      return;
    }
  }""")
        assert _found(tmp_path, source) == []

    def test_operand_before_the_host_term_is_ordinary_code(self, tmp_path):
        source = _state_class("""\
  Future<void> close() async {
    if (!mounted) return;
    if (context.mounted && mounted) {
      Navigator.of(context).pop();
    }
  }""")
        assert _found(tmp_path, source) == []

    def test_named_argument_label_is_not_a_use(self, tmp_path):
        source = _state_class("""\
  Future<void> report() async {
    await send();
    if (!mounted) return logger.logWarning('gone', extra: build(context: null));
  }""")
        assert _found(tmp_path, source) == []

    def test_a_lambda_parameter_named_state_is_not_the_notifier_state(self, tmp_path):
        source = _notifier("""\
  List<Item> ready(List<Item> items) {
    if (!ref.mounted) return items.where((state) => state.isReady).toList();
    return items;
  }""")
        assert _found(tmp_path, source) == []

    def test_uses_in_strings_and_comments_are_not_code(self, tmp_path):
        source = _notifier("""\
  Future<void> load() async {
    await fetch();
    if (!ref.mounted) {
      // state and ref.read(p) are unusable here
      logger.logInfo('state is gone, ref.read would throw');
      return;
    }
  }""")
        assert _found(tmp_path, source) == []

    def test_code_after_a_nested_exiting_guard_cannot_run(self, tmp_path):
        source = _notifier("""\
  void onDone(bool retry) {
    if (!ref.mounted || retry) {
      if (!ref.mounted) return;
      state = const AsyncLoading();
    }
  }""")
        assert _found(tmp_path, source) == []

    def test_a_nested_positive_branch_inside_a_disposed_branch_cannot_run(self, tmp_path):
        source = _notifier("""\
  void onDone(bool retry) {
    if (retry || !ref.mounted) {
      if (ref.mounted) state = const AsyncLoading();
    }
  }""")
        assert _found(tmp_path, source) == []


class TestGuardMustExitToProtect:
    """A negated guard whose branch falls through protects nothing after it."""

    def test_catch_check_ignores_a_fall_through_guard(self, tmp_path):
        source = _notifier("""\
  Future<void> save() async {
    if (!ref.mounted) return;
    final logger = ref.read(unifiedLoggerProvider);
    try {
      await write();
      if (!ref.mounted) return;
    } catch (e) {
      logger.logError('failed');
      if (!ref.mounted) {
        logger.logInfo('disposed');
      }
      state = AsyncError(e, StackTrace.current);
    }
  }""")
        types = [v.violation_type for v in _scan(tmp_path, source)]
        assert ViolationType.MISSING_MOUNTED_IN_CATCH in types

    def test_catch_check_accepts_an_exiting_guard(self, tmp_path):
        source = _notifier("""\
  Future<void> save() async {
    if (!ref.mounted) return;
    final logger = ref.read(unifiedLoggerProvider);
    try {
      await write();
      if (!ref.mounted) return;
    } catch (e) {
      logger.logError('failed');
      if (!ref.mounted) {
        logger.logInfo('disposed');
        return;
      }
      state = AsyncError(e, StackTrace.current);
    }
  }""")
        types = [v.violation_type for v in _scan(tmp_path, source)]
        assert ViolationType.MISSING_MOUNTED_IN_CATCH not in types

    def test_post_await_check_ignores_a_fall_through_guard(self, tmp_path):
        source = _notifier("""\
  Future<void> load() async {
    if (!ref.mounted) return;
    final team = await fetch();
    if (!ref.mounted) {
      debugLog('gone');
    }
    state = AsyncData(team);
  }""")
        types = [v.violation_type for v in _scan(tmp_path, source)]
        assert ViolationType.MISSING_MOUNTED_AFTER_AWAIT in types

    def test_post_await_check_accepts_an_exiting_guard(self, tmp_path):
        source = _notifier("""\
  Future<void> load() async {
    if (!ref.mounted) return;
    final team = await fetch();
    if (!ref.mounted) {
      debugLog('gone');
      return;
    }
    state = AsyncData(team);
  }""")
        types = [v.violation_type for v in _scan(tmp_path, source)]
        assert ViolationType.MISSING_MOUNTED_AFTER_AWAIT not in types

    def test_a_return_inside_a_closure_in_the_branch_does_not_exit_it(self, tmp_path):
        source = _notifier("""\
  Future<void> load() async {
    if (!ref.mounted) return;
    final team = await fetch();
    if (!ref.mounted) {
      items.forEach((item) { return; });
    }
    state = AsyncData(team);
  }""")
        types = [v.violation_type for v in _scan(tmp_path, source)]
        assert ViolationType.MISSING_MOUNTED_AFTER_AWAIT in types
