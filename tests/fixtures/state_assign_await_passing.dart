// Test fixture: correct patterns that should NOT be flagged
// Verifies no false positives for properly restructured state + await

import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'state_assign_await_passing.g.dart';

@riverpod
class StateAssignAwaitPassing extends _$StateAssignAwaitPassing {
  @override
  AsyncValue<String> build() => const AsyncData('initial');

  // PASSING: await result stored in variable, then state assigned after mounted check
  Future<void> fetchDataGood1() async {
    if (!ref.mounted) return;
    final result = await AsyncValue.guard(() => someApi());
    if (!ref.mounted) return;
    state = result;  // ← OK: separated and guarded
  }

  // PASSING: state assignment without await (sync)
  Future<void> fetchDataGood2() async {
    if (!ref.mounted) return;
    state = const AsyncLoading();  // ← OK: no await
    final result = await someApi();
    if (!ref.mounted) return;
    state = AsyncData(result);  // ← OK: separated and guarded
  }
}

Future<String> someApi() async => 'data';
