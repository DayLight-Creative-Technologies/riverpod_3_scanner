// Test fixture: patterns that look similar but are NOT violations
// Every one of these must NOT be flagged — zero false positives is mission-critical.

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

// =========================================================================
// Case A: Bang getter + nullable field, but NO ref.read assignment anywhere.
// The field is set from a constructor / parameter / business logic.
// Must NOT be flagged — not a Riverpod caching pattern.
// =========================================================================
class PlainNullableField extends ConsumerStatefulWidget {
  const PlainNullableField({super.key});
  @override
  ConsumerState<PlainNullableField> createState() => _PlainNullableFieldState();
}

class _PlainNullableFieldState extends ConsumerState<PlainNullableField> {
  String? _cachedLabel;  // Assigned from user input, not ref.read
  String get cachedLabel => _cachedLabel!;

  void setLabel(String value) {
    _cachedLabel = value;  // ← NOT ref.read — user-supplied
  }

  @override
  Widget build(BuildContext context) => const SizedBox();

  Future<void> _save() async {
    await _persist(cachedLabel);
  }

  Future<void> _persist(String v) async {}
}

// =========================================================================
// Case B: ref.read exists in the class, but the field/getter pair is absent.
// Must NOT be flagged — no field caching pattern.
// =========================================================================
class JustInTimeRead extends ConsumerStatefulWidget {
  const JustInTimeRead({super.key});
  @override
  ConsumerState<JustInTimeRead> createState() => _JustInTimeReadState();
}

class _JustInTimeReadState extends ConsumerState<JustInTimeRead> {
  @override
  Widget build(BuildContext context) => const SizedBox();

  Future<void> _doStuff() async {
    if (!mounted) return;
    final svc = ref.read(someServiceProvider.notifier);
    await svc.perform();
  }
}

// =========================================================================
// Case C: Sync-only class (no async methods). Framework allows lazy getters.
// Must NOT be flagged.
// =========================================================================
class SyncOnlyWidget extends ConsumerStatefulWidget {
  const SyncOnlyWidget({super.key});
  @override
  ConsumerState<SyncOnlyWidget> createState() => _SyncOnlyWidgetState();
}

class _SyncOnlyWidgetState extends ConsumerState<SyncOnlyWidget> {
  SomeService? _service;
  SomeService get service => _service!;

  @override
  Widget build(BuildContext context) {
    _service ??= ref.read(someServiceProvider.notifier);
    service.finalize();  // sync usage only — no await
    return const SizedBox();
  }
}

// =========================================================================
// Case D: Getter uses bang but on a NON-matching field name.
// The `_service!` bang-return applies to a local variable, not a field.
// Must NOT be flagged.
// =========================================================================
class LocalVariableBang extends ConsumerStatefulWidget {
  const LocalVariableBang({super.key});
  @override
  ConsumerState<LocalVariableBang> createState() => _LocalVariableBangState();
}

class _LocalVariableBangState extends ConsumerState<LocalVariableBang> {
  @override
  Widget build(BuildContext context) => const SizedBox();

  Future<void> _doStuff() async {
    if (!mounted) return;
    SomeService? svc = ref.read(someServiceProvider.notifier);
    await svc!.perform();
  }
}

abstract class SomeService {
  Future<void> perform();
  void finalize();
}

final someServiceProvider = Provider<SomeService>((ref) => throw UnimplementedError());
