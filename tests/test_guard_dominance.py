"""A mounted guard protects the rest of ITS block, not everything after it.

`_leftmost_unguarded_danger` (shared by VIOLATION 6, 6b, 10 and 15b) counted any
guard that appeared earlier in the text, so a guard nested in a conditional
block hid a later use outside that block. Found through SocialScoreKeeper gap
#822: `if (url != null) { await launch(); if (!ref.mounted) return; }` followed
by `ref.read(p)` — unguarded whenever `url` is null.
"""

import re

from riverpod_3_scanner.checkers import _CATCH_DANGER_PATTERNS, _leftmost_unguarded_danger
from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner

GUARD = re.compile(r'if\s*\(\s*!ref\.mounted\s*\)')


def _danger(code):
    found = _leftmost_unguarded_danger(code, _CATCH_DANGER_PATTERNS, GUARD)
    return None if found is None else found.group(0)


def test_straight_line_guard_protects_what_follows():
    assert _danger("if (!ref.mounted) return;\nref.read(p);\nstate = x;") is None


def test_a_guard_inside_a_conditional_block_does_not_protect_a_use_after_it():
    assert _danger("if (url != null) {\n  await go();\n  if (!ref.mounted) return;\n}\nref.read(p);") == 'ref.read'


def test_a_guard_protects_uses_inside_its_own_block():
    assert _danger("if (url != null) {\n  await go();\n  if (!ref.mounted) return;\n  ref.read(p);\n}") is None


def test_the_first_unguarded_use_is_reported_even_after_a_guarded_one():
    code = "if (a) {\n  if (!ref.mounted) return;\n  ref.read(p);\n}\nstate = x;"
    assert _danger(code) == 'state ='


def test_a_use_inside_the_negated_guards_own_branch_is_unguarded():
    # The branch runs precisely when the host is gone (invite_notifier.dart shape).
    assert _danger("if (!ref.mounted) {\n  state = x;\n  return;\n}") == 'state ='


def test_a_positive_check_protects_only_its_own_branch():
    positive = re.compile(r'if\s*\(\s*!?\s*ref\.mounted\s*\)')
    assert _leftmost_unguarded_danger("if (ref.mounted) {\n  ref.read(p);\n}", _CATCH_DANGER_PATTERNS, positive) is None
    inverted = _leftmost_unguarded_danger("if (ref.mounted) return;\nref.read(p);", _CATCH_DANGER_PATTERNS, positive)
    assert inverted is not None and inverted.group(0) == 'ref.read'


def test_a_guard_after_the_use_does_not_protect_it():
    assert _danger("ref.read(p);\nif (!ref.mounted) return;") == 'ref.read'


def test_a_binding_less_on_clause_is_judged_like_a_catch(tmp_path):
    source = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@riverpod
class Probe extends _$Probe {
  @override
  int build() => 0;

  Future<void> run() async {
    if (!ref.mounted) return;
    try {
      await work();
      if (!ref.mounted) return;
    } on TimeoutException {
      state = -1;
    }
  }
}
"""
    f = tmp_path / "probe.dart"
    f.write_text(source)
    found = [v for v in RiverpodScanner().scan_file(f) if v.violation_type == ViolationType.MISSING_MOUNTED_IN_CATCH]
    assert len(found) == 1


def test_catch_block_with_a_nested_guard_is_flagged_end_to_end(tmp_path):
    source = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'probe.g.dart';

@riverpod
class Probe extends _$Probe {
  @override
  int build() => 0;

  Future<void> run() async {
    if (!ref.mounted) return;
    final logger = ref.read(unifiedLoggerProvider);
    try {
      await work();
      if (!ref.mounted) return;
    } catch (e) {
      logger.logError('Failed', error: e);
      if (e is StateError) {
        if (!ref.mounted) return;
      }
      state = -1;
    }
  }
}
"""
    f = tmp_path / "probe.dart"
    f.write_text(source)
    found = [v for v in RiverpodScanner().scan_file(f) if v.violation_type == ViolationType.MISSING_MOUNTED_IN_CATCH]
    assert len(found) == 1
