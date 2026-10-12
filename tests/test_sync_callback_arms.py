"""Code an await's own expression runs BEFORE it suspends is not "after the await".

`await result.fold((failure) async { build.read(p); … }, …)` evaluates
`result.fold(…)` first, and `fold` calls the arm it picks before it returns: the
arm runs synchronously, up to its own first `await`, and only then does the outer
`await` suspend. The guard above the await still covers that code. VIOLATION 5
read the arm's lines as post-suspension code and demanded a second guard inside
the arm (SocialScoreKeeper `UserNotifier._loadUser`).

The rule, shared with SocialScoreKeeper's gate #98 (`syncCallbackNames`):

- a closure passed directly to a callee in `SYNC_CALLBACK_NAMES` (`fold`, `when`,
  `map`, `forEach`, …) whose receiver is not visibly a Future or a Stream, inside
  the awaited expression and not inside a function literal of it, runs before
  the callee returns;
- its code up to the closure's OWN first `await` is pre-suspension — not inside
  a loop that holds one of its awaits, never an `await` of a nested closure;
- the code after that await, a closure passed to any other callee, a visibly
  Future / Stream receiver and a closure inside a function literal stay
  post-suspension, exactly as before.

The same reading holds in every check that judges "after an await": VIOLATION 5,
VIOLATION 15 (an async event handler's `ref` use) and the call graph's danger
zone (VIOLATION 10, a sync helper called from an async gap).
"""

import pytest

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner
from riverpod_3_scanner.utils import (
    SYNC_CALLBACK_NAMES,
    _await_operand_end,
    blank_spans,
    blank_string_literals,
    pre_suspension_spans,
    receiver_is_visibly_async,
    remove_comments,
)

AFTER_AWAIT = ViolationType.MISSING_MOUNTED_AFTER_AWAIT
SYNC = ViolationType.SYNC_METHOD_WITHOUT_MOUNTED_CHECK
HANDLER = ViolationType.DEFERRED_CALLBACK_UNSAFE_REF

HEADER_LINES = 9  # lines of `_notifier` above `members`


def _notifier(members: str) -> str:
    return f"""\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@riverpod
class Probe extends _$Probe {{
  @override
  int build() => 0;

{members}
}}
"""


def _order(finding):
    return finding[0].value, finding[1]


def _scan(tmp_path, source):
    (tmp_path / "probe.dart").write_text(source)
    return sorted(((v.violation_type, v.line_number) for v in RiverpodScanner().scan_directory(tmp_path)), key=_order)


def _findings(tmp_path, members):
    """(type, line within `members`, 1-based) of every finding in a Notifier."""
    return [(t, line - HEADER_LINES) for t, line in _scan(tmp_path, _notifier(members))]


def _clean(tmp_path, members):
    assert _findings(tmp_path, members) == []


def _flagged_at(tmp_path, members, *expected):
    assert _findings(tmp_path, members) == sorted(expected, key=_order)


# ---------------------------------------------------------------------------
# The SocialScoreKeeper shape: a guard above the await covers the arm's start
# ---------------------------------------------------------------------------

class TestArmRunsBeforeTheOuterAwaitSuspends:
    def test_the_fold_arm_of_a_captured_ref_after_a_guard_is_clean(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) async {
        final auth = build.read(authProvider.notifier);
        auth.signOut();
        await retry();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""")

    def test_the_fold_arm_of_ref_after_a_guard_is_clean(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load() async {
    if (!ref.mounted) return;
    final result = await usecase.execute();
    if (!ref.mounted) return;
    final value = await result.fold(
      (failure) async {
        final auth = ref.read(authProvider.notifier);
        auth.signOut();
        await retry();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""")

    def test_a_when_arm_is_clean(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final snapshot = await source.read();
    if (!build.mounted) return;
    final value = await snapshot.when(
      data: (rows) async {
        build.read(logProvider).info('rows');
        await persist(rows);
        return 1;
      },
      loading: () async => 0,
      error: (e, s) async => -1,
    );
    log(value);
  }
