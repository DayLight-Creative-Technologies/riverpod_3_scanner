// Test fixture: state access patterns that should NOT be flagged
// These are correct patterns — mounted check precedes state access

import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'state_access_passing.g.dart';

// =========================================================================
// Case 1: Sync method with mounted check before state access (CORRECT)
// =========================================================================
@riverpod
class SyncStateAccessSafe extends _$SyncStateAccessSafe {
  @override
  String build() => 'initial';

  // CORRECT: mounted check before state access
  void clearDetection() {
    if (!ref.mounted) return;
    state = 'cleared';
  }
}

// =========================================================================
// Case 2: Async method with mounted check before state access (CORRECT)
// =========================================================================
@riverpod
class AsyncStateAccessSafe extends _$AsyncStateAccessSafe {
  @override
  String build() => 'initial';

  // CORRECT: mounted check at entry before state access
  Future<void> completeGame() async {
    if (!ref.mounted) return;
    state = 'completing';
    await someAsyncOperation();
    if (!ref.mounted) return;
    state = 'completed';
  }
}

// =========================================================================
// Case 3: build() method with state-like return (should NOT be flagged)
// build() is called by framework — provider is guaranteed alive
// =========================================================================
@riverpod
class BuildMethodSafe extends _$BuildMethodSafe {
  @override
  FutureOr<String> build() async {
    final data = await fetchData();
    return data;
  }
}

Future<void> someAsyncOperation() async {}
Future<String> fetchData() async => 'data';
