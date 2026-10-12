"""A mounted guard on a Ref the method CAPTURED is a guard (SocialScoreKeeper gap #1073).

Inside a Notifier `ref` is the element's CURRENT Ref and a rebuild installs a new
one (riverpod 3.4.3 element.dart:616-618), so work a build starts reads the Ref
that build captured: `final build = ref;` as the first statement of `build()`,
`Ref build` as a parameter of a method the build starts. `Ref.mounted` is
`!_element._disposed && identical(_element.ref, this)` (ref.dart:112), so where
`if (!build.mounted) return;` passes, the element's current Ref IS `build` and
`ref.mounted` is true too. The scanner demanded the literal `if (!ref.mounted)
return;` right after it anyway.

Recognised: a `Ref`-typed parameter (any name) and a local initialised exactly
from `ref`, in every guard shape `ref.mounted` is accepted in. Not recognised: a
local initialised from anything else, a non-Ref parameter, a field, a name
rebound in the method, another method's capture, and a guard separated from the
access by another await.

A captured Ref's USE is a ref use too (gap #1076): `build.read(p)`,
`build.watch(p)`, `build.listen(…)`, `build.onDispose(…)` throw on a disposed Ref
exactly as `ref.read(p)` does. It is guarded by the captured Ref's own
`build.mounted` and by nothing else — `ref.mounted` says nothing about a Ref a
rebuild has replaced.

A sync helper is judged by its own signature, wherever it is declared (gap
#1075): one declared right after an `async` method is not async.
"""

import pytest

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner
from riverpod_3_scanner.utils import (
    captured_ref_names,
    captured_ref_names_at,
    captured_ref_use_pattern,
    captured_ref_uses,
    class_member_spans,
    first_unguarded_captured_use,
    header_param_text,
    mounted_receivers,
    params_of_signature,
    signature_declares_async,
)

AFTER_AWAIT = ViolationType.MISSING_MOUNTED_AFTER_AWAIT
ENTRY = ViolationType.REF_READ_BEFORE_MOUNTED
IN_CATCH = ViolationType.MISSING_MOUNTED_IN_CATCH
IN_FINALLY = ViolationType.MISSING_MOUNTED_IN_FINALLY
CALLBACK = ViolationType.DEFERRED_CALLBACK_UNSAFE_REF
SYNC = ViolationType.SYNC_METHOD_WITHOUT_MOUNTED_CHECK
ASYNC_STAR = ViolationType.ASYNC_STAR_REF_BEFORE_MOUNTED


def _notifier(members: str) -> str:
    return f"""\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@riverpod
class Probe extends _$Probe {{
  @override
  int build() => 0;

{members}
}}
"""


def _types(tmp_path, source):
    # scan_directory runs the cross-file passes VIOLATION 10 needs (the call graph).
    (tmp_path / "probe.dart").write_text(source)
    return sorted(v.violation_type.value for v in RiverpodScanner().scan_directory(tmp_path))


def _clean(tmp_path, members):
    assert _types(tmp_path, _notifier(members)) == []


def _flagged(tmp_path, members, *expected):
    assert _types(tmp_path, _notifier(members)) == sorted(t.value for t in expected)


# ---------------------------------------------------------------------------
# Accepted: the early-return guard after an await (VIOLATIONS 4 and 5)
# ---------------------------------------------------------------------------

class TestEarlyReturnGuard:
    def test_a_local_initialised_from_ref_guards_the_write_after_an_await(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""")

    def test_a_ref_parameter_guards_the_write_after_an_await(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""")

    @pytest.mark.parametrize("parameter", [
        "Ref owner", "final Ref owner", "required Ref owner", "Ref<int> owner",
    ])
    def test_a_ref_parameter_may_have_any_name_and_modifier(self, tmp_path, parameter):
        signature = f"{{{parameter}}}" if parameter.startswith("required") else parameter
        _clean(tmp_path, f"""\
  Future<void> load({signature}) async {{
    if (!owner.mounted) return;
    await work();
    if (!owner.mounted) return;
    state = 1;
  }}
""")

    @pytest.mark.parametrize("declaration", [
        "final build = ref;", "var build = ref;", "final Ref build = ref;", "Ref build = ref;",
    ])
    def test_every_local_declaration_of_ref_is_a_capture(self, tmp_path, declaration):
        _clean(tmp_path, f"""\
  Future<void> reload() async {{
    {declaration}
    await work();
    if (!build.mounted) return;
    state = 1;
  }}
""")

    def test_the_guard_may_be_a_block_that_exits(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    await work();
    if (!build.mounted) {
      return;
    }
    state = 1;
  }
""")

    def test_the_build_method_captures_its_own_ref(self, tmp_path):
        source = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@riverpod
class Probe extends _$Probe {
  @override
  Future<int> build() async {
    final build = ref;
    final seed = await load();
    if (!build.mounted) return 0;
    state = AsyncData(seed);
    return seed;
  }
}
"""
        assert _types(tmp_path, source) == []

    def test_ref_mounted_is_still_accepted_beside_a_capture(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    await work();
    if (!ref.mounted) return;
    state = 1;
    await other();
    if (!build.mounted) return;
    state = 2;
  }
""")

    def test_a_guard_per_await_is_enough_when_each_names_a_capture(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    await first();
    if (!build.mounted) return;
    state = 1;
    await second();
    if (!build.mounted) return;
    state = 2;
  }
""")


# ---------------------------------------------------------------------------
# Accepted: catch / finally (VIOLATIONS 6 and 6b), early return and positive block
# ---------------------------------------------------------------------------

class TestCatchAndFinally:
    def test_the_early_return_guard_in_a_catch(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    try {
      await work();
      if (!build.mounted) return;
      state = 1;
    } catch (e) {
      if (!build.mounted) return;
      state = -1;
    }
  }
