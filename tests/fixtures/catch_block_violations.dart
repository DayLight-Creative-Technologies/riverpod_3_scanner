// Test fixture: catch block violations that should be detected
// Tests Violation 6 gap — state= and ref.invalidate in catch blocks without mounted guard

import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'catch_block_violations.g.dart';

@riverpod
class CatchBlockViolations extends _$CatchBlockViolations {
  @override
  AsyncValue<String> build() => const AsyncData('initial');

  // VIOLATION: state = in catch block without mounted guard
  Future<void> fetchDataBad1() async {
    if (!ref.mounted) return;
    try {
      final result = await someApi();
      if (!ref.mounted) return;
      state = AsyncData(result);
    } catch (e, stack) {
      state = AsyncError(e, stack);  // ← VIOLATION: state = without mounted guard
    }
  }

  // VIOLATION: ref.invalidateSelf() in catch block without mounted guard
  Future<void> fetchDataBad2() async {
    if (!ref.mounted) return;
    try {
      final result = await someApi();
      if (!ref.mounted) return;
      state = AsyncData(result);
    } catch (e, stack) {
      ref.invalidateSelf();  // ← VIOLATION: ref.invalidate without mounted guard
    }
  }

  // VIOLATION: state. access in catch block without mounted guard
  Future<void> fetchDataBad3() async {
    if (!ref.mounted) return;
    try {
      final result = await someApi();
      if (!ref.mounted) return;
      state = AsyncData(result);
    } catch (e, stack) {
      state.whenData((data) => print(data));  // ← VIOLATION: state. without mounted guard
    }
  }
}

Future<String> someApi() async => 'data';
