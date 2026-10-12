// Test fixture: shapes that look like a captured-Ref guard but are not one.
// Only a `Ref`-typed parameter and a local initialised exactly from `ref` name
// a Ref the method captured. A guard on anything else proves nothing about
// `ref`, and a guard no longer dominates the access once an await separates
// them.

import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'captured_ref_guard_violations.g.dart';

// =========================================================================
// Case 1: the guard is on a non-Ref parameter
// =========================================================================
@riverpod
class GuardOnContext extends _$GuardOnContext {
  @override
  String build() => 'initial';

  Future<void> load(BuildContext build) async {
    if (!ref.mounted) return;
    await fetchRemote();
    if (!build.mounted) return;
    state = 'done';
  }
}

// =========================================================================
// Case 2: the guard is on a local initialised from something other than ref
// =========================================================================
@riverpod
class GuardOnOtherLocal extends _$GuardOnOtherLocal {
  @override
  String build() => 'initial';

  Future<void> load(Holder holder) async {
    if (!ref.mounted) return;
    final build = holder.ref;
    await fetchRemote();
    if (!build.mounted) return;
    state = 'done';
  }
}

// =========================================================================
// Case 3: the guard is on a field
// =========================================================================
@riverpod
class GuardOnField extends _$GuardOnField {
  late Ref _build;

  @override
  String build() => 'initial';

  Future<void> load() async {
    if (!ref.mounted) return;
    await fetchRemote();
    if (!_build.mounted) return;
    state = 'done';
  }
}

// =========================================================================
// Case 4: a guard, then another await, then the access
// =========================================================================
@riverpod
class GuardThenAwait extends _$GuardThenAwait {
  @override
  String build() => 'initial';

  Future<void> load() async {
    if (!ref.mounted) return;
    final build = ref;
    await fetchRemote();
    if (!build.mounted) return;
    await fetchRemote();
    state = 'done';
  }
}

Future<String> fetchRemote() async => 'raw';