""")

    def test_the_positive_block_in_a_catch(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      if (build.mounted) {
        state = -1;
      }
    }
  }
""")

    def test_the_positive_block_with_a_conjunct(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      if (build.mounted && e is StateError) state = -1;
    }
  }
""")

    def test_the_positive_check_in_a_finally(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } finally {
      if (build.mounted) state = 0;
    }
  }
""")

    def test_a_positive_block_protects_only_its_own_region(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      if (build.mounted) {
        state = -1;
      }
      state = -2;
    }
  }
""", IN_CATCH)


# ---------------------------------------------------------------------------
# Accepted: a closure a Notifier hands to a widget (VIOLATION 15b)
# ---------------------------------------------------------------------------

class TestUiCallbacks:
    def test_the_early_return_guard_on_the_methods_capture(self, tmp_path):
        _clean(tmp_path, """\
  Widget _actions(BuildContext dialogContext) {
    final build = ref;
    return TextButton(
      onPressed: () {
        if (!build.mounted) return;
        state = 1;
      },
      child: const Text('OK'),
    );
  }
""")

    def test_the_positive_block_on_a_ref_parameter(self, tmp_path):
        _clean(tmp_path, """\
  Widget _actions(BuildContext dialogContext, Ref build) {
    return TextButton(
      onPressed: () {
        if (build.mounted) {
          state = 1;
        }
      },
      child: const Text('OK'),
    );
  }
""")

    def test_another_methods_capture_is_not_visible(self, tmp_path):
        _flagged(tmp_path, """\
  void _capture() {
    final build = ref;
  }

  Widget _actions(BuildContext dialogContext) {
    return TextButton(
      onPressed: () {
        if (!build.mounted) return;
        state = 1;
      },
      child: const Text('OK'),
    );
  }
""", CALLBACK)

    def test_a_guard_on_the_dialog_context_is_not_a_notifier_guard(self, tmp_path):
        _flagged(tmp_path, """\
  Widget _actions(BuildContext dialogContext) {
    final build = ref;
    return TextButton(
      onPressed: () {
        if (!dialogContext.mounted) return;
        state = 1;
      },
      child: const Text('OK'),
    );
  }
""", CALLBACK)


# ---------------------------------------------------------------------------
# Accepted: sync helpers and the call-graph danger zone (VIOLATION 10)
# ---------------------------------------------------------------------------

SYNC_HELPER_CALLED_AFTER_AWAIT = """\
  Future<void> run() async {
    await work();
    _emit();
  }

  void _emit(%s) {
%s
    state = 1;
  }
"""


class TestSyncHelpers:
    def test_the_helper_with_no_guard_is_flagged(self, tmp_path):
        _flagged(tmp_path, SYNC_HELPER_CALLED_AFTER_AWAIT % ("", ""), SYNC)

    def test_a_helper_declared_before_the_async_method_is_flagged(self, tmp_path):
        _flagged(tmp_path, """\
  void _emit() {
    state = 1;
  }

  Future<void> run() async {
    await work();
    _emit();
  }
""", SYNC)

    def test_a_helper_declared_right_after_an_async_method_is_checked(self, tmp_path):
        # The helper starts a few characters after `run`'s `async {` — the old
        # 50-character window took it for async and never judged it.
        _flagged(tmp_path, """\
  Future<void> run() async { await work(); _emit(); }
  void _emit() { state = 1; }
