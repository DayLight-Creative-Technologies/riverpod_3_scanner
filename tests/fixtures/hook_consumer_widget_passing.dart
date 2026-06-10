// Fixture: HookConsumerWidget passing patterns. Expected: 0 violations.
import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

// PASS 1: microtask body re-guards with context.mounted at entry —
// the canonical widget-side gate (WidgetRef has no `mounted` getter).
class GuardedMicrotaskHookWidget extends HookConsumerWidget {
  const GuardedMicrotaskHookWidget({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    useEffect(() {
      Future.microtask(() async {
        if (!context.mounted) return;
        final logger = ref.read(loggerProvider);
        logger.logInfo('started');
      });
      return null;
    }, const []);
    return const SizedBox();
  }
}

// PASS 2: parametered async handler guards with context.mounted after
// the await, before the ref operation.
class GuardedParamHandlerHookWidget extends HookConsumerWidget {
  const GuardedParamHandlerHookWidget({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return TextField(
      onChanged: (value) async {
        await Future<void>.delayed(const Duration(milliseconds: 100));
        if (!context.mounted) return;
        ref.read(loggerProvider).logInfo(value);
      },
    );
  }
}

// PASS 3: hook widget with no async surface at all.
class SyncHookWidget extends HookConsumerWidget {
  const SyncHookWidget({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final label = ref.watch(labelProvider);
    return Text(label);
  }
}
