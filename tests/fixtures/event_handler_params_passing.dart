// Fixture: parametered async event handlers — passing patterns.
// Expected: 0 violations.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class GuardedParamHandlerWidget extends ConsumerWidget {
  const GuardedParamHandlerWidget({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Column(
      children: [
        // PASS 1: guard after the await, before the ref operation.
        TextField(
          onChanged: (value) async {
            await saveValue(value);
            if (!context.mounted) return;
            ref.read(loggerProvider).logInfo('saved');
          },
        ),
        // PASS 2: ref read BEFORE the await only — nothing to protect after.
        TextField(
          onSubmitted: (value) async {
            final logger = ref.read(loggerProvider);
            await saveValue(value);
            logger.logInfo('submitted');
          },
        ),
        // PASS 3: synchronous parametered handler — not an async surface.
        TextField(
          onChanged: (value) {
            ref.read(draftProvider.notifier).update(value);
          },
        ),
      ],
    );
  }
}