""", SYNC)

    def test_a_ref_read_helper_declared_after_an_async_method_is_checked(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> run() async {
    await work();
    _emit();
  }
  void _emit() {
    ref.read(sourceProvider);
  }
""", SYNC)

    def test_a_guarded_helper_declared_after_an_async_method_is_clean(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> run() async {
    await work();
    _emit();
  }
  void _emit() {
    if (!ref.mounted) return;
    state = 1;
  }
""")

    def test_every_sync_helper_after_an_async_method_is_checked(self, tmp_path):
        source = _notifier("""\
  Future<void> run() async {
    await work();
    _first();
    _second();
  }
  void _first() {
    if (!ref.mounted) return;
    state = 1;
  }
  void _second() {
    state = 2;
  }
""")
        (tmp_path / "probe.dart").write_text(source)
        found = RiverpodScanner().scan_directory(tmp_path)
        assert [v.context.split("(")[0] for v in found] == ["Method _second"]

    def test_an_async_method_is_still_not_a_sync_helper(self, tmp_path):
        # A `void` return type is legal on an async method; V10 judges sync ones only.
        _clean(tmp_path, """\
  Future<void> run() async {
    await work();
    _emit();
  }

  void _emit() async {
    state = 1;
  }
""")

    def test_a_ref_parameter_guard_at_the_helpers_entry(self, tmp_path):
        source = _notifier("""\
  Future<void> run() async {
    final build = ref;
    await work();
    _emit(build);
  }

  void _emit(Ref build) {
    if (!build.mounted) return;
    state = 1;
  }
""")
        assert _types(tmp_path, source) == []

    def test_a_local_capture_guard_at_the_helpers_entry(self, tmp_path):
        source = _notifier("""\
  Future<void> run() async {
    await work();
    _emit();
  }

  void _emit() {
    final build = ref;
    if (!build.mounted) return;
    state = 1;
  }
""")
        assert _types(tmp_path, source) == []

    def test_a_guard_on_a_non_ref_parameter_does_not_guard_the_helper(self, tmp_path):
        _flagged(
            tmp_path,
            SYNC_HELPER_CALLED_AFTER_AWAIT % ("BuildContext build", "    if (!build.mounted) return;"),
            SYNC,
        )

    def test_the_guard_ends_the_danger_zone_of_the_await_before_it(self, tmp_path):
        # `_helper` runs after a build guard: it is not "called from an async
        # gap" in the call graph, so its own entry guard is not demanded.
        source = _notifier("""\
  Future<void> run(Ref build) async {
    if (!build.mounted) return;
    await work();
    if (!build.mounted) return;
    _helper();
  }

  void _helper() {
    state = 1;
  }
""")
        assert _types(tmp_path, source) == []

    def test_a_guard_on_a_non_ref_does_not_end_the_danger_zone(self, tmp_path):
        source = _notifier("""\
  Future<void> run(BuildContext build) async {
    await work();
    if (!build.mounted) return;
    _helper();
  }

  void _helper() {
    state = 1;
  }
""")
        assert _types(tmp_path, source) == [SYNC.value]


class TestMethodDatabase:
    """Pass 1.5 records, per method, whether a mounted guard precedes its first `ref.read`."""

    @pytest.mark.parametrize("signature, prologue, recorded", [
        ("Ref build", "if (!build.mounted) return;", True),
        ("", "final build = ref;\n    if (!build.mounted) return;", True),
        ("", "if (!ref.mounted) return;", True),
        ("BuildContext build", "if (!build.mounted) return;", False),
        ("", "final build = other;\n    if (!build.mounted) return;", False),
        ("Ref build", "", False),
    ])
    def test_has_mounted_check_follows_the_guard_before_the_first_read(
        self, tmp_path, signature, prologue, recorded
    ):
        (tmp_path / "probe.dart").write_text(_notifier(f"""\
  void touch({signature}) {{
    {prologue}
    ref.read(sourceProvider);
  }}
"""))
        scanner = RiverpodScanner()
        scanner.scan_directory(tmp_path)
        (metadata,) = [m for (_, _, name), m in scanner._ctx.all_methods.items() if name == "touch"]
        assert metadata.has_mounted_check is recorded


# ---------------------------------------------------------------------------
# Accepted: an async* function provider (VIOLATION 14)
# ---------------------------------------------------------------------------

class TestAsyncStarFunctionProvider:
    SOURCE = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@riverpod
Stream<int> feed(Ref ref) async* {
%s
  final value = ref.read(sourceProvider);
  yield value;
}
"""

    def test_an_unguarded_first_read_is_flagged(self, tmp_path):
        assert _types(tmp_path, self.SOURCE % "") == [ASYNC_STAR.value]

    def test_a_guard_on_a_capture_before_the_first_read(self, tmp_path):
        assert _types(tmp_path, self.SOURCE % "  final build = ref;\n  if (!build.mounted) return;") == []

    def test_a_guard_on_a_local_from_something_else_is_not_one(self, tmp_path):
        source = self.SOURCE % "  final build = other;\n  if (!build.mounted) return;"
        assert _types(tmp_path, source) == [ASYNC_STAR.value]


# ---------------------------------------------------------------------------
# Still flagged
# ---------------------------------------------------------------------------

class TestStillFlagged:
    def test_no_guard_at_all(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    final build = ref;
    await work();
    state = 1;
  }
""", AFTER_AWAIT)

    def test_a_guard_on_a_parameter_that_is_not_a_ref(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(BuildContext build) async {
    if (!ref.mounted) return;
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""", AFTER_AWAIT)

    @pytest.mark.parametrize("parameter", ["WidgetRef build", "Ref? build", "Object build", "dynamic build"])
    def test_a_parameter_of_another_type_is_not_a_capture(self, tmp_path, parameter):
        _flagged(tmp_path, f"""\
  Future<void> reload({parameter}) async {{
    if (!ref.mounted) return;
    await work();
    if (!build.mounted) return;
    state = 1;
  }}
""", AFTER_AWAIT)

    @pytest.mark.parametrize("initialiser", [
        "other", "ref.read(pProvider)", "this.ref", "ref.notifier", "null", "_stored",
    ])
    def test_a_local_initialised_from_anything_but_ref(self, tmp_path, initialiser):
        _flagged(tmp_path, f"""\
  Future<void> reload() async {{
    if (!ref.mounted) return;
    final build = {initialiser};
    await work();
    if (!build.mounted) return;
    state = 1;
  }}
""", AFTER_AWAIT)

    def test_a_guard_followed_by_another_await_before_the_access(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    final build = ref;
    await first();
    if (!build.mounted) return;
    await second();
    state = 1;
  }
""", AFTER_AWAIT)

    def test_a_guard_on_a_field(self, tmp_path):
        _flagged(tmp_path, """\
  late Ref _build;

  Future<void> reload() async {
    if (!ref.mounted) return;
    await work();
    if (!_build.mounted) return;
    state = 1;
  }
""", AFTER_AWAIT)

    def test_a_field_assigned_from_ref_is_still_a_field(self, tmp_path):
        _flagged(tmp_path, """\
  late Ref _build;

  Future<void> reload() async {
    if (!ref.mounted) return;
    _build = ref;
    await work();
    if (!_build.mounted) return;
    state = 1;
  }
""", AFTER_AWAIT)

    def test_another_methods_capture_is_not_visible(self, tmp_path):
        _flagged(tmp_path, """\
  void capture() {
    final build = ref;
  }

  Future<void> reload() async {
    if (!ref.mounted) return;
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""", AFTER_AWAIT)

    def test_a_capture_reassigned_to_something_else(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref other) async {
    if (!ref.mounted) return;
    var build = ref;
    build = other;
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""", AFTER_AWAIT)

    def test_a_ref_parameter_reassigned(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref build, Ref other) async {
    if (!ref.mounted) return;
    build = other;
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""", AFTER_AWAIT)

    def test_a_name_that_a_nested_closure_takes_as_its_own_parameter(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    final build = ref;
    await work();
    items.forEach((build) {
      if (!build.mounted) return;
    });
    if (!build.mounted) return;
    state = 1;
  }
""", AFTER_AWAIT)

    def test_a_guard_that_does_not_exit(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    final build = ref;
    await work();
    if (!build.mounted) {
      log('gone');
    }
    state = 1;
  }