""")

    def test_a_stream_named_in_an_earlier_argument_does_not_make_a_later_receiver_async(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build, List<int> ids) async {
    if (!build.mounted) return;
    await warm();
    if (!build.mounted) return;
    await publish(
      eventStream,
      ids.map((id) => build.read(cacheProvider).get(id)),
    );
    log('done');
  }
""")

    def test_an_arrow_arm_is_clean(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) => build.read(failureProvider).handle(failure),
      (ok) async => ok,
    );
    log(value);
  }
""")

    def test_a_null_aware_fold_is_clean(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result?.fold(
      (failure) async {
        build.read(failureProvider).handle(failure);
        await retry();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""")

    def test_a_traversal_nested_in_the_arguments_of_the_awaited_call_is_clean(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build, List<int> ids) async {
    if (!build.mounted) return;
    await warm();
    if (!build.mounted) return;
    await Future.wait(
      ids.map((id) async {
        build.read(cacheProvider).touch(id);
        await fetch(id);
      }),
    );
    log('done');
  }
""")

    def test_the_arm_may_run_a_nested_sync_closure_before_its_first_await(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) async {
        failure.causes.forEach((cause) {
          build.read(logProvider).error(cause);
        });
        await retry();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""")

    def test_a_loop_before_the_arms_first_await_that_holds_no_await_is_pre_suspension(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) async {
        for (final cause in failure.causes) {
          build.read(logProvider).error(cause);
        }
        await retry();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""")


# ---------------------------------------------------------------------------
# Still post-suspension: the same code in every other position
# ---------------------------------------------------------------------------

class TestStillPostSuspension:
    def test_a_read_after_the_arms_own_first_await_is_flagged(self, tmp_path):
        # Both the outer await and the arm's own await see the read after the arm's await.
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) async {
        await retry();
        build.read(authProvider.notifier).signOut();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""", (AFTER_AWAIT, 5), (AFTER_AWAIT, 7))

    def test_a_read_in_the_arm_with_no_guard_before_the_outer_await_is_flagged(self, tmp_path):
        # The arm runs right after the previous await resumed: nothing guards it.
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    final value = await result.fold(
      (failure) async {
        build.read(authProvider.notifier).signOut();
        await retry();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""", (AFTER_AWAIT, 3))

    def test_the_same_arm_of_ref_with_no_guard_before_the_outer_await_is_flagged(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load() async {
    if (!ref.mounted) return;
    final result = await usecase.execute();
    final value = await result.fold(
      (failure) async {
        ref.read(authProvider.notifier).signOut();
        await retry();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""", (AFTER_AWAIT, 3))

    def test_a_closure_passed_to_future_delayed_is_flagged(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await Future.delayed(
      const Duration(seconds: 1),
      () => build.read(authProvider.notifier).signOut(),
    );
    log('done');
  }
""", (AFTER_AWAIT, 3))

    def test_a_closure_passed_to_then_is_flagged(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await fetch().then(
      (value) => build.read(cacheProvider).put(value),
    );
    log('done');
  }
""", (AFTER_AWAIT, 3))

    def test_a_closure_passed_to_a_callee_outside_the_set_is_flagged(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.foldIt(
      (failure) async {
        build.read(authProvider.notifier).signOut();
        await retry();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""", (AFTER_AWAIT, 5))

    def test_a_sync_callee_inside_a_then_closure_is_flagged(self, tmp_path):
        # `then` runs its closure later, so the fold inside it does too.
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await fetch().then(
      (result) => result.fold(
        (failure) => build.read(failureProvider).handle(failure),
        (ok) => ok,
      ),
    );
    log('done');
  }
""", (AFTER_AWAIT, 3))

    def test_a_call_without_a_receiver_is_flagged(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await fold(
      (failure) async {
        build.read(authProvider.notifier).signOut();
        await retry();
      },
    );
    log('done');
  }
""", (AFTER_AWAIT, 3))

    def test_a_generator_arm_is_flagged(self, tmp_path):
        # An `async*` body runs when the stream is listened to, not when it is passed.
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    await result.fold(
      (failure) async* {
        build.read(authProvider.notifier).signOut();
        yield 1;
      },
      (ok) async* {
        yield 2;
      },
    ).first;
    log('done');
  }
""", (AFTER_AWAIT, 5))

    def test_a_read_in_a_loop_that_holds_the_arms_await_is_flagged(self, tmp_path):
        # The second iteration runs after the arm's await resumed.
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) async {
        while (failure.retryable) {
          build.read(authProvider.notifier).signOut();
          await retry();
        }
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""", (AFTER_AWAIT, 5))

    def test_a_read_after_the_awaited_statement_is_flagged(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) async => 1,
      (ok) async => 3,
    );
    build.read(authProvider.notifier).signOut();
  }
""", (AFTER_AWAIT, 5))


