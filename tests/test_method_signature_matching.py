"""A `Future<` that is not a declaration must not swallow the methods after it.

Every checker finds methods by matching a signature (``Future<T> name(params)
async {``). The generic return type used to be the lazy, DOTALL ``Future<.+?>``
and the async-name regexes also spelled the parameter list as ``\\(.*?\\)``. A lazy
``.+?>`` starts wherever ``Future<`` appears — an awaited expression
(``await Future<void>.delayed(Duration.zero)``), a field initializer, an
arrow-bodied ``Future<int> reload() => ...`` — and runs on to the next ``>`` (or
``) async``) that lets the rest of the pattern fit, swallowing every method
declared in between:

* PASS 1.5 (``RE_METHOD``) never registered the swallowed sync methods, so the
  sync-method check (VIOLATION 10) could not resolve a call to them and went
  silent;
* ``find_async_methods`` returned the WRONG names — ``['reload']`` instead of
  ``['doIt']`` — so the async method after an arrow-bodied ``Future`` method was
  not checked at all (VIOLATIONS 4-6 and 12 all iterate its result).

The signature head now comes from one owner, ``utils.async_signature_head`` and
its ``*_PATTERN`` pieces, which match balanced generics and parameter lists.
"""

import re
import time

import pytest

from riverpod_3_scanner.analysis import _RE_ASYNC_METHOD
from riverpod_3_scanner.scanner import RiverpodScanner
from riverpod_3_scanner.utils import (
    FUTURE_TYPE_PATTERN,
    RE_METHOD,
    STREAM_TYPE_PATTERN,
    async_signature_head,
    find_async_methods,
    find_methods_using_ref,
)

# ---------------------------------------------------------------------------
# Class template. `first` runs the hazard, awaits, then calls the sync method
# `describe` (so `describe` runs in an async context); `second` is a later async
# method. Whatever the hazard is, all three must stay visible.
# ---------------------------------------------------------------------------

CLASS_TEMPLATE = """\
class Foo extends _$Foo {
__MEMBER__
  Future<void> first(Logger logger) async {
    __STATEMENT__
    await work();
    describe(logger);
  }

  void describe(Logger logger) {
    logger.logInfo('last value $state');
  }

  Future<void> second() async {
    await work();
  }
}
"""

# Awaited expressions / statements that used to start a swallowing match, and
# ones that merely contain `>` or generic arguments.
STATEMENTS = [
    pytest.param("await Future<void>.delayed(Duration.zero);", id="future-delayed"),
    pytest.param("await Future<Map<String, int>>.value(<String, int>{});", id="future-nested-generic"),
    pytest.param("final Future<int> pending = Future<int>.value(1);", id="typed-local-future"),
    pytest.param("final ticks = Stream<List<int>>.empty();", id="stream-of-list"),
    pytest.param("await Future<void>.delayed(Duration.zero); await work();", id="two-awaits-one-line"),
    pytest.param("await compute<int, int>(double, 1);", id="compute-two-type-args"),
    pytest.param("if (count > limit) { await work(); }", id="greater-than-comparison"),
    pytest.param("final ok = await work() ?? a > b;", id="greater-than-in-awaited-expression"),
    pytest.param("await work();", id="plain-await"),
]

# Class-level members that used to start a swallowing match.
MEMBERS = [
    pytest.param("", id="no-member"),
    pytest.param("  final Future<void> _ready = Future<void>.value();", id="future-field-initializer"),
    pytest.param("  Future<int> reload() => _fetch();", id="arrow-bodied-future-method"),
    pytest.param("  Future<Map<String, int>> snapshot() => _load();", id="arrow-bodied-nested-generic"),
    pytest.param("  Stream<int> get ticks => Stream<int>.periodic(Duration.zero);", id="stream-getter"),
    pytest.param("  Future<void> Function()? onDone;", id="function-typed-field"),
]


def _class(statement="await work();", member=""):
    return CLASS_TEMPLATE.replace("__STATEMENT__", statement).replace("__MEMBER__", member)


def _names(pattern, text):
    return [m.group(1) for m in pattern.finditer(text)]


# ---------------------------------------------------------------------------
# The three consumers of the signature regexes
# ---------------------------------------------------------------------------


class TestEveryMethodStaysVisible:
    @pytest.mark.parametrize("statement", STATEMENTS)
    @pytest.mark.parametrize("member", MEMBERS)
    def test_async_methods_are_found_by_name(self, statement, member):
        assert find_async_methods(_class(statement, member)) == ["first", "second"]

    @pytest.mark.parametrize("statement", STATEMENTS)
    @pytest.mark.parametrize("member", MEMBERS)
    def test_pass_1_5_registers_every_method(self, statement, member):
        # `describe` is the sync method a swallowing match used to eat.
        assert _names(RE_METHOD, _class(statement, member)) == ["first", "describe", "second"]

    @pytest.mark.parametrize("statement", STATEMENTS)
    @pytest.mark.parametrize("member", MEMBERS)
    def test_async_call_tracing_finds_every_async_method(self, statement, member):
        assert _names(_RE_ASYNC_METHOD, _class(statement, member)) == ["first", "second"]

    def test_find_methods_using_ref_sees_the_method_after_a_delayed_await(self):
        source = """\
class Foo extends _$Foo {
  Future<void> first() async {
    await Future<void>.delayed(Duration.zero);
  }

  void usesRef() {
    ref.read(p);
  }
}
"""
        assert find_methods_using_ref(source) == {"usesRef"}