""", AFTER_AWAIT)

    def test_a_catch_with_a_guard_on_a_non_ref(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(BuildContext build) async {
    if (!ref.mounted) return;
    try {
      await work();
      if (!ref.mounted) return;
    } catch (e) {
      if (!build.mounted) return;
      state = -1;
    }
  }
""", IN_CATCH)

    def test_a_finally_with_a_positive_check_on_a_local_from_something_else(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    final build = other;
    if (!ref.mounted) return;
    try {
      await work();
      if (!ref.mounted) return;
    } finally {
      if (build.mounted) state = 0;
    }
  }
""", IN_FINALLY)

    def test_an_entry_use_before_the_capture_guard(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref build) async {
    state = 0;
    if (!build.mounted) return;
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""", ENTRY)

    def test_a_guard_whose_receiver_only_ends_like_a_capture(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    final build = ref;
    await work();
    if (!mybuild.mounted) return;
    state = 1;
  }
""", AFTER_AWAIT)


# ---------------------------------------------------------------------------
# The helpers themselves
# ---------------------------------------------------------------------------

class TestCapturedRefNames:
    def test_a_ref_parameter_and_a_local_from_ref(self):
        assert captured_ref_names("Ref a, int n", "final b = ref;") == {"a", "b"}

    def test_ref_itself_is_never_listed(self):
        assert captured_ref_names("Ref ref", "") == frozenset()

    def test_a_declaration_in_a_comment_or_a_string_is_not_one(self):
        body = "// final b = ref;\nfinal s = 'final c = ref;';"
        assert captured_ref_names("", body) == frozenset()

    def test_every_declaration_of_a_name_must_be_a_capture(self):
        both = "final b = ref;\nvoid f() { final b = ref; }"
        assert captured_ref_names("", both) == {"b"}
        mixed = "final b = ref;\nvoid f() { final b = other; }"
        assert captured_ref_names("", mixed) == frozenset()

    def test_a_compound_assignment_rebinds(self):
        assert captured_ref_names("", "var b = ref;\nb ??= other;") == frozenset()

    def test_a_comparison_or_a_field_write_does_not_rebind(self):
        body = "final b = ref;\nif (b == other) {}\nholder.b = other;"
        assert captured_ref_names("", body) == {"b"}

    def test_a_parameter_of_another_type_wins_over_a_nested_local(self):
        assert captured_ref_names("BuildContext b", "final b = ref;") == frozenset()

    def test_mounted_receivers_lists_ref_first_then_the_captures_sorted(self):
        assert mounted_receivers(()) == "(?:ref)"
        assert mounted_receivers({"zeta", "alpha", "ref"}) == "(?:ref|alpha|zeta)"


class TestSignatureHelpers:
    def test_params_of_signature_finds_the_list_of_the_named_method(self):
        assert params_of_signature("Future<void> load(Ref build, {int n = 1}) async {", "load") == \
            "Ref build, {int n = 1}"

    def test_params_of_signature_ignores_a_longer_name(self):
        assert params_of_signature("Future<void> preload(Ref a) async {", "load") == ""

    def test_header_param_text_strips_the_async_modifier(self):
        assert header_param_text("\n  Future<void> load(Ref build) async ") == "Ref build"
        assert header_param_text("\n  Stream<int> feed(Ref build) async* ") == "Ref build"

    def test_header_param_text_of_a_member_without_parameters(self):
        assert header_param_text("\n  int get size ") == ""

    def test_header_param_text_takes_the_last_list_not_an_annotations(self):
        assert header_param_text("\n  @Deprecated('x')\n  void run(Ref build) ") == "Ref build"


class TestClassMemberSpans:
    CLASS = (
        "class A extends _$A {\n"
        "  int x = 0;\n"
        "  void one(Ref a) {\n    if (a.mounted) { go(); }\n  }\n"
        "  final m = {1: 2};\n"
        "  void two({required Ref b}) {\n    run();\n  }\n"
        "}"
    )

    def test_each_brace_bodied_member_has_its_own_span(self):
        spans = class_member_spans(self.CLASS)
        assert [self.CLASS[s:b].strip() for s, b, _ in spans] == [
            "void one(Ref a)", "final m =", "void two({required Ref b})",
        ]

    def test_a_brace_in_a_parameter_list_is_not_a_body(self):
        assert len(class_member_spans(self.CLASS)) == 3

    def test_captures_resolve_against_the_containing_member_only(self):
        at_one = self.CLASS.index("go();")
        at_two = self.CLASS.index("run();")
        assert captured_ref_names_at(self.CLASS, at_one) == {"a"}
        assert captured_ref_names_at(self.CLASS, at_two) == {"b"}
        assert captured_ref_names_at(self.CLASS, self.CLASS.index("int x")) == frozenset()


# ---------------------------------------------------------------------------
# A captured Ref's USE is a ref use (gap #1076)
# ---------------------------------------------------------------------------

USES = ["read(sourceProvider)", "watch(sourceProvider)", "listen(sourceProvider, (a, b) {})",
        "onDispose(() {})", "invalidate(sourceProvider)", "refresh(sourceProvider)", "exists(sourceProvider)"]


class TestCapturedRefUseAfterAwait:
    """VIOLATION 5: the use after an await needs the captured Ref's own guard."""

    @pytest.mark.parametrize("use", USES)
    def test_a_use_after_an_await_with_no_guard_is_flagged(self, tmp_path, use):
        _flagged(tmp_path, f"""\
  Future<void> reload() async {{
    final build = ref;
    if (!build.mounted) return;
    await work();
    build.{use};
  }}
""", AFTER_AWAIT)

    def test_the_context_names_the_captured_ref_and_the_use(self, tmp_path):
        (tmp_path / "probe.dart").write_text(_notifier("""\
  Future<void> reload() async {
    final build = ref;
    if (!build.mounted) return;
    await work();
    build.read(sourceProvider);
  }
"""))
        (found,) = RiverpodScanner().scan_directory(tmp_path)
        assert "Missing build.mounted after await" in found.context
        assert "build.read()" in found.context

    def test_a_ref_parameter_use_after_an_await_with_no_guard(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    await work();
    build.read(sourceProvider);
  }
