"""VIOLATION 17 (CATCH_GUARD_RETURNS_SUCCESS): a catch whose mounted guard
returns a success value while the catch otherwise returns a failure value.

``catch (e) { if (!ref.mounted) return const Right(null); …; return Left(…); }``
tells the awaiting caller — who is still alive — that a failed operation
succeeded, whenever the host is disposed first.
"""

from riverpod_3_scanner.models import ViolationType
from riverpod_3_scanner.scanner import RiverpodScanner


def _catch(body: str) -> str:
    return f"""\
class Repo {{
  Future<Either<String, void>> save() async {{
    try {{
      await write();
      return const Right(null);
    }} catch (e) {{
{body}
    }}
  }}
}}
"""


def _found(tmp_path, source):
    f = tmp_path / "probe.dart"
    f.write_text(source)
    return [v for v in RiverpodScanner().scan_file(f) if v.violation_type == ViolationType.CATCH_GUARD_RETURNS_SUCCESS]


class TestFlagged:
    def test_right_on_dispose_left_otherwise(self, tmp_path):
        (violation,) = _found(tmp_path, _catch("      if (!ref.mounted) return const Right(null);\n      logger.logError('Failed');\n      return Left('failed: $e');"))
        assert 'returns const Right(null)' in violation.context

    def test_true_on_dispose_false_otherwise(self, tmp_path):
        assert len(_found(tmp_path, _catch("      if (!mounted) return true;\n      return false;"))) == 1

    def test_block_form_guard(self, tmp_path):
        assert len(_found(tmp_path, _catch("      if (!ref.mounted) {\n        return Right(cached);\n      }\n      return Left('failed');"))) == 1

    def test_advice_returns_the_failure_on_both_paths(self, tmp_path):
        (violation,) = _found(tmp_path, _catch("      if (!ref.mounted) return const Right(null);\n      return Left('x');"))
        assert 'Return the failure on both paths' in violation.fix_instructions


class TestClean:
    def test_guard_returns_the_same_failure(self, tmp_path):
        assert _found(tmp_path, _catch("      if (!ref.mounted) return Left('disposed');\n      return Left('failed');")) == []

    def test_no_guard(self, tmp_path):
        assert _found(tmp_path, _catch("      logger.logError('Failed');\n      return Left('failed');")) == []

    def test_catch_that_never_returns_a_failure(self, tmp_path):
        assert _found(tmp_path, _catch("      if (!ref.mounted) return const Right(null);\n      return const Right(null);")) == []

    def test_success_in_a_string_is_not_code(self, tmp_path):
        assert _found(tmp_path, _catch("      logger.logInfo('if (!mounted) return true;');\n      return Left('failed');")) == []
