// Test fixture: catch block patterns that should NOT be flagged (passing)
// Verifies no false positives when mounted guards are present

import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'catch_block_passing.g.dart';

@riverpod
class CatchBlockPassing extends _$CatchBlockPassing {
  @override
  AsyncValue<String> build() => const AsyncData('initial');

  // PASSING: state = in catch block WITH mounted guard
  Future<void> fetchDataGood1() async {
    if (!ref.mounted) return;
    try {
      final result = await someApi();
      if (!ref.mounted) return;
      state = AsyncData(result);
    } catch (e, stack) {
      if (!ref.mounted) return;
      state = AsyncError(e, stack);  // ← OK: mounted guard present
    }
  }

  // PASSING: ref.invalidateSelf() in catch block WITH mounted guard
  Future<void> fetchDataGood2() async {
    if (!ref.mounted) return;
    try {
      final result = await someApi();
      if (!ref.mounted) return;
      state = AsyncData(result);
    } catch (e, stack) {
      if (!ref.mounted) return;
      ref.invalidateSelf();  // ← OK: mounted guard present
    }
  }

  // PASSING: ref.read in catch block WITH mounted guard
  Future<void> fetchDataGood3() async {
    if (!ref.mounted) return;
    try {
      final result = await someApi();
      if (!ref.mounted) return;
      state = AsyncData(result);
    } catch (e, stack) {
      if (!ref.mounted) return;
      final logger = ref.read(loggerProvider);
      logger.logError('Failed', error: e, stackTrace: stack);
    }
  }
}

Future<String> someApi() async => 'data';