""", AFTER_AWAIT)

    def test_no_guard_at_all_is_an_entry_use_and_an_after_await_use(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    await work();
    build.read(sourceProvider);
  }
""", ENTRY, AFTER_AWAIT)

    def test_a_guard_on_ref_does_not_guard_a_captured_ref(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!build.mounted) return;
    await work();
    if (!ref.mounted) return;
    build.read(sourceProvider);
  }
""", AFTER_AWAIT)

    def test_a_guard_on_another_captured_ref_does_not_guard_this_one(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> load(Ref build, Ref other) async {
    if (!build.mounted) return;
    await work();
    if (!other.mounted) return;
    build.read(sourceProvider);
  }
""", AFTER_AWAIT)

    def test_a_guard_another_await_separates_from_the_use(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!build.mounted) return;
    await first();
    if (!build.mounted) return;
    await second();
    build.read(sourceProvider);
  }
""", AFTER_AWAIT)

    def test_a_guard_that_does_not_exit(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!build.mounted) return;
    await work();
    if (!build.mounted) {
      log('gone');
    }
    build.read(sourceProvider);
  }
""", AFTER_AWAIT)

    def test_a_guard_on_a_receiver_that_is_no_capture_does_not_cover_it(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Holder holder) async {
    final build = ref;
    if (!build.mounted) return;
    await work();
    if (!holder.ref.mounted) return;
    build.read(sourceProvider);
  }
""", AFTER_AWAIT)

    def test_the_guarded_use_is_clean(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!build.mounted) return;
    await work();
    if (!build.mounted) return;
    build.read(sourceProvider);
  }
""")

    @pytest.mark.parametrize("use", USES)
    def test_every_guarded_use_is_clean(self, tmp_path, use):
        _clean(tmp_path, f"""\
  Future<void> reload(Ref build) async {{
    if (!build.mounted) return;
    await work();
    if (!build.mounted) return;
    build.{use};
  }}
""")

    def test_a_guard_on_the_capture_covers_a_use_of_the_capture_and_of_ref(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!build.mounted) return;
    await work();
    if (!build.mounted) return;
    build.read(sourceProvider);
    ref.read(otherProvider);
  }
""")

    def test_a_block_guard_that_exits_covers_the_use(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!build.mounted) return;
    await work();
    if (!build.mounted) {
      return;
    }
    build.read(sourceProvider);
  }
""")

    def test_a_use_in_a_comment_or_a_string_is_not_a_use(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!build.mounted) return;
    await work();
    // build.read(sourceProvider);
    log('build.read(sourceProvider)');
  }
""")

    def test_the_mounted_check_itself_is_not_a_use(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!build.mounted) return;
    await work();
    final alive = build.mounted;
    log(alive);
  }
""")

    @pytest.mark.parametrize("receiver", ["other.build", "rebuild", "build2", "_build"])
    def test_a_receiver_that_only_ends_or_starts_like_the_capture_is_not_it(self, tmp_path, receiver):
        _clean(tmp_path, f"""\
  Future<void> reload() async {{
    final build = ref;
    if (!build.mounted) return;
    await work();
    log({receiver}.read(sourceProvider));
  }}
""")


class TestCapturedRefUseAtEntry:
    """VIOLATION 4: a captured Ref's use before its own guard."""

    def test_a_use_before_the_guard_is_flagged(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> load(Ref build) async {
    build.read(sourceProvider);
    if (!build.mounted) return;
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""", ENTRY)

    def test_a_guard_on_ref_does_not_precede_the_use_of_a_capture(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!ref.mounted) return;
    build.read(sourceProvider);
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""", ENTRY)

    def test_the_context_names_the_captured_use(self, tmp_path):
        (tmp_path / "probe.dart").write_text(_notifier("""\
  Future<void> load(Ref build) async {
    build.onDispose(() {});
    if (!build.mounted) return;
  }
"""))
        (found,) = RiverpodScanner().scan_directory(tmp_path)
        assert found.violation_type == ENTRY
        assert "build.onDispose() before mounted check" in found.context

    def test_the_guard_before_the_use_is_clean(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> load(Ref build) async {
    if (!build.mounted) return;
    build.read(sourceProvider);
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""")

    def test_the_build_method_has_no_entry_to_guard(self, tmp_path):
        source = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@riverpod
class Probe extends _$Probe {
  @override
  Future<int> build() async {
    final build = ref;
    final seed = build.watch(seedProvider);
    final loaded = await load(seed);
    if (!build.mounted) return 0;
    return loaded;
  }
}
"""
        assert _types(tmp_path, source) == []


class TestCapturedRefUseInCatchAndFinally:
    """VIOLATIONS 6 and 6b."""

    def test_a_use_in_a_catch_with_no_guard(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      build.read(loggerProvider);
    }
  }
""", IN_CATCH)

    def test_a_use_in_an_on_clause_with_no_guard(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } on StateError {
      build.invalidate(sourceProvider);
    }
  }
""", IN_CATCH)

    def test_a_use_in_a_finally_with_no_guard(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } finally {
      build.read(loggerProvider);
    }
  }