# ---------------------------------------------------------------------------
# End to end: the report the swallowed method used to lose
# ---------------------------------------------------------------------------

E2E_TEMPLATE = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'foo.g.dart';

@riverpod
__CLASS__
"""


def _e2e_source(statement, member):
    cls = _class(statement, member).replace("class Foo extends _$Foo {", "class Foo extends _$Foo {\n  @override\n  int build() => 0;\n", 1)
    return E2E_TEMPLATE.replace("__CLASS__", cls)


def _types(violations):
    return sorted(v.violation_type.value for v in violations)


class TestSyncMethodCheckEndToEnd:
    """VIOLATION 10 needs `describe` in the method database AND in the async-call trace."""

    @pytest.mark.parametrize("statement", STATEMENTS)
    @pytest.mark.parametrize("member", MEMBERS)
    def test_the_sync_method_called_after_the_awaited_expression_is_flagged(self, tmp_path, statement, member):
        (tmp_path / "foo.dart").write_text(_e2e_source(statement, member))
        violations = RiverpodScanner().scan_directory(tmp_path)
        assert "sync_method_without_mounted_check" in _types(violations)
        (flagged,) = [v for v in violations if v.violation_type.value == "sync_method_without_mounted_check"]
        assert "describe()" in flagged.context

    def test_the_three_of_three_repro(self, tmp_path):
        """The 1.14.2 demo fixture: three violations, one per check, none lost to `Future<void>.delayed`."""
        (tmp_path / "bar.dart").write_text(
            """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'bar.g.dart';

@riverpod
class Bar extends _$Bar {
  @override
  int build() => 0;

  Future<void> afterAwait(Logger logger) async {
    if (!ref.mounted) return;
    await Future<void>.delayed(Duration.zero);
    logger.logInfo('last value $state');
  }

  Future<void> beforeGuard(Logger logger) async {
    logger.logInfo('last value ${state}');
    await Future<void>.delayed(Duration.zero);
    if (!ref.mounted) return;
    state = 1;
  }

  Future<void> run(Logger logger) async {
    await Future<void>.delayed(Duration.zero);
    describe(logger);
  }

  void describe(Logger logger) {
    logger.logInfo('last value $state');
  }

  Future<void> clean(Logger logger) async {
    if (!ref.mounted) return;
    await Future<void>.delayed(Duration.zero);
    logger.logInfo(r'last value $state');
    if (!ref.mounted) return;
    logger.logInfo('last value $state');
  }
}
"""
        )
        violations = RiverpodScanner().scan_directory(tmp_path)
        assert sorted((v.violation_type.value, v.line_number) for v in violations) == [
            ("missing_mounted_after_await", 12),
            ("ref_read_before_mounted", 17),
            ("sync_method_without_mounted_check", 28),
        ]


class TestAsyncMethodAfterAnArrowBodiedFutureMethodIsChecked:
    """`Future<int> reload() => ...` used to make find_async_methods return
    ['reload'] and drop the real async method behind it — so its unguarded
    catch went unreported."""

    SOURCE = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'foo.g.dart';

@riverpod
class Foo extends _$Foo {
  @override
  int build() => 0;

  Future<int> reload() => doIt();

  Future<int> doIt() async {
    if (!ref.mounted) return 0;
    try {
      await work();
      if (!ref.mounted) return 0;
      state = 1;
    } catch (e) {
      ref.read(errorProvider).report(e);
    }
    return 1;
  }
}
"""

    def test_the_async_method_is_named_correctly(self):
        assert find_async_methods(self.SOURCE) == ["doIt"]

    def test_its_unguarded_catch_is_reported(self, tmp_path):
        f = tmp_path / "foo.dart"
        f.write_text(self.SOURCE)
        assert _types(RiverpodScanner().scan_file(f)) == ["missing_mounted_in_catch"]

    def test_a_sync_arrow_method_is_not_reported_as_async(self):
        assert "reload" not in find_async_methods(self.SOURCE)


