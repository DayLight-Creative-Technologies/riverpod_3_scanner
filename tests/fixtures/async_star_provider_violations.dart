// Test fixture for the v1.11.0 async* function-provider ref check (violations).
//
// Every @riverpod async* provider in this file is UNGUARDED — the scanner
// must flag exactly one ASYNC_STAR_REF_BEFORE_MOUNTED violation for each, for
// a total of 5 violations.
//
// Companion file: async_star_provider_passing.dart

import 'package:riverpod_annotation/riverpod_annotation.dart';

// VIOLATION 1: async* provider, ref.read on the first line, no mounted gate.
@riverpod
Stream<int> unguardedRead(Ref ref) async* {
  final dep = ref.read(depProvider);
  yield* dep.stream();
}

// VIOLATION 2: async* provider, ref.watch first, no mounted gate.
@riverpod
Stream<int> unguardedWatch(Ref ref) async* {
  final dep = ref.watch(depProvider);
  yield dep;
}

// VIOLATION 3: async* provider, ref.listen first, no mounted gate.
@riverpod
Stream<int> unguardedListen(Ref ref) async* {
  ref.listen(depProvider, (_, _) {});
  yield 0;
}

// VIOLATION 4: @Riverpod(keepAlive: true) async* provider, unguarded —
// proves the @Riverpod(...) annotation form is matched, and that keepAlive
// does not exempt a provider (it can still be invalidated).
@Riverpod(keepAlive: true)
Stream<int> unguardedKeepAlive(Ref ref) async* {
  final dep = ref.read(depProvider);
  yield* dep.stream();
}

// VIOLATION 5: a mounted gate exists, but it comes AFTER the first ref.read.
// Order matters — the read still runs first, so this is a violation.
@riverpod
Stream<int> guardAfterRead(Ref ref) async* {
  final dep = ref.read(depProvider);
  if (!ref.mounted) return;
  yield* dep.stream();
}

// Stub.
final depProvider = Provider<dynamic>((ref) => null);