""", IN_FINALLY)

    def test_a_guard_on_ref_does_not_guard_a_use_in_a_catch(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      if (!ref.mounted) return;
      build.read(loggerProvider);
    }
  }
""", IN_CATCH)

    def test_a_positive_block_on_ref_does_not_guard_a_use_of_a_capture(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      if (ref.mounted) {
        build.read(loggerProvider);
      }
    }
  }
""", IN_CATCH)

    def test_a_positive_block_on_another_capture_does_not_guard_a_use_in_a_finally(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref build, Ref other) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } finally {
      if (other.mounted) {
        build.read(loggerProvider);
      }
    }
  }
""", IN_FINALLY)

    def test_a_positive_block_covers_only_its_own_region(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      if (build.mounted) {
        build.read(loggerProvider);
      }
      build.read(otherProvider);
    }
  }
""", IN_CATCH)

    def test_the_leftmost_danger_across_refs_is_the_one_reported(self, tmp_path):
        (tmp_path / "probe.dart").write_text(_notifier("""\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      build.read(loggerProvider);
      ref.read(otherProvider);
    }
  }
"""))
        (found,) = RiverpodScanner().scan_directory(tmp_path)
        assert "build.read" in found.context

    def test_the_early_return_guard_in_a_catch_covers_the_use(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      if (!build.mounted) return;
      build.read(loggerProvider);
    }
  }
""")

    def test_the_positive_block_in_a_catch_covers_the_use(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      if (build.mounted) {
        build.read(loggerProvider);
      }
    }
  }