class TestNothingNewIsFlagged:
    def test_a_guard_inside_the_arms_pre_suspension_code_is_still_a_guard_for_the_window(self, tmp_path):
        # Only uses are left out of the window; a guard found anywhere in it still counts, as in 1.17.0:
        # the outer await stays clean and the arm's own await is the one that is judged.
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) async {
        if (!build.mounted) return 1;
        await retry();
        build.read(authProvider.notifier).signOut();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""", (AFTER_AWAIT, 8))


    def test_the_same_for_ref_and_for_ref_mounted(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load() async {
    if (!ref.mounted) return;
    final result = await usecase.execute();
    if (!ref.mounted) return;
    final value = await result.fold(
      (failure) async {
        if (!ref.mounted) return 1;
        await retry();
        ref.read(authProvider.notifier).signOut();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""", (AFTER_AWAIT, 8))


class TestReceiversThatRunTheClosureLater:
    @pytest.mark.parametrize("receiver", [
        "controller.stream",
        "userStream",
        "Stream.fromIterable(ids)",
        "ref.read(feedProvider.stream)",
        "repo.watchAll()",
        "query.snapshots()",
        "fetch().asStream()",
        "ref.read(feedProvider.notifier)",
    ])
    def test_a_visibly_async_receiver_keeps_its_closure_post_suspension(self, tmp_path, receiver):
        _flagged_at(tmp_path, f"""\
  Future<void> load(Ref build) async {{
    if (!build.mounted) return;
    await {receiver}.map(
      (event) => build.read(cacheProvider).put(event),
    ).first;
    log('done');
  }}
""", (AFTER_AWAIT, 3))

    def test_update_on_a_notifier_runs_its_callback_after_it_awaits_the_state(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await ref.read(feedProvider.notifier).update(
      (current) async {
        build.read(cacheProvider).touch();
        await persist(current);
        return current;
      },
    );
    log('done');
  }
""", (AFTER_AWAIT, 3))

    def test_a_local_declared_as_a_stream_is_flagged(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build, Stream<int> events) async {
    if (!build.mounted) return;
    await events.map(
      (event) => build.read(cacheProvider).put(event),
    ).first;
    log('done');
  }
""", (AFTER_AWAIT, 3))

    def test_a_local_initialised_from_a_stream_is_flagged(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final events = controller.stream;
    await events.map(
      (event) => build.read(cacheProvider).put(event),
    ).first;
    log('done');
  }
""", (AFTER_AWAIT, 4))

    def test_a_field_declared_as_a_future_is_flagged(self, tmp_path):
        _flagged_at(tmp_path, """\
  late final Future<List<int>> pending;

  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await pending.forEach(
      (id) => build.read(cacheProvider).touch(id),
    );
    log('done');
  }
