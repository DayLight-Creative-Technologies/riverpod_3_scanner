"""Tests for check_build_listen_sync_state_mutation.

A `ref.listen(P, cb)` registered in a notifier crashes with a build-phase
provider modification when P is a SYNC + REACTIVE provider (ref.watch-derived,
so it can be flushed + notify synchronously when read dirty mid-build) AND the
callback mutates `state` synchronously. These tests pin that the checker flags
exactly the dangerous shapes and excludes every safe one — deferral, async
providers, and imperative sync notifiers.

Detection needs cross-file provider async-ness/reactivity, so every test writes
the provider definitions AND the listener into a directory and uses
scan_directory (single-file scan_file has no cross-file analysis).
"""

from pathlib import Path

from riverpod_3_scanner.scanner import RiverpodScanner

VIOLATION = "build_listen_sync_state_mutation"

# ── Provider definitions (separate files, mirroring real project layout) ──────

# SYNC + REACTIVE (ref.watch-derived) — dangerous to sync-mutate state on.
SYNC_REACTIVE_PROVIDER = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class TeamListNotifier extends _$TeamListNotifier {
  @override
  TeamListState build() {
    final async = ref.watch(allTeamsStreamProvider);
    return TeamListState(items: async.value ?? const []);
  }
  List<TeamEntity> query(TeamListFilter f) => const [];
}
"""

# SYNC + REACTIVE function provider.
SYNC_REACTIVE_FN_PROVIDER = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
List<GameEntity> gamesByTournament(Ref ref, int tournamentId) {
  final all = ref.watch(allGamesStreamProvider);
  return all.where((g) => g.tournamentId == tournamentId).toList();
}
"""

# ASYNC StreamProvider — never flushes a new value mid-build (safe).
ASYNC_STREAM_PROVIDER = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
Stream<List<MediaEntity>> allGalleryMediaStream(Ref ref) async* {}
"""

# ASYNC notifier — .select on it is safe.
ASYNC_NOTIFIER_PROVIDER = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class GameNotifier extends _$GameNotifier {
  @override
  AsyncValue<GameEntity> build(int gameId) => const AsyncLoading();
}
"""

# SYNC but IMPERATIVE (no ref.watch — driven by an external observer). Never
# flushes mid-build, so listening from a state-mutating callback is safe.
SYNC_IMPERATIVE_PROVIDER = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class AppLifecycleNotifier extends _$AppLifecycleNotifier {
  @override
  AppLifecycleState build() => AppLifecycleState.resumed;
  void set(AppLifecycleState s) => state = s;
}
"""


def _scan(tmp_path: Path, listener_src: str, *provider_srcs: str) -> list:
    (tmp_path / "listener.dart").write_text(listener_src)
    for i, src in enumerate(provider_srcs):
        (tmp_path / f"provider_{i}.dart").write_text(src)
    scanner = RiverpodScanner()
    violations = scanner.scan_directory(tmp_path)
    return [v for v in violations if v.violation_type.value == VIOLATION]


# ── Dangerous shapes — MUST be flagged ───────────────────────────────────────

def test_inline_lambda_calling_state_mutating_helper_is_flagged(tmp_path):
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class GameAddNotifier extends _$GameAddNotifier {
  @override
  GameAddState build() {
    final n = ref.read(teamListProvider.notifier);
    ref.listen(teamListProvider, (_, _) {
      if (!ref.mounted) return;
      _refresh(n);
    });
    return const GameAddState();
  }
  void _refresh(TeamListNotifier n) {
    state = state.copyWith(availableTeams: n.query(const TeamListFilter()));
  }
}
"""
    hits = _scan(tmp_path, listener, SYNC_REACTIVE_PROVIDER)
    assert len(hits) == 1, [h.context for h in hits]


