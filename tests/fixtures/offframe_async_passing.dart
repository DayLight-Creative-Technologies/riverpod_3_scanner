// Test fixture for the v1.9.0 off-frame async + ref check (passing cases).
//
// Every off-frame callback in this file is correctly guarded — the scanner
// must produce ZERO violations.
//
// Surfaces covered:
//   - Future.microtask (entry guard with ref.mounted)
//   - Future.microtask (entry guard with context.mounted)
//   - Future.microtask (entry guard with State.mounted)
//   - scheduleMicrotask (entry guard with ref.mounted)
//   - addPostFrameCallback() async { } (entry guard)
//   - Pre-capture-then-microtask (NO ref inside callback — canonical safe)
//   - Comment containing `ref.read()` text (must not false-positive)
//   - Compound mounted check `if (!context.mounted || flag)`
//
// Companion file: offframe_async_violations.dart

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

// ---------------------------------------------------------------------------
// Notifier surface — `ref.mounted` is the correct gate.
// ---------------------------------------------------------------------------

class GoodNotifier {
  late Ref ref;

  void doWork() {
    Future.microtask(() async {
      if (!ref.mounted) return; // entry guard
      final logger = ref.read(loggerProvider);
      logger.info('done');
    });
  }

  void scheduleWork() {
    scheduleMicrotask(() {
      if (!ref.mounted) return; // entry guard
      ref.read(notifierProvider.notifier).doStuff();
    });
  }
}

// ---------------------------------------------------------------------------
// ConsumerStatefulWidget.State surface — `mounted` (State.mounted) is the gate.
// ---------------------------------------------------------------------------

class GoodStateWidget extends ConsumerStatefulWidget {
  const GoodStateWidget({super.key});
  @override
  ConsumerState<GoodStateWidget> createState() => _GoodStateWidgetState();
}

class _GoodStateWidgetState extends ConsumerState<GoodStateWidget> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return; // State.mounted
      final logger = ref.read(loggerProvider);
      logger.info('initialized');
    });

    Future.microtask(() async {
      if (!mounted) return; // State.mounted
      ref.read(myProvider.notifier).load();
    });
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}

// ---------------------------------------------------------------------------
// ConsumerWidget surface — `context.mounted` is the correct gate.
// ---------------------------------------------------------------------------

class GoodConsumerWidget extends ConsumerWidget {
  const GoodConsumerWidget({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return GestureDetector(
      onTap: () {
        // The Future.microtask body is correctly guarded with context.mounted
        // (WidgetRef has no `mounted` getter; context.mounted is the gate).
        Future.microtask(() async {
          if (!context.mounted) return;
          ref.read(notifierProvider.notifier).fire();
        });
      },
      child: const SizedBox.shrink(),
    );
  }
}

// ---------------------------------------------------------------------------
// Pre-capture-then-microtask — the canonical safe pattern.
// No ref access happens inside the callback.
// ---------------------------------------------------------------------------

class GoodPreCaptureWidget extends ConsumerWidget {
  const GoodPreCaptureWidget({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Captures happen BEFORE the microtask is scheduled. The microtask body
    // calls a private method with the captured arguments. No new ref access.
    final logger = ref.read(loggerProvider);
    final notifier = ref.read(myProvider.notifier);

    Future.microtask(() async {
      await _doWork(logger, notifier);
    });

    return const SizedBox.shrink();
  }

  Future<void> _doWork(dynamic logger, dynamic notifier) async {
    await notifier.load();
    logger.info('done');
  }
}

// ---------------------------------------------------------------------------
// Comment containing `ref.read()` text — must not false-positive.
// ---------------------------------------------------------------------------

class GoodCommentNoise {
  late Ref ref;

  void run() {
    Future.microtask(() async {
      // Use ref.read() pattern with a mounted gate before the read so the
      // microtask is safe even if the host disposes mid-schedule.
      if (!ref.mounted) return;
      final logger = ref.read(loggerProvider);
      logger.info('safe');
    });
  }
}

// ---------------------------------------------------------------------------
// Compound mounted check shapes that the BROAD regex must accept.
// ---------------------------------------------------------------------------

class GoodCompoundGuards extends ConsumerWidget {
  const GoodCompoundGuards({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final hasShown = ValueNotifier(false);

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!context.mounted || hasShown.value) return; // compound `||`
      ref.read(myProvider.notifier).pulse();
    });

    Future.microtask(() async {
      if (mounted && context.mounted) return; // compound `&&` plus `(prefix.)mounted`
      ref.read(myProvider.notifier).pulse();
    });

    return const SizedBox.shrink();
  }

  bool get mounted => true; // unrelated; just exercising parser
}

// ---------------------------------------------------------------------------
// Stubs to satisfy parsing — these are not real providers.
// ---------------------------------------------------------------------------

final loggerProvider = Provider<dynamic>((ref) => null);
final notifierProvider = NotifierProvider<dynamic, dynamic>(() => null as dynamic);
final myProvider = NotifierProvider<dynamic, dynamic>(() => null as dynamic);
