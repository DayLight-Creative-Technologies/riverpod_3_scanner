// Test fixture for the v1.11.0 async* function-provider ref check (passing).
//
// Every @riverpod provider in this file is SAFE — the scanner must report
// 0 violations of ASYNC_STAR_REF_BEFORE_MOUNTED (and 0 violations overall)
// for this file.
//
// Companion file: async_star_provider_violations.dart

import 'package:riverpod_annotation/riverpod_annotation.dart';

// PASS 1: async* provider with an `if (!ref.mounted)` gate as the first
// statement, before any ref.read.
@riverpod
Stream<int> guardedFirstStatement(Ref ref) async* {
  if (!ref.mounted) return;
  final dep = ref.read(depProvider);
  yield* dep.stream();
}

// PASS 2: @Riverpod(keepAlive: true) async* provider, guarded before the
// first ref.watch. The annotation form with arguments is matched too.
@Riverpod(keepAlive: true)
Stream<int> guardedKeepAlive(Ref ref) async* {
  if (!ref.mounted) return;
  final dep = ref.watch(depProvider);
  yield dep;
}

// PASS 3: async* provider that never calls ref.read/watch/listen — it only
// passes `ref` through to another function. No dangerous ref operation, so
// there is nothing to guard.
@riverpod
Stream<int> passesRefThrough(Ref ref) async* {
  yield* guardedFirstStatement(ref);
}

// PASS 4: a Future `async` provider with an unguarded first ref.read. An
// `async` body's first line runs synchronously with build(), so this is safe
// — and Future providers are out of this checker's scope regardless.
@riverpod
Future<int> plainAsyncProvider(Ref ref) async {
  final dep = ref.read(depProvider);
  return dep;
}

// PASS 5: a synchronous Stream provider (a normal body, not a generator).
// The first statement runs synchronously with build() — safe.
@riverpod
Stream<int> syncStreamProvider(Ref ref) {
  return ref.read(depProvider).stream();
}

// PASS 6: async* provider whose first ref usage is ref.onDispose — a
// lifecycle registration, not a read/watch/listen. The mounted gate then
// precedes the first real ref.read, so it is safe.
@riverpod
Stream<int> onDisposeThenGuarded(Ref ref) async* {
  ref.onDispose(() {});
  if (!ref.mounted) return;
  final dep = ref.read(depProvider);
  yield* dep.stream();
}

// Stub.
final depProvider = Provider<dynamic>((ref) => null);