def test_tearoff_callback_that_sets_state_is_flagged(tmp_path):
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class GameEditNotifier extends _$GameEditNotifier {
  @override
  GameEditState build(String gameKey) {
    ref.listen(teamListProvider, _onTeamListChanged);
    return const GameEditState();
  }
  void _onTeamListChanged(TeamListState? prev, TeamListState next) {
    if (!ref.mounted) return;
    state = state.copyWith(availableTeams: next.items);
  }
}
"""
    hits = _scan(tmp_path, listener, SYNC_REACTIVE_PROVIDER)
    assert len(hits) == 1, [h.context for h in hits]


def test_direct_inline_state_assignment_is_flagged(tmp_path):
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class TournamentEditNotifier extends _$TournamentEditNotifier {
  @override
  TournamentEditState build(int id) {
    ref.listen(teamListProvider, (_, next) {
      if (!ref.mounted) return;
      state = state.copyWith(teams: next.items);
    });
    return const TournamentEditState();
  }
}
"""
    hits = _scan(tmp_path, listener, SYNC_REACTIVE_PROVIDER)
    assert len(hits) == 1, [h.context for h in hits]


def test_sync_reactive_function_provider_tearoff_is_flagged(tmp_path):
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class TournamentGamesNotifier extends _$TournamentGamesNotifier {
  @override
  TournamentGamesState build(int id) {
    ref.listen(gamesByTournamentProvider(id), _onGamesChanged);
    return const TournamentGamesState();
  }
  void _onGamesChanged(List<GameEntity>? p, List<GameEntity> next) {
    state = state.copyWith(games: next);
  }
}
"""
    hits = _scan(tmp_path, listener, SYNC_REACTIVE_FN_PROVIDER)
    assert len(hits) == 1, [h.context for h in hits]


# ── Safe shapes — MUST NOT be flagged ────────────────────────────────────────

def test_microtask_deferred_inline_is_not_flagged(tmp_path):
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class GameAddNotifierFixed extends _$GameAddNotifierFixed {
  @override
  GameAddState build() {
    final n = ref.read(teamListProvider.notifier);
    ref.listen(teamListProvider, (_, _) {
      Future.microtask(() {
        if (!ref.mounted) return;
        _refresh(n);
      });
    });
    return const GameAddState();
  }
  void _refresh(TeamListNotifier n) {
    state = state.copyWith(availableTeams: n.query(const TeamListFilter()));
  }
}
"""
    assert _scan(tmp_path, listener, SYNC_REACTIVE_PROVIDER) == []


def test_tearoff_dispatched_via_microtask_is_not_flagged(tmp_path):
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class GameEditNotifierFixed extends _$GameEditNotifierFixed {
  @override
  GameEditState build(String gameKey) {
    ref.listen(teamListProvider, (prev, next) {
      Future.microtask(() {
        if (!ref.mounted) return;
        _onTeamListChanged(prev, next);
      });
    });
    return const GameEditState();
  }
  void _onTeamListChanged(TeamListState? prev, TeamListState next) {
    state = state.copyWith(availableTeams: next.items);
  }
}
"""
    assert _scan(tmp_path, listener, SYNC_REACTIVE_PROVIDER) == []


def test_async_stream_provider_listener_is_not_flagged(tmp_path):
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class GalleryListNotifier extends _$GalleryListNotifier {
  @override
  GalleryListState build() {
    ref.listen(allGalleryMediaStreamProvider, (_, next) => _onDataChanged(next));
    return const GalleryListState();
  }
  void _onDataChanged(AsyncValue<List<MediaEntity>> next) {
    state = state.copyWith(items: next.value ?? const []);
  }
}
"""
    assert _scan(tmp_path, listener, ASYNC_STREAM_PROVIDER) == []


def test_async_provider_select_listener_is_not_flagged(tmp_path):
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class ScorekeeperIntentNotifier extends _$ScorekeeperIntentNotifier {
  @override
  ScorekeeperIntentState build() {
    ref.listen(gameProvider(1).select((g) => g.value?.activeScorekeeper), (prev, next) {
      if (!ref.mounted) return;
      state = state.copyWith(activeScorekeeper: next);
    });
    return const ScorekeeperIntentState();
  }
}
"""
    assert _scan(tmp_path, listener, ASYNC_NOTIFIER_PROVIDER) == []


def test_imperative_sync_provider_listener_is_not_flagged(tmp_path):
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class PresenceNotifier extends _$PresenceNotifier {
  @override
  PresenceStatus build() {
    ref.listen(appLifecycleProvider, (previous, next) {
      if (!ref.mounted) return;
      state = state.copyWith(lastLifecycle: next);
    });
    return const PresenceStatus();
  }
}
"""
    assert _scan(tmp_path, listener, SYNC_IMPERATIVE_PROVIDER) == []


