// Test fixture: field-caching violations using null-assertion getter pattern
// Pattern: nullable field + `Type get x => _x!;` + `_x ??= ref.read(...)` + async methods
// This is the exact pattern that evades the existing detector due to the trailing `!`
// Real-world instance: lib/presentation/features/game/views/game_gallery_view.dart

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

// =========================================================================
// Case 1: ConsumerState with nullable field + bang getter + ??= ref.read
// =========================================================================
class GalleryView extends ConsumerStatefulWidget {
  const GalleryView({super.key, required this.gameId});
  final int gameId;
  @override
  ConsumerState<GalleryView> createState() => _GalleryViewState();
}

class _GalleryViewState extends ConsumerState<GalleryView> {
  // VIOLATION: nullable field cached from ref.read, getter returns with `!`,
  // class has async methods — crashes when accessed across async gap.
  SomeService? _service;  // ← Signal 1: nullable field
  SomeService get service => _service!;  // ← Signal 2: bang getter

  @override
  Widget build(BuildContext context) {
    _service ??= ref.read(someServiceProvider.notifier);  // ← Signal 3: ref.read backed
    return const SizedBox();
  }

  // ← Signal 4: async method uses the cached reference
  Future<void> _doStuff() async {
    await service.perform();
    service.finalize();
  }
}

// =========================================================================
// Case 2: Direct `=` assignment (not `??=`) still counts
// =========================================================================
class DirectAssignView extends ConsumerStatefulWidget {
  const DirectAssignView({super.key});
  @override
  ConsumerState<DirectAssignView> createState() => _DirectAssignViewState();
}

class _DirectAssignViewState extends ConsumerState<DirectAssignView> {
  CacheManager? _cache;  // nullable field
  CacheManager get cache => _cache!;  // bang getter

  @override
  void initState() {
    super.initState();
    _cache = ref.read(cacheManagerProvider);  // = ref.read(...) in lifecycle
  }

  @override
  Widget build(BuildContext context) => const SizedBox();

  Future<void> _load() async {
    await cache.prime();
  }
}

abstract class SomeService {
  Future<void> perform();
  void finalize();
}

abstract class CacheManager {
  Future<void> prime();
}

final someServiceProvider = Provider<SomeService>((ref) => throw UnimplementedError());
final cacheManagerProvider = Provider<CacheManager>((ref) => throw UnimplementedError());
