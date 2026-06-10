// Fixture: HookConsumerWidget violations (scanned since 1.12.0).
// Expected: 2 violations, both deferred_callback_unsafe_ref.
import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

// VIOLATION 1: Future.microtask inside a hook body with an unguarded
// ref.read — the exact Sentry SOCIALSCOREKEEPER-FLUTTER-9CJ shape.
class MicrotaskHookWidget extends HookConsumerWidget {
  const MicrotaskHookWidget({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    useEffect(() {
      Future.microtask(() async {
        final logger = ref.read(loggerProvider);
        logger.logInfo('started');
      });
      return null;
    }, const []);
    return const SizedBox();
  }
}

// VIOLATION 2: parametered async event handler using ref after await
// without a mounted guard (zero-parameter-only matching missed this
// shape before 1.12.0).
class ParamHandlerHookWidget extends HookConsumerWidget {
  const ParamHandlerHookWidget({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return TextField(
      onChanged: (value) async {
        await Future<void>.delayed(const Duration(milliseconds: 100));
        ref.read(loggerProvider).logInfo(value);
      },
    );
  }
}