""", (AFTER_AWAIT, 5))

    def test_a_local_initialised_from_the_awaited_value_is_not_a_future(self, tmp_path):
        # `await x` yields the value: its `fold` is the sync Either.fold.
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) async {
        build.read(authProvider.notifier).signOut();
        await retry();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }
""")


# ---------------------------------------------------------------------------
# The other checks that judge "after an await"
# ---------------------------------------------------------------------------

class TestEventHandlers:
    def _handler(self, body):
        return f"""\
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class Probe extends ConsumerWidget {{
  const Probe({{super.key}});

  @override
  Widget build(BuildContext context, WidgetRef ref) {{
    return GestureDetector(
      onTap: () async {{
{body}
      }},
    );
  }}
}}
"""

    def test_a_ref_read_in_a_fold_arm_before_its_first_await_is_clean(self, tmp_path):
        assert _scan(tmp_path, self._handler("""\
        if (!context.mounted) return;
        final result = await usecase.execute();
        if (!context.mounted) return;
        await result.fold(
          (failure) async {
            ref.read(loggerProvider).error(failure);
            await retry();
          },
          (ok) async {},
        );
""")) == []

    def test_a_ref_read_after_the_arms_first_await_is_flagged(self, tmp_path):
        assert [t for t, _ in _scan(tmp_path, self._handler("""\
        final result = await usecase.execute();
        await result.fold(
          (failure) async {
            await retry();
            ref.read(loggerProvider).error(failure);
          },
          (ok) async {},
        );
"""))] == [HANDLER]

    def test_a_ref_read_in_a_then_closure_is_flagged(self, tmp_path):
        assert [t for t, _ in _scan(tmp_path, self._handler("""\
        await fetch().then((value) => ref.read(cacheProvider).put(value));
"""))] == [HANDLER]


class TestCallGraphDangerZone:
    HELPER = """\
  void _note() {
    ref.read(logProvider).info('noted');
  }
"""

    def test_a_helper_called_from_the_arm_before_its_first_await_is_not_called_from_an_async_gap(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) async {
        _note();
        await retry();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }

""" + self.HELPER)

    def test_a_helper_called_from_a_named_sync_callback_is_not_called_from_an_async_gap(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await snapshot.when(
      data: (rows) {
        _note();
      },
      loading: () {},
      error: (e, s) {},
    );
  }

""" + self.HELPER)

    def test_a_helper_called_from_a_named_callback_of_another_callee_is_called_from_an_async_gap(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await source.load(
      onDone: (rows) {
        _note();
      },
    );
  }

""" + self.HELPER, (SYNC, 10))

    def test_a_helper_called_from_the_arm_after_its_first_await_is_called_from_an_async_gap(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    final result = await usecase.execute();
    if (!build.mounted) return;
    final value = await result.fold(
      (failure) async {
        await retry();
        _note();
        return 2;
      },
      (ok) async => 3,
    );
    log(value);
  }

""" + self.HELPER, (SYNC, 16))

    def test_a_helper_called_from_a_then_closure_is_called_from_an_async_gap(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await fetch().then((value) {
      _note();
    });
    log('done');
  }

""" + self.HELPER, (SYNC, 9))

    def test_a_helper_called_from_a_named_arm_after_an_await_is_called_from_an_async_gap(self, tmp_path):
        _flagged_at(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await fetch();
    final snapshot = await source.read();
    snapshot.when(
      data: (rows) {
        _note();
      },
      loading: () {},
      error: (e, s) {},
    );
  }

""" + self.HELPER, (SYNC, 14))


# ---------------------------------------------------------------------------
# The helpers
# ---------------------------------------------------------------------------

def _reduce(code):
    return blank_string_literals(remove_comments(code))


def _spans_text(code, await_text="await ", declared_in=""):
    reduced = _reduce(code)
    spans = pre_suspension_spans(reduced, reduced.index(await_text), declared_in)
    return [reduced[begin:finish] for begin, finish in spans]


