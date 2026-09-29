// Test fixture: LOG-FIRST catch blocks where a ref / state use runs BEFORE the guard.
// Log-first (log through a logger captured while mounted, THEN guard) puts a
// multi-line log call ahead of the guard, so the guard sits many lines into the
// catch body. VIOLATION 6 must judge the WHOLE catch body — the leftmost ref/state
// use versus the leftmost guard — not a fixed look-ahead window.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'catch_block_log_first_violations.g.dart';

@riverpod
class LogFirstNotifierViolations extends _$LogFirstNotifierViolations {
  @override
  AsyncValue<String> build() => const AsyncData('initial');

  // VIOLATION: multi-line captured-logger log, then an unguarded state write.
  Future<void> multiLineLogThenState() async {
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
      state = AsyncError(e, st);
    }
  }

  // VIOLATION: the logger is read from ref INSIDE the catch — a ref use — and
  // the guard only comes after it.
  Future<void> refReadLoggerBeforeGuard() async {
    if (!ref.mounted) return;
    try {
      await someApi();
      if (!ref.mounted) return;
    } catch (e, st) {
      ref.read(loggerProvider).logError(
        'Failed',
        error: e,
        stackTrace: st,
      );
      if (!ref.mounted) return;
    }
  }

  // VIOLATION: the guard exists but comes AFTER the first ref use.
  Future<void> guardAfterRefUse() async {
    if (!ref.mounted) return;
    final logger = ref.read(loggerProvider);
    try {
      await someApi();
      if (!ref.mounted) return;
    } catch (e, st) {
      logger.logError('Failed', error: e, stackTrace: st);
      ref.invalidateSelf();
      if (!ref.mounted) return;
    }
  }

  // VIOLATION: a string INTERPOLATION is code — the ref.read inside `${...}`
  // runs before the guard.
  Future<void> interpolatedRefRead() async {
    if (!ref.mounted) return;
    final logger = ref.read(loggerProvider);
    try {
      await someApi();
      if (!ref.mounted) return;
    } catch (e, st) {
      logger.logError('Failed for ${ref.read(idProvider)}', error: e, stackTrace: st);
      if (!ref.mounted) return;
    }
  }
}

class LogFirstStateViolations extends ConsumerState<LogFirstWidget> {
  // VIOLATION: the two probe shapes from the log-first rule — multi-line log,
  // then an unguarded ref.read.
  Future<void> multiLineLogThenRefRead() async {
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
      ref.read(someProvider.notifier).markFailed();
    }
  }

  // VIOLATION: single-line log, then an unguarded ref.read.
  Future<void> singleLineLogThenRefRead() async {
    if (!mounted) return;
    final logger = ref.read(loggerProvider);
    try {
      await someApi();
      if (!mounted) return;
    } catch (e, st) {
      logger.logError('Probe failed', error: e, stackTrace: st);
      ref.read(someProvider.notifier).markFailed();
    }
  }

  @override
  Widget build(BuildContext context) => const SizedBox();
}

class LogFirstWidget extends ConsumerStatefulWidget {
  const LogFirstWidget({super.key});
  @override
  ConsumerState<LogFirstWidget> createState() => LogFirstStateViolations();
}

// A POSITIVE mounted check (`if (mounted) { ... }`) guards only its own block —
// it is not an early-return guard for what follows it.
@riverpod
class PositiveGuardNotifierViolations extends _$PositiveGuardNotifierViolations {
  @override
  AsyncValue<String> build() => const AsyncData('initial');

  // VIOLATION: the use is in the `else` branch, which the positive check does
  // not guard.
  Future<void> refReadInElseBranch() async {
    if (!ref.mounted) return;
    try {
      await someApi();
      if (!ref.mounted) return;
    } catch (e, st) {
      if (ref.mounted) {
        state = AsyncError(e, st);
      } else {
        ref.read(loggerProvider).logError('Failed', error: e, stackTrace: st);
      }
    }
  }
}

class PositiveGuardStateViolations extends ConsumerState<LogFirstWidget> {
  // VIOLATION: `if (mounted) { setState }` guards the setState only; the ref.read
  // after the block runs with no guard before it.
  Future<void> refReadAfterPositiveBlock() async {
    if (!mounted) return;
    try {
      await someApi();
      if (!mounted) return;
    } catch (e) {
      if (mounted) {
        setState(() => _failed = true);
      }

      final logger = ref.read(loggerProvider);
      logger.logError('Failed', error: e);
    }
  }

  @override
  Widget build(BuildContext context) => const SizedBox();
}

Future<String> someApi() async => 'data';
