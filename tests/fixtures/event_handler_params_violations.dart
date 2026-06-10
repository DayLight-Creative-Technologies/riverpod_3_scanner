// Fixture: parametered async event handlers in a ConsumerWidget.
// Expected: 2 violations, both deferred_callback_unsafe_ref.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class ParamHandlerWidget extends ConsumerWidget {
  const ParamHandlerWidget({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Column(
      children: [
        // VIOLATION 1: one-parameter handler, ref after await, no guard.
        TextField(
          onChanged: (value) async {
            final result = await saveValue(value);
            ref.read(loggerProvider).logInfo('saved: $result');
          },
        ),
        // VIOLATION 2: zero-parameter handler (pre-1.12.0 shape) — must
        // still be detected after the pattern generalization.
        GestureDetector(
          onTap: () async {
            await refreshAll();
            ref.read(loggerProvider).logInfo('refreshed');
          },
          child: const Icon(Icons.refresh),
        ),
      ],
    );
  }
}