class TestSyncCallbackNames:
    def test_the_set_is_the_one_gate_98_uses(self):
        assert SYNC_CALLBACK_NAMES == {
            'when', 'maybeWhen', 'whenOrNull', 'map', 'maybeMap', 'mapOrNull', 'whenData', 'fold', 'flatMap',
            'mapLeft', 'getOrElse', 'forEach', 'where', 'any', 'every', 'firstWhere', 'lastWhere',
            'singleWhere', 'firstWhereOrNull', 'lastWhereOrNull', 'expand', 'sort', 'removeWhere',
            'retainWhere', 'putIfAbsent', 'update', 'updateAll', 'reduce', 'indexWhere', 'takeWhile',
            'skipWhile', 'sortBy', 'groupBy', 'whereType',
        }

    @pytest.mark.parametrize("name", sorted(SYNC_CALLBACK_NAMES))
    def test_every_name_in_the_set_exempts_its_closure(self, name):
        text = _spans_text(f"final v = await box.{name}((x) => build.read(p));")
        assert text == [" build.read(p)"]

    def test_a_name_outside_the_set_exempts_nothing(self):
        assert _spans_text("final v = await box.then((x) => build.read(p));") == []


class TestPreSuspensionSpans:
    def test_only_the_code_before_the_arms_first_await_is_a_span(self):
        text = _spans_text("await r.fold((f) async { a(); await b(); c(); }, (o) => d());")
        assert text == [" a(); ", " d()"]

    def test_a_named_argument_closure_is_found(self):
        assert _spans_text("await v.when(data: (d) { a(d); }, loading: () { b(); });") == [" a(d); ", " b(); "]

    def test_a_tear_off_has_no_body(self):
        assert _spans_text("await r.fold(_onFailure, _onOk);") == []

    def test_an_await_of_a_nested_closure_is_not_the_arms_own_first_await(self):
        text = _spans_text("await r.fold((f) async { f.xs.forEach((x) async { await z(x); }); a(); await b(); c(); }, (o) {});")
        assert text == [" f.xs.forEach((x) async { await z(x); }); a(); ", ""]

    def test_a_closure_with_no_await_is_pre_suspension_throughout(self):
        assert _spans_text("await r.fold((f) { a(); b(); }, (o) {});") == [" a(); b(); ", ""]

    def test_an_await_in_a_branch_ends_the_span_in_source_order(self):
        assert _spans_text("await r.fold((f) async { a(); if (c) { await x(); } b(); }, (o) {});") == [
            " a(); if (c) { ", "",
        ]

    def test_a_loop_holding_an_await_is_not_a_span(self):
        text = _spans_text("await r.fold((f) async { a(); while (c) { b(); await x(); } }, (o) {});")
        assert text == [" a(); ", ""]

    def test_a_loop_before_the_first_await_that_holds_none_is_a_span(self):
        text = _spans_text("await r.fold((f) async { for (final x in f) { b(x); } await y(); }, (o) {});")
        assert text == [" for (final x in f) { b(x); } ", ""]

    def test_a_do_while_loop_holding_an_await_is_not_a_span(self):
        text = _spans_text("await r.fold((f) async { a(); do { b(); await x(); } while (c); }, (o) {});")
        assert text == [" a(); ", ""]

    def test_a_callee_inside_a_function_literal_of_the_operand_is_not_a_callee_of_it(self):
        assert _spans_text("await load((v) => v.fold((f) => a(), (o) => b()));") == []

    def test_a_callee_in_the_arguments_of_the_awaited_call_is_pre_suspension(self):
        assert _spans_text("await Future.wait(ids.map((id) => a(id)));") == [" a(id)"]

    def test_only_the_awaited_expression_counts(self):
        reduced = _reduce("await a(); r.fold((f) => b(), (o) => c());")
        assert pre_suspension_spans(reduced, reduced.index("await ")) == []

    def test_a_closure_after_a_binary_operator_is_not_in_the_operand(self):
        reduced = _reduce("final v = await a() + r.fold((f) => b(), (o) => c());")
        assert pre_suspension_spans(reduced, reduced.index("await ")) == []

    def test_a_receiver_declared_as_a_stream_exempts_nothing(self):
        text = _spans_text("await s.map((x) => a(x)).first;", declared_in="final Stream<int> s = make();")
        assert text == []

    def test_the_same_receiver_undeclared_is_taken_for_sync(self):
        assert _spans_text("await s.map((x) => a(x)).first;") == [" a(x)"]

    def test_blank_spans_keeps_length_and_newlines(self):
        text = "ab\ncd\nef"
        blanked = blank_spans(text, [(1, 5)])
        assert blanked == "a \n  \nef" and len(blanked) == len(text)