""")

    def test_the_positive_check_in_a_finally_covers_the_use(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } finally {
      if (build.mounted) build.read(loggerProvider);
    }
  }
""")

    def test_one_guard_on_the_capture_covers_the_capture_and_ref(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload(Ref build) async {
    if (!build.mounted) return;
    try {
      await work();
      if (!build.mounted) return;
    } catch (e) {
      if (!build.mounted) return;
      build.read(loggerProvider);
      ref.read(otherProvider);
    }
  }
""")


class TestCapturedRefUseInUiCallbacks:
    """VIOLATION 15b."""

    def test_a_use_in_the_closure_with_no_guard(self, tmp_path):
        _flagged(tmp_path, """\
  Widget _actions(BuildContext dialogContext) {
    final build = ref;
    return TextButton(
      onPressed: () {
        build.read(sourceProvider);
      },
      child: const Text('OK'),
    );
  }
""", CALLBACK)

    def test_a_guard_on_ref_does_not_guard_a_use_of_a_capture_in_the_closure(self, tmp_path):
        _flagged(tmp_path, """\
  Widget _actions(BuildContext dialogContext, Ref build) {
    return TextButton(
      onPressed: () {
        if (!ref.mounted) return;
        build.read(sourceProvider);
      },
      child: const Text('OK'),
    );
  }
""", CALLBACK)

    def test_a_guard_on_the_capture_covers_the_use_in_the_closure(self, tmp_path):
        _clean(tmp_path, """\
  Widget _actions(BuildContext dialogContext) {
    final build = ref;
    return TextButton(
      onPressed: () {
        if (!build.mounted) return;
        build.read(sourceProvider);
      },
      child: const Text('OK'),
    );
  }
""")

    def test_the_positive_block_on_the_capture_covers_the_use_in_the_closure(self, tmp_path):
        _clean(tmp_path, """\
  Widget _actions(BuildContext dialogContext, Ref build) {
    return TextButton(
      onPressed: () {
        if (build.mounted) {
          build.read(sourceProvider);
        }
      },
      child: const Text('OK'),
    );
  }
""")


class TestCapturedRefUseInSyncHelpers:
    """VIOLATION 10: a sync helper that uses a Ref it was handed."""

    HELPER = """\
  Future<void> run() async {
    final build = ref;
    await work();
    _emit(build);
  }

  void _emit(Ref build) {
%s
    build.read(sourceProvider);
  }
"""

    def test_a_helper_that_uses_its_ref_parameter_unguarded_is_flagged(self, tmp_path):
        _flagged(tmp_path, self.HELPER % "", SYNC)

    def test_a_guard_on_ref_does_not_guard_the_helpers_capture(self, tmp_path):
        _flagged(tmp_path, self.HELPER % "    if (!ref.mounted) return;", SYNC)

    def test_a_guard_on_the_parameter_covers_the_helper(self, tmp_path):
        _clean(tmp_path, self.HELPER % "    if (!build.mounted) return;")

    def test_a_helper_declared_before_the_async_method_is_flagged_too(self, tmp_path):
        _flagged(tmp_path, """\
  void _emit(Ref build) {
    build.read(sourceProvider);
  }

  Future<void> run() async {
    final build = ref;
    await work();
    _emit(build);
  }
""", SYNC)


class TestCapturedRefUseInAsyncStarProvider:
    """VIOLATION 14."""

    SOURCE = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@riverpod
Stream<int> feed(Ref ref) async* {
  final build = ref;
%s
  final value = build.read(sourceProvider);
  yield value;
}
"""

    STALE = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@riverpod
Stream<int> feed(Ref ref) async* {
  final build = ref;
  await settle();
%s
  final value = build.read(sourceProvider);
  yield value;
}
"""

    def test_an_unguarded_use_of_a_capture_is_flagged(self, tmp_path):
        assert _types(tmp_path, self.SOURCE % "") == [ASYNC_STAR.value]

    def test_the_capture_right_after_its_declaration_is_ref(self, tmp_path):
        # `build` IS `ref` there, so a guard on `ref` covers it.
        assert _types(tmp_path, self.SOURCE % "  if (!ref.mounted) return;") == []

    def test_a_guard_on_the_capture_covers_it(self, tmp_path):
        assert _types(tmp_path, self.SOURCE % "  if (!build.mounted) return;") == []

    def test_a_use_after_an_await_needs_the_captures_own_guard(self, tmp_path):
        assert _types(tmp_path, self.STALE % "  if (!ref.mounted) return;") == [ASYNC_STAR.value]

    def test_a_use_after_an_await_behind_the_captures_own_guard(self, tmp_path):
        assert _types(tmp_path, self.STALE % "  if (!build.mounted) return;") == []


# ---------------------------------------------------------------------------
# The sync-vs-async decision is the method's own signature (gap #1075)
# ---------------------------------------------------------------------------

class TestSignatureDeclaresAsync:
    @pytest.mark.parametrize("declaration", [
        "Future<void> run() async {",
        "Future<void> run()async{",
        "void run() async {",
        "Stream<int> feed(Ref ref) async* {",
        "Iterable<int> gen() sync* {",
        "Future<void> run(\n    int a,\n  ) async\n  {",
        "Future<void> run() async",
    ])
    def test_the_marker_between_the_parameter_list_and_the_body(self, declaration):
        assert signature_declares_async(declaration)

    @pytest.mark.parametrize("declaration", [
        "void _emit() {",
        "void _emit(Ref build) {",
        "void _emit(int async) {",
        "void _emit() ",
        "bool isAsync() {",
    ])
    def test_a_sync_signature(self, declaration):
        assert not signature_declares_async(declaration)


class TestMethodDatabaseAsyncness:
    def test_a_sync_method_declared_after_an_async_one_is_recorded_sync(self, tmp_path):
        (tmp_path / "probe.dart").write_text(_notifier("""\
  Future<void> run() async {
    await work();
  }
  void touch() {
    ref.read(sourceProvider);
  }
  void later() async {
    ref.read(sourceProvider);
  }
"""))
        scanner = RiverpodScanner()
        scanner.scan_directory(tmp_path)
        recorded = {name: m.is_async for (_, _, name), m in scanner._ctx.all_methods.items()}
        assert recorded["run"] is True
        assert recorded["touch"] is False
        assert recorded["later"] is True


# ---------------------------------------------------------------------------
# The use helpers themselves
# ---------------------------------------------------------------------------

class TestCapturedRefUsePattern:
    @pytest.mark.parametrize("code, member", [
        ("build.read(p)", "read"),
        ("build . watch(p)", "watch"),
        ("x = build.onDispose(() {});", "onDispose"),
        ("build.mountedAt", "mountedAt"),
        ("(build.listen(p, f))", "listen"),
    ])
    def test_any_member_but_mounted_is_a_use(self, code, member):
        assert captured_ref_use_pattern("build").search(code).group(1) == member

    @pytest.mark.parametrize("code", [
        "build.mounted",
        "if (!build.mounted) return;",
        "other.build.read(p)",
        "rebuild.read(p)",
        "build2.read(p)",
        "this.build.read(p)",
        "build",
        "f(build)",
    ])
    def test_the_guard_a_longer_name_and_a_bare_mention_are_not_uses(self, code):
        assert captured_ref_use_pattern("build").search(code) is None


class TestFirstUnguardedCapturedUse:
    def test_the_leftmost_use_without_its_own_guard(self):
        code = "a.read(p);\nif (!b.mounted) return;\nb.read(p);\n"
        name, use = first_unguarded_captured_use(code, {"a", "b"})
        assert (name, use.group(0)) == ("a", "a.read")

    def test_a_guard_before_the_use_clears_it(self):
        assert first_unguarded_captured_use("if (!b.mounted) return;\nb.read(p);", {"b"}) is None

    def test_a_guard_after_the_use_does_not(self):
        code = "b.read(p);\nif (!b.mounted) return;\n"
        assert first_unguarded_captured_use(code, {"b"})[0] == "b"

    def test_a_guard_on_another_name_does_not(self):
        code = "if (!a.mounted) return;\nb.read(p);\n"
        assert first_unguarded_captured_use(code, {"a", "b"})[0] == "b"

    def test_ref_itself_is_never_a_captured_name(self):
        assert first_unguarded_captured_use("ref.read(p);", {"ref"}) is None

    def test_the_guard_suffix_narrows_the_guard(self):
        code = "if (!b.mounted) { log(); }\nb.read(p);\n"
        assert first_unguarded_captured_use(code, {"b"}, r"\s*return") is not None
        assert first_unguarded_captured_use(code, {"b"}) is None


# ---------------------------------------------------------------------------
# A local captured from `ref` and used right after is `ref` (gap #1076)
# ---------------------------------------------------------------------------

class TestFreshCapture:
    """`final build = ref;` followed, with no await or closure between, by `build.read`.

    The Notifier's current `ref` and `build` are one Ref there, so the use is a
    `ref` use and any guard that covers a `ref` use covers it. A use after an
    await, in a closure, or on a `Ref` parameter may be on a replaced Ref and
    needs `build`'s own guard.
    """

    def test_an_entry_guard_on_ref_before_the_declaration_covers_the_use(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    final build = ref;
    final connected = build.read(connectivityProvider);
    if (!connected) return;
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""")

    def test_an_entry_guard_on_ref_after_the_declaration_covers_the_use(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!ref.mounted) return;
    final connected = build.read(connectivityProvider);
    if (!connected) return;
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""")

    def test_a_function_literal_that_ends_before_the_use_does_not_make_it_stale(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    final build = ref;
    final user = state.value?.whenOrNull(loaded: (user, _) => user);
    final other = items.map((item) {
      return item.id;
    });
    build.read(connectivityProvider);
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""")

    def test_the_use_with_no_guard_at_all_is_an_entry_use(self, tmp_path):
        (tmp_path / "probe.dart").write_text(_notifier("""\
  Future<void> reload() async {
    final build = ref;
    build.read(connectivityProvider);
    await work();
    if (!build.mounted) return;
    state = 1;
  }
"""))
        (found,) = RiverpodScanner().scan_directory(tmp_path)
        assert found.violation_type == ENTRY
        assert "build.read() before mounted check" in found.context

    def test_a_capture_declared_after_an_await_and_a_guard_on_ref_is_ref(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    await work();
    if (!ref.mounted) return;
    final build = ref;
    build.read(connectivityProvider);
  }
