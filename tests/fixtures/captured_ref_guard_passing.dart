// Test fixture: a mounted guard on a Ref the method CAPTURED (SSK gap #1073).
// A build's work reads the Ref its build captured: `final build = ref;` as the
// first statement of build(), `Ref build` as a parameter of a method it starts.
// Past `if (!build.mounted) return;` the Notifier's current `ref` IS that
// build's Ref (riverpod 3.4.3 ref.dart:112, element.dart:616-618), so the guard
// is a guard for `ref` too and no redundant `ref.mounted` is demanded.

import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'captured_ref_guard_passing.g.dart';

// =========================================================================
// Case 1: build() captures its Ref; the load it starts takes it as a parameter
// =========================================================================
@riverpod
class UserLoader extends _$UserLoader {
  @override
  Future<String> build() async {
    final build = ref;
    final cached = await readCache(build);
    if (!build.mounted) return 'initial';
    state = AsyncData(cached);
    return load(build);
  }

  Future<String> load(Ref build) async {
    if (!build.mounted) return 'initial';
    final fresh = await fetchRemote();
    if (!build.mounted) return 'initial';
    state = AsyncData(fresh);
    return fresh;
  }

  // The refresh captures the build current when it is asked for.
  Future<void> reload() async {
    if (!ref.mounted) return;
    final build = ref;
    final next = await load(build);
    if (!build.mounted) return;
    state = AsyncData(next);
  }
}

// =========================================================================
// Case 2: catch / finally guard on the captured Ref, early return and
// positive block
// =========================================================================
@riverpod
class GuardedFailures extends _$GuardedFailures {
  @override
  String build() => 'initial';

  Future<void> run(Ref build) async {
    if (!build.mounted) return;
    try {
      await fetchRemote();
      if (!build.mounted) return;
      state = 'done';
    } catch (e) {
      if (build.mounted) {
        state = 'failed';
      }
    } finally {
      if (build.mounted) state = 'idle';
    }
  }
}

Future<String> fetchRemote() async => 'raw';
Future<String> readCache(Ref build) async => 'cached';