class TestAwaitOperandEnd:
    @pytest.mark.parametrize("source, operand", [
        ("await a;", "a"),
        ("await a.b(c).d;", "a.b(c).d"),
        ("await a?.b(c);", "a?.b(c)"),
        ("await a.b<T>(c);", "a.b<T>(c)"),
        ("await a[0].b();", "a[0].b()"),
        ("await a!.b();", "a!.b()"),
        ("await (a.b());", "(a.b())"),
        ("await a\n    .b(c)\n    .d();", "a\n    .b(c)\n    .d()"),
        ("await a() + b();", "a()"),
        ("await a(), b;", "a()"),
        ("await a ? b : c;", "a"),
        ("await a != b;", "a"),
        ("await a..b();", "a"),
        ("foo(await a.b(), c);", "a.b()"),
    ])
    def test_the_operand_is_the_member_chain(self, source, operand):
        start = source.index("await") + len("await")
        assert source[start:_await_operand_end(source, start)].strip() == operand


class TestReceiverIsVisiblyAsync:
    @pytest.mark.parametrize("receiver", [
        "stream", "userStream", "_events", "controller.stream", "Stream.fromIterable(xs)", "StreamController<int>()",
        "Future.value(1)", "provider.future", "ref.read(p.future)", "repo.watchAll()", "q.snapshots()",
        "f.asStream()", "f.then((v) => v)", "f.catchError(g)", "f.whenComplete(g)", "f.timeout(d)",
        "ref.read(p.notifier)",
    ])
    def test_a_receiver_that_names_a_future_or_stream(self, receiver):
        # `events` ends in neither word: it is decided from `declared_in` below.
        if receiver == "_events":
            receiver = "_eventStream"
        assert receiver_is_visibly_async(receiver)

    @pytest.mark.parametrize("receiver", [
        "result", "this.result", "ref.watch(p)", "ref.read(p)", "snapshot", "rows.where((r) => r.ok)", "usecase.execute()",
    ])
    def test_a_receiver_that_names_nothing_async(self, receiver):
        assert not receiver_is_visibly_async(receiver)

    @pytest.mark.parametrize("declaration", [
        "final Stream<int> events = make();", "Stream<int> events;", "late final Future<void> events;",
        "Future<Map<String, int>> events() async => {};", "void f(StreamController<int> events) {}",
        "final events = controller.stream;", "var events = repo.watchAll();",
    ])
    def test_a_receiver_declared_async_in_the_class(self, declaration):
        assert receiver_is_visibly_async("events", declaration)

    @pytest.mark.parametrize("declaration", [
        "final List<int> events = make();", "final events = await usecase.execute();", "final events = make();",
        "events == other;",
    ])
    def test_a_receiver_declared_otherwise(self, declaration):
        assert not receiver_is_visibly_async("events", declaration)

    def test_a_receiver_only_a_type_checker_could_decide_is_not_decided(self):
        # The limit, stated: a local whose name and initialiser say nothing is taken for sync.
        assert not receiver_is_visibly_async("changes", "final changes = repo.changes();")
        assert not receiver_is_visibly_async("changes.where((c) => c.ok)", "final changes = repo.changes();")
