// Test fixture: Ref / WidgetRef into plain class — PASSING patterns.
// Expected scanner result: 0 violations.
//
// Every pattern here is an idiomatic, framework-sanctioned use of `ref`. The
// `check_ref_into_plain_class` checker must NOT flag any of them.

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

// P1 — @riverpod provider function. `(Ref ref)` is the mandatory provider
// signature: a top-level function, never a plain-class constructor.
@riverpod
String greeting(Ref ref) => 'hi';

// P2 — ConsumerWidget. `build` and build-helper methods receive WidgetRef from
// the framework; they are methods, never constructors. A ConsumerWidget also
// cannot decompose `build` without passing `ref` — it has no instance ref.
class GreetingView extends ConsumerWidget {
  const GreetingView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) => _section(context, ref);

  Widget _section(BuildContext context, WidgetRef ref) {
    final value = ref.watch(greetingProvider);
    return Text(value);
  }
}

// P3 — Riverpod notifier. Excluded: extends _$.
class CounterNotifier extends _$CounterNotifier {
  @override
  int build() => 0;
}

// P4 — plain class whose constructor takes a *callback* that itself receives a
// Ref. The parameter's declared type is `void Function(...)`, not `Ref`.
class CallbackHolder {
  CallbackHolder(this.onResolve);
  final void Function(Ref ref) onResolve;
}

// P5 — plain class with a clean constructor: specific dependencies, never ref.
class TokenCache {
  TokenCache({required this.service, required this.logger});
  final Object service;
  final Object logger;
}

// P6 — doc comment mentioning the forbidden shape as a counter-example. The
// class body is comment-stripped before scanning, so the example text — even
// though it ends in `;` — is never mistaken for a real declaration.
class DocExample {
  /// Never write a constructor like `DocExample(Ref ref);` — inject deps.
  DocExample(this.service);
  final Object service;
}
