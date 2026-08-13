// Test fixture: the dangerous shapes in build() that MUST still be flagged.
//
// Excluding build() from VIOLATION 4 (the entry-guard check) narrows the
// checker only where it could not describe a real crash. The genuinely
// dangerous shape — touching ref AFTER an await, when the provider may have
// been disposed during the gap — is owned by VIOLATION 5
// (missing_mounted_after_await), which scans every await in the method body,
// build() included. These cases pin that coverage so the gap #728 exclusion
// cannot quietly become a blind spot.

import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'build_ref_op_violations.g.dart';

// =========================================================================
// Case 1: async build() touching ref AFTER an await with no mounted check.
// The provider may have been disposed during the await — VIOLATION 5.
// =========================================================================
@riverpod
class AsyncBuildRefAfterAwait extends _$AsyncBuildRefAfterAwait {
  @override
  Future<String> build() async {
    final raw = await fetchRemote();
    final logger = ref.read(loggerProvider);
    logger.log(raw);
    return raw;
  }
}

// =========================================================================
// Case 2: a NON-build async method with no entry guard — the original
// VIOLATION 4 shape, unaffected by the build() exclusion.
// =========================================================================
@riverpod
class RefreshWithoutEntryGuard extends _$RefreshWithoutEntryGuard {
  @override
  String build() => 'initial';

  Future<void> refresh() async {
    final api = ref.read(apiProvider);
    await api.load('x');
  }
}

Future<String> fetchRemote() async => 'raw';
