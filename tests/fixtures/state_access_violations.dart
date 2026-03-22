// Test fixture: state access violations that should be detected
// Tests state access as ref-equivalent operation — accessing `state` on
// a disposed notifier throws UnmountedRefException (Sentry FLUTTER-950/951/952)

import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'state_access_violations.g.dart';

// =========================================================================
// Case 1: Sync method with state access, no mounted check (FLUTTER-952)
// Pattern: clearDuplicateDetection() in game_add_notifier.dart
// =========================================================================
@riverpod
class SyncStateAccess extends _$SyncStateAccess {
  @override
  String build() => 'initial';

  // VIOLATION: sync method accesses state without mounted check
  // Crashes when called from callback after dialog dismissal
  void clearDetection() {
    state = 'cleared';  // ← VIOLATION: state access without mounted guard
  }
}

// =========================================================================
// Case 2: Async method with state access before mounted check (FLUTTER-951)
// Pattern: completeGame() in baseball_notifier.dart
// =========================================================================
@riverpod
class AsyncStateAccess extends _$AsyncStateAccess {
  @override
  String build() => 'initial';

  // VIOLATION: async method accesses state before mounted check
  Future<void> completeGame() async {
    state = 'completing';  // ← VIOLATION: state access before mounted check
    await someAsyncOperation();
    if (!ref.mounted) return;
    state = 'completed';
  }
}

// =========================================================================
// Case 3: Sync method with state.copyWith, no mounted check
// Pattern: cancelDialog() accessing state.updateState in baseball_controls_notifier
// =========================================================================
@riverpod
class SyncStateCopyWith extends _$SyncStateCopyWith {
  @override
  String build() => 'initial';

  // VIOLATION: sync method reads state via state.length (state. access)
  void cancelDialog() {
    state.length;  // ← VIOLATION: state. access without mounted guard
    state = 'idle';
  }
}

Future<void> someAsyncOperation() async {}
