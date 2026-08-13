// Test fixture: ref operations inside build() that must NOT be flagged.
//
// VIOLATION 4 (ref_read_before_mounted) is an ENTRY-GUARD check — a method
// that can be resumed on an already-disposed provider must guard before it
// touches ref. build() has no entry to guard: the framework calls it while the
// provider is being CREATED, so ref is mounted by definition and a pre-await
// ref operation there cannot throw UnmountedRefException.
//
// Flagging these demanded dead defensive code (`if (!ref.mounted) return null;`
// at the top of a build, for a state that cannot occur) and there is no
// alternative idiom — declaring a reactive dependency REQUIRES ref.watch in
// build(). Origin: SocialScoreKeeper gap #728.

import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'build_ref_op_passing.g.dart';

// =========================================================================
// Case 1: async build() whose FIRST statement is ref.watch (CORRECT)
// The canonical "rebuild when this dependency changes" idiom.
// =========================================================================
@riverpod
class AsyncBuildWatchesDependency extends _$AsyncBuildWatchesDependency {
  @override
  Future<String?> build(String userId) async {
    // Reactive dependency — must be declared synchronously in build().
    ref.watch(subscriptionProvider.select((s) => s.tier));
    return _fetch(userId);
  }

  Future<String?> _fetch(String userId) async {
    if (!ref.mounted) return null;
    final api = ref.read(apiProvider);
    final result = await api.load(userId);
    if (!ref.mounted) return null;
    return result;
  }
}

// =========================================================================
// Case 2: async build() reading a dependency before any await (CORRECT)
// ref.read in build() is equally safe pre-await.
// =========================================================================
@riverpod
class AsyncBuildReadsDependency extends _$AsyncBuildReadsDependency {
  @override
  Future<int> build() async {
    final config = ref.read(configProvider);
    final value = await load(config);
    if (!ref.mounted) return 0;
    return value;
  }
}

// =========================================================================
// Case 3: async build() with ref.listen before any await (CORRECT)
// =========================================================================
@riverpod
class AsyncBuildListens extends _$AsyncBuildListens {
  @override
  Future<String> build() async {
    ref.listen(userProvider, (prev, next) {
      _handleUserChange(next);
    });
    return 'ready';
  }

  void _handleUserChange(Object? next) {
    if (!ref.mounted) return;
  }
}

// =========================================================================
// Case 4: a NON-build async method still requires its entry guard.
// This is the shape VIOLATION 4 exists for and must keep catching — it is
// present here only to prove the exclusion is scoped to build().
// =========================================================================
@riverpod
class NonBuildMethodGuarded extends _$NonBuildMethodGuarded {
  @override
  String build() => 'initial';

  Future<void> refresh() async {
    if (!ref.mounted) return;
    final api = ref.read(apiProvider);
    await api.load('x');
  }
}

Future<int> load(Object config) async => 1;