""")

    def test_a_capture_declared_after_an_await_with_no_guard_is_flagged(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    await work();
    final build = ref;
    build.read(connectivityProvider);
  }
""", AFTER_AWAIT)

    def test_a_use_after_an_await_is_stale(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    final build = ref;
    if (!ref.mounted) return;
    await work();
    if (!ref.mounted) return;
    build.read(connectivityProvider);
  }
""", ENTRY, AFTER_AWAIT)

    def test_a_use_in_a_closure_is_stale(self, tmp_path):
        _flagged(tmp_path, """\
  Widget _actions(BuildContext dialogContext) {
    if (!ref.mounted) return const SizedBox();
    final build = ref;
    return TextButton(
      onPressed: () {
        if (!ref.mounted) return;
        build.read(sourceProvider);
      },
      child: const Text('OK'),
    );
  }
""", CALLBACK)

    def test_a_use_in_a_deferred_arrow_is_stale(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    final build = ref;
    unawaited(Future<void>.delayed(delay, () => build.read(sourceProvider)));
    await work();
    if (!build.mounted) return;
    state = 1;
  }
""", ENTRY)

    def test_a_fresh_use_in_a_catch_follows_the_guard_that_covers_ref(self, tmp_path):
        _clean(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    try {
      await work();
      if (!ref.mounted) return;
    } catch (e) {
      if (!ref.mounted) return;
      final build = ref;
      build.read(loggerProvider);
    }
  }
""")

    def test_a_fresh_use_in_a_catch_with_no_guard_is_flagged(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> reload() async {
    if (!ref.mounted) return;
    try {
      await work();
      if (!ref.mounted) return;
    } catch (e) {
      final build = ref;
      build.read(loggerProvider);
    }
  }
""", IN_CATCH)

    def test_a_sync_helpers_local_capture_is_ref(self, tmp_path):
        source = _notifier("""\
  Future<void> run() async {
    await work();
    _emit();
  }

  void _emit() {
    if (!ref.mounted) return;
    final build = ref;
    build.read(sourceProvider);
  }
""")
        assert _types(tmp_path, source) == []

    def test_a_sync_helpers_local_capture_with_no_guard_is_flagged(self, tmp_path):
        _flagged(tmp_path, """\
  Future<void> run() async {
    await work();
    _emit();
  }

  void _emit() {
    final build = ref;
    build.read(sourceProvider);
  }
""", SYNC)


class TestCapturedRefUses:
    def test_a_use_right_after_the_declaration_is_fresh(self):
        stale, fresh = captured_ref_uses("final b = ref;\nb.read(p);", {"b"})
        assert not stale
        assert [(name, use.group(0)) for name, use in fresh] == [("b", "b.read")]

    def test_an_await_between_makes_it_stale(self):
        stale, fresh = captured_ref_uses("final b = ref;\nawait w();\nb.read(p);", {"b"})
        assert [name for name, _ in stale] == ["b"]
        assert not fresh

    def test_a_use_inside_a_block_closure_is_stale(self):
        stale, fresh = captured_ref_uses("final b = ref;\nf(() {\n  b.read(p);\n});", {"b"})
        assert [name for name, _ in stale] == ["b"]
        assert not fresh

    def test_a_use_inside_an_arrow_closure_is_stale(self):
        stale, fresh = captured_ref_uses("final b = ref;\nf((x) => b.read(p), y);", {"b"})
        assert [name for name, _ in stale] == ["b"]
        assert not fresh

    def test_a_use_after_an_arrow_closure_that_ended_is_fresh(self):
        stale, fresh = captured_ref_uses("final b = ref;\nf((x) => x, y);\nb.read(p);", {"b"})
        assert not stale
        assert [name for name, _ in fresh] == ["b"]

    def test_a_use_after_a_block_closure_that_ended_is_fresh(self):
        stale, fresh = captured_ref_uses("final b = ref;\nf(() {\n  g();\n});\nb.read(p);", {"b"})
        assert not stale
        assert [name for name, _ in fresh] == ["b"]

    @pytest.mark.parametrize("head", ["if (ok) {", "for (final x in xs) {", "while (ok) {", "catch (e) {"])
    def test_a_block_head_is_not_a_function_literal(self, head):
        stale, fresh = captured_ref_uses(f"final b = ref;\n{head}\n  b.read(p);\n}}", {"b"})
        assert not stale
        assert [name for name, _ in fresh] == ["b"]

    def test_a_ref_parameter_is_always_stale(self):
        stale, fresh = captured_ref_uses("b.read(p);", {"b"})
        assert [name for name, _ in stale] == ["b"]
        assert not fresh

    def test_a_use_before_the_declaration_is_stale(self):
        stale, fresh = captured_ref_uses("b.read(p);\nfinal b = ref;", {"b"})
        assert [name for name, _ in stale] == ["b"]
        assert not fresh
