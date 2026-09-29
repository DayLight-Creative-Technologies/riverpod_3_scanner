// Test fixture: LOG-FIRST catch blocks that are SAFE — nothing here may be flagged.
// A call on a value captured while mounted (`logger.logError(...)`) may precede
// the guard; only a ref / state use needs the guard before it.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'catch_block_log_first_passing.g.dart';

@riverpod
class LogFirstNotifierPassing extends _$LogFirstNotifierPassing {
  @override
  AsyncValue<String> build() => const AsyncData('initial');

  // PASSING: multi-line captured-logger log, THEN the guard, THEN the state write.
  Future<void> multiLineLogThenGuardThenState() async {
    if (!ref.mounted) return;
    final logger = ref.read(loggerProvider);
    try {
      await someApi();
      if (!ref.mounted) return;
    } catch (e, st) {
      logger.logError(
        'Failed',
        error: e,
        stackTrace: st,
      );
      if (!ref.mounted) return;
      state = AsyncError(e, st);
    }
  }

  // PASSING: log only — no ref / state use anywhere in the catch.
  Future<void> logOnly() async {
    if (!ref.mounted) return;
    final logger = ref.read(loggerProvider);
    try {
      await someApi();
      if (!ref.mounted) return;
    } catch (e, st) {
      logger.logError(
        'Failed',
        error: e,
        stackTrace: st,
      );
    }
  }

  // PASSING: log text that MENTIONS state / ref.read is string content, not a use.
  Future<void> messageMentionsStateAndRef() async {
    if (!ref.mounted) return;
    final logger = ref.read(loggerProvider);
    try {
      await someApi();
      if (!ref.mounted) return;
    } catch (e, st) {
      logger.logError('Could not restore state. ref.read(x) was skipped', error: e, stackTrace: st);
      if (!ref.mounted) return;
      state = AsyncError(e, st);
    }
  }

  // PASSING: a comment that MENTIONS ref.read / state = is not a use, and a
  // comment that mentions the guard is not a guard.
  Future<void> commentsMentionRefAndGuard() async {
    if (!ref.mounted) return;
    final logger = ref.read(loggerProvider);
    try {
      await someApi();
      if (!ref.mounted) return;
    } catch (e, st) {
      // 1. log FIRST — never ref.read(...) here, and state = ... waits for the guard
      logger.logError('Failed', error: e, stackTrace: st);
      // 2. then `if (!ref.mounted) return;`
      if (!ref.mounted) return;
      state = AsyncError(e, st);
    }
  }

  // PASSING: `state` reached through ANOTHER object is not this notifier's state.
  Future<void> otherObjectsState() async {
    if (!ref.mounted) return;
    final logger = ref.read(loggerProvider);
    try {
      await someApi();
      if (!ref.mounted) return;
    } catch (e, st) {
      logger.logError('Failed', error: e, stackTrace: st, phase: snapshot.state.name);
    }
  }
}

class LogFirstStatePassing extends ConsumerState<LogFirstWidget> {
  // PASSING: multi-line log, guard, THEN the ref use.
  Future<void> multiLineLogThenGuardThenRefRead() async {
    if (!mounted) return;
    final logger = ref.read(loggerProvider);
    try {
      await someApi();
      if (!mounted) return;
    } catch (e, st) {
      logger.logError(
        'Probe failed',
        error: e,
        stackTrace: st,
      );
      if (!mounted) return;
      ref.read(someProvider.notifier).markFailed();
    }
  }

  @override
  Widget build(BuildContext context) => const SizedBox();
}

class LogFirstWidget extends ConsumerStatefulWidget {
  const LogFirstWidget({super.key});
  @override
  ConsumerState<LogFirstWidget> createState() => LogFirstStatePassing();
}

// A POSITIVE mounted check (`if (mounted) { ... }`) guards its own block.
@riverpod
class PositiveGuardNotifierPassing extends _$PositiveGuardNotifierPassing {
  @override
  AsyncValue<String> build() => const AsyncData('initial');

  // PASSING: the ref use is inside the block a positive check guards.
  Future<void> refReadInsidePositiveBlock() async {
    if (!ref.mounted) return;
    try {
      await someApi();
      if (!ref.mounted) return;
    } catch (e) {
      completer.completeError(e);
      if (ref.mounted) {
        ref.read(holdProvider.notifier).release();
      }
      rethrow;
    }
  }
}

class PositiveGuardStatePassing extends ConsumerState<LogFirstWidget> {
  // PASSING: a brace-less positive check guards its single statement.
  Future<void> braceLessPositiveCheck() async {
    if (!mounted) return;
    try {
      await someApi();
      if (!mounted) return;
    } catch (e) {
      if (mounted) ref.read(someProvider.notifier).markFailed();
    }
  }

  // PASSING: a compound positive check (`mounted && flag`) guards its block.
  Future<void> compoundPositiveCheck() async {
    if (!mounted) return;
    try {
      await someApi();
      if (!mounted) return;
    } catch (e) {
      if (mounted && _wantsRetry) {
        ref.read(someProvider.notifier).retry();
      }
    }
  }

  @override
  Widget build(BuildContext context) => const SizedBox();
}

Future<String> someApi() async => 'data';