def test_state_assignment_only_inside_timer_callback_is_not_flagged(tmp_path):
    # realtime_readiness shape (gap #386, Defect A): the connectivity listener
    # arms a poll timer whose callback sets state. Timer / Timer.periodic
    # callbacks are dispatched by the event loop and never run synchronously
    # mid-build, so the `state = true` is off-frame — must NOT be flagged.
    listener = """\
import 'dart:async';
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class ReadinessNotifier extends _$ReadinessNotifier {
  Timer? _pollTimer;
  @override
  bool build() {
    ref.listen(teamListProvider, (previous, next) => _onChanged(previous, next));
    return false;
  }
  void _onChanged(TeamListState? previous, TeamListState next) {
    if (!ref.mounted) return;
    _armPoll();
  }
  void _armPoll() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(milliseconds: 200), (_) {
      if (!ref.mounted) return;
      state = true;
      _pollTimer?.cancel();
    });
  }
}
"""
    assert _scan(tmp_path, listener, SYNC_REACTIVE_PROVIDER) == []


def test_local_variable_named_state_is_not_flagged(tmp_path):
    # A `final state = ...` local (shadowing the notifier's `state`) is NOT the
    # notifier's state setter (gap #386, Defect B root).
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class ShadowNotifier extends _$ShadowNotifier {
  @override
  ShadowState build() {
    ref.listen(teamListProvider, (previous, next) {
      if (!ref.mounted) return;
      final state = next.items;
      _log(state.length);
    });
    return const ShadowState();
  }
  void _log(int n) {}
}
"""
    assert _scan(tmp_path, listener, SYNC_REACTIVE_PROVIDER) == []


def test_member_state_assignment_on_other_object_is_not_flagged(tmp_path):
    # `otherObject.state = ...` assigns a field on a different object, not the
    # notifier's own state (gap #386, Defect B).
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class MemberNotifier extends _$MemberNotifier {
  final _machine = _Machine();
  @override
  MemberState build() {
    ref.listen(teamListProvider, (previous, next) {
      if (!ref.mounted) return;
      _machine.state = next.items.length;
    });
    return const MemberState();
  }
}
"""
    assert _scan(tmp_path, listener, SYNC_REACTIVE_PROVIDER) == []


def test_control_flow_keyword_is_not_recursed_as_a_method_call(tmp_path):
    # subscription_purchase shape (gap #386, Defect B): the flagged callback only
    # resets fields, but its body contains `if (`. An earlier listener in the
    # class has an `if (...) {` block holding a `final state = ...` local. The
    # `if` keyword must NOT be treated as a same-class method call reaching it.
    listener = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class PurchaseNotifier extends _$PurchaseNotifier {
  int _failureCount = 0;
  @override
  PurchaseState build() {
    ref.listen(entitlementStreamProvider, (previous, next) {
      if (previous == null) {
        final state = next;
        _log(state);
      }
    });
    ref.listen(teamListProvider, (previous, next) {
      if (next.items.isEmpty) {
        _resetCircuitBreaker();
      }
    });
    return const PurchaseState();
  }
  void _resetCircuitBreaker() {
    _failureCount = 0;
  }
  void _log(Object? o) {}
}
"""
    assert _scan(tmp_path, listener, SYNC_REACTIVE_PROVIDER) == []


def test_single_file_scan_does_not_flag_without_cross_file_analysis(tmp_path):
    # scan_file (no passes) can't resolve provider async-ness/reactivity, so the
    # checker conservatively no-ops — it never flags what it cannot prove.
    f = tmp_path / "combined.dart"
    f.write_text(SYNC_REACTIVE_PROVIDER + """
@riverpod
class GameEditNotifier extends _$GameEditNotifier {
  @override
  GameEditState build(String gameKey) {
    ref.listen(teamListProvider, _onTeamListChanged);
    return const GameEditState();
  }
  void _onTeamListChanged(TeamListState? prev, TeamListState next) {
    state = state.copyWith(availableTeams: next.items);
  }
}
""")
    scanner = RiverpodScanner()
    violations = scanner.scan_file(f)
    assert [v for v in violations if v.violation_type.value == VIOLATION] == []
