// Test fixture: Ref / WidgetRef into plain class — VIOLATION patterns.
// Expected scanner result: 5 violations.
//
// Each plain (non-Riverpod) class either stores or receives `ref` — the
// on-ramp to UnmountedRefException once the owning provider/widget disposes.

import 'package:flutter_riverpod/flutter_riverpod.dart';

// V1 — plain class stores Ref as a field. (REF_STORED_AS_FIELD)
class RefFieldHolder {
  RefFieldHolder(this._ref);
  final Ref _ref;
}

// V2 — plain class stores WidgetRef as a field. (REF_STORED_AS_FIELD)
class WidgetRefFieldHolder {
  WidgetRefFieldHolder(this._wref);
  final WidgetRef _wref;
}

// V3 — plain class constructor takes Ref directly. (REF_PASSED_TO_PLAIN_CLASS)
class RefCtorPlain {
  RefCtorPlain(Ref ref);
}

// V4 — plain class named constructor takes Ref. (REF_PASSED_TO_PLAIN_CLASS)
class NamedRefCtor {
  NamedRefCtor.fromRef(Ref ref);
}

// V5 — plain class constructor takes WidgetRef as a named parameter.
//      (REF_PASSED_TO_PLAIN_CLASS)
class WidgetRefCtorPlain {
  WidgetRefCtorPlain({required WidgetRef ref});
}
