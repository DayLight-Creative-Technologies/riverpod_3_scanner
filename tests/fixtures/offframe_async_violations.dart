// Test fixture for the v1.9.0 off-frame async + ref check (violation cases).
//
// Every off-frame callback in this file is unguarded — the scanner must
// flag a violation for each one.
//
// Surfaces covered:
//   - Future.microtask — direct ref.read inside, no entry guard (9CJ shape)
//   - scheduleMicrotask — direct ref.read inside, no entry guard
//   - addPostFrameCallback() async { } — async-bodied form, no guard
//   - Mounted check AFTER first ref usage — first-position bug class
//
// Companion file: offframe_async_passing.dart

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

// ---------------------------------------------------------------------------
// VIOLATION 1: Future.microtask in a State without entry guard (9CJ shape).
// ---------------------------------------------------------------------------

class BadStateWidget extends ConsumerStatefulWidget {
  const BadStateWidget({super.key});
  @override
  ConsumerState<BadStateWidget> createState() => _BadStateWidgetState();
}

class _BadStateWidgetState extends ConsumerState<BadStateWidget> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() async {
      // ❌ No mounted check before ref.read — Sentry 9CJ shape.
      final logger = ref.read(loggerProvider);
      logger.info('boom');
    });
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}

// ---------------------------------------------------------------------------
// VIOLATION 2: Mounted check AFTER first ref usage — first-position bug class.
// ---------------------------------------------------------------------------

class BadGuardAfterRef extends ConsumerStatefulWidget {
  const BadGuardAfterRef({super.key});
  @override
  ConsumerState<BadGuardAfterRef> createState() => _BadGuardAfterRefState();
}

class _BadGuardAfterRefState extends ConsumerState<BadGuardAfterRef> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      // ❌ ref.read at line 1 of body — not protected by the
      // `if (mounted)` guard at line 3 of body.
      ref.read(myProvider.notifier).pulse();

      if (mounted) {
        ref.read(myProvider.notifier).pulse();
      }
    });
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}

// ---------------------------------------------------------------------------
// VIOLATION 3: scheduleMicrotask without entry guard, in a notifier class.
// ---------------------------------------------------------------------------

class BadScheduleMicrotask extends _$BadScheduleMicrotask {
  @override
  String build() => '';

  void run() {
    scheduleMicrotask(() {
      // ❌ No mounted check before ref.read.
      ref.read(notifierProvider.notifier).fire();
    });
  }
}

abstract class _$BadScheduleMicrotask {
  Ref get ref;
  String state = '';
}

// ---------------------------------------------------------------------------
// VIOLATION 4: addPostFrameCallback with `async {}` body, no guard.
// ---------------------------------------------------------------------------

class BadAsyncPostFrame extends ConsumerStatefulWidget {
  const BadAsyncPostFrame({super.key});
  @override
  ConsumerState<BadAsyncPostFrame> createState() => _BadAsyncPostFrameState();
}

class _BadAsyncPostFrameState extends ConsumerState<BadAsyncPostFrame> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      // ❌ async body version — no mounted check before ref.read.
      final notifier = ref.read(myProvider.notifier);
      await notifier.load();
    });
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}

// ---------------------------------------------------------------------------
// Stubs.
// ---------------------------------------------------------------------------

final loggerProvider = Provider<dynamic>((ref) => null);
final notifierProvider = NotifierProvider<dynamic, dynamic>(() => null as dynamic);
final myProvider = NotifierProvider<dynamic, dynamic>(() => null as dynamic);