class TestParameterListsWithParenthesesAreChecked:
    """A `void Function()` parameter or a `const Duration(...)` default put `)`
    inside the parameter list. `find_async_methods` matched such a method, but
    the per-method lookups that pull its body out (`\\([^)]*\\)`) did not, and a
    lookup that finds nothing does `continue` — so the method was named async
    and then never checked. Both now come from the same owner."""

    @pytest.mark.parametrize(
        "params",
        [
            "{required void Function() onApproved}",
            "void Function(int) cb",
            "{Duration timeout = const Duration(seconds: 1)}",
            "int Function(int Function(int)) nested",
        ],
    )
    def test_unguarded_entry_state_write_is_flagged(self, tmp_path, params):
        f = tmp_path / "foo.dart"
        f.write_text(
            f"""\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'foo.g.dart';

@riverpod
class Foo extends _$Foo {{
  @override
  int build() => 0;

  Future<void> update({params}) async {{
    state = 1;
    await work();
    if (!ref.mounted) return;
    state = 2;
  }}
}}
"""
        )
        assert _types(RiverpodScanner().scan_file(f)) == ["ref_read_before_mounted"]

    def test_the_same_method_with_a_guard_is_clean(self, tmp_path):
        f = tmp_path / "foo.dart"
        f.write_text(
            """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'foo.g.dart';

@riverpod
class Foo extends _$Foo {
  @override
  int build() => 0;

  Future<void> update({required void Function() onApproved}) async {
    if (!ref.mounted) return;
    state = 1;
    await work();
    if (!ref.mounted) return;
    state = 2;
  }
}
"""
        )
        assert RiverpodScanner().scan_file(f) == []

    @pytest.mark.parametrize(
        "params",
        ["{required void Function() onApproved}", "{Duration timeout = const Duration(seconds: 1)}"],
    )
    def test_every_name_find_async_methods_returns_has_a_body_lookup(self, params):
        """The two halves agree: a name that is listed as async can be looked up."""
        source = f"class Foo extends _$Foo {{\n  Future<void> update({params}) async {{\n  }}\n}}\n"
        (name,) = find_async_methods(source)
        assert re.search(async_signature_head(name) + r"\s+async\*?\s*\{", source) is not None


# ---------------------------------------------------------------------------
# Return types and parameter lists a signature must still match
# ---------------------------------------------------------------------------


class TestSignaturesStillMatch:
    @pytest.mark.parametrize(
        "signature, name",
        [
            ("Future<void> run() async {", "run"),
            ("Future<Map<String, int>> load() async {", "load"),
            ("Future<Either<Failure, void>> save(int a) async {", "save"),
            ("Future<Map<String, List<Map<String, int>>>> deep() async {", "deep"),
            ("FutureOr<List<int>> build() async {", "build"),
            ("Stream<List<Item>> watch() async* {", "watch"),
            ("Future<void> withDefault({Duration timeout = const Duration(seconds: 1)}) async {", "withDefault"),
            ("Future<void> withCallback(void Function(int) cb) async {", "withCallback"),
            ("Future<void> multiLine(\n    int a,\n    String b,\n  ) async {", "multiLine"),
            ("Future<(int, String)> record() async {", "record"),
        ],
    )
    def test_async_method_signatures_are_found(self, signature, name):
        assert find_async_methods(f"class Foo extends _$Foo {{\n  {signature}\n  }}\n}}\n") == [name]

    @pytest.mark.parametrize(
        "source",
        [
            "Future<int> reload() => _fetch();",
            "Future<int> reload();",
            "final Future<void> ready = Future<void>.value();",
            "Stream<int> get ticks => Stream<int>.empty();",
            "await Future<void>.delayed(Duration.zero);",
        ],
    )
    def test_things_that_are_not_async_declarations_are_not_found(self, source):
        assert find_async_methods(f"class Foo extends _$Foo {{\n  {source}\n}}\n") == []

    def test_the_head_starts_at_the_declaration_not_at_an_earlier_expression(self):
        text = "await Future<void>.delayed(Duration.zero);\n}\nFuture<void> real() async {"
        match = re.search(async_signature_head(), text)
        assert match is not None
        assert match.group(1) == "real"
        assert match.start() == text.index("Future<void> real")

    def test_a_named_head_matches_only_that_method(self):
        text = "Future<void> a() async {}\nFuture<void> b() async {}"
        assert re.search(async_signature_head("b"), text).start() == text.index("Future<void> b")

    def test_a_generic_type_cannot_cross_a_statement(self):
        assert re.search(FUTURE_TYPE_PATTERN, "Future<int\n;\n> x") is None
        assert re.search(STREAM_TYPE_PATTERN, "Stream<int> x").group(0) == "Stream<int>"


# ---------------------------------------------------------------------------
# The balanced patterns must stay linear
# ---------------------------------------------------------------------------


class TestNoPathologicalBacktracking:
    def test_a_large_class_with_many_swallow_candidates_scans_quickly(self):
        body = "\n".join(
            f"  Future<void> m{i}() async {{\n    await Future<Map<String, List<int>>>.value({{}});\n    v{i}();\n  }}\n\n"
            f"  void v{i}() {{\n    log(a > b);\n  }}\n"
            for i in range(400)
        )
        source = f"class Foo extends _$Foo {{\n{body}}}\n"
        started = time.perf_counter()
        names = find_async_methods(source)
        registered = _names(RE_METHOD, source)
        elapsed = time.perf_counter() - started
        assert len(names) == 400 and len(registered) == 800
        assert elapsed < 5.0, f"signature matching took {elapsed:.1f}s"

    def test_unclosed_generics_and_parens_fail_fast(self):
        source = "class Foo {\n" + "  Future<Map<String, " * 50 + "\n" + "  void f(" * 50 + "\n}\n"
        started = time.perf_counter()
        assert find_async_methods(source) == []
        assert list(RE_METHOD.finditer(source)) == []
        assert time.perf_counter() - started < 5.0
