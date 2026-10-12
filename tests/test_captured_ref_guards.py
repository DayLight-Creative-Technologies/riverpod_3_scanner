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
"""

import pytest

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner
from riverpod_3_scanner.utils import (
    captured_ref_names,
    captured_ref_names_at,
    class_member_spans,
    header_param_text,
    mounted_receivers,
    params_of_signature,
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

# The helper is declared BEFORE the async method on purpose: VIOLATION 10's
# "is this method async?" test looks for `async` in the 50 characters before the
# declaration, which would otherwise find `run`'s own and skip the helper.
SYNC_HELPER_CALLED_AFTER_AWAIT = """\
  void _emit(%s) {
%s
    state = 1;
  }

  Future<void> run() async {
    await work();
    _emit();
  }
"""


class TestSyncHelpers:
    def test_the_helper_with_no_guard_is_flagged(self, tmp_path):
        _flagged(tmp_path, SYNC_HELPER_CALLED_AFTER_AWAIT % ("", ""), SYNC)

    def test_a_ref_parameter_guard_at_the_helpers_entry(self, tmp_path):
        source = _notifier("""\
  void _emit(Ref build) {
    if (!build.mounted) return;
    state = 1;
  }

  Future<void> run() async {
    final build = ref;
    await work();
    _emit(build);
  }
""")
        assert _types(tmp_path, source) == []

    def test_a_local_capture_guard_at_the_helpers_entry(self, tmp_path):
        source = _notifier("""\
  void _emit() {
    final build = ref;
    if (!build.mounted) return;
    state = 1;
  }

  Future<void> run() async {
    await work();
    _emit();
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
  void _helper() {
    state = 1;
  }

  Future<void> run(Ref build) async {
    if (!build.mounted) return;
    await work();
    if (!build.mounted) return;
    _helper();
  }
""")
        assert _types(tmp_path, source) == []

    def test_a_guard_on_a_non_ref_does_not_end_the_danger_zone(self, tmp_path):
        source = _notifier("""\
  void _helper() {
    state = 1;
  }

  Future<void> run(BuildContext build) async {
    await work();
    if (!build.mounted) return;
    _helper();
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
