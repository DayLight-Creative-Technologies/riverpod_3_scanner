// Test fixture: state = await pattern violations
// Tests STATE_ASSIGN_AWAIT detection — state assigned directly from await expression

import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'state_assign_await_violations.g.dart';

@riverpod
class StateAssignAwaitViolations extends _$StateAssignAwaitViolations {
  @override
  AsyncValue<String> build() => const AsyncData('initial');

  // VIOLATION: state = await — needs restructuring
  Future<void> fetchDataBad1() async {
    if (!ref.mounted) return;
    state = await AsyncValue.guard(() => someApi());  // ← VIOLATION
  }

  // VIOLATION: state = await with different expression
  Future<void> fetchDataBad2() async {
    if (!ref.mounted) return;
    state = await ref.read(someProvider.future);  // ← VIOLATION
  }
}

Future<String> someApi() async => 'data';
