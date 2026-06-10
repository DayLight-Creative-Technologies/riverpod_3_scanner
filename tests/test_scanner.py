"""Scanner orchestration and CLI behavior tests."""

import json
import subprocess
import sys
from pathlib import Path

from riverpod_3_scanner import __version__
from riverpod_3_scanner.scanner import RiverpodScanner

# A notifier with exactly one violation: `state = await ...` (STATE_ASSIGN_AWAIT).
VIOLATING_NOTIFIER = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class Counter extends _$Counter {
  @override
  Future<int> build() async => 0;

  Future<void> refresh() async {
    if (!ref.mounted) return;
    state = await AsyncValue.guard(() async => 1);
  }
}
"""

SUPPRESSED_NOTIFIER = VIOLATING_NOTIFIER.replace(
    "    state = await AsyncValue.guard(() async => 1);",
    "    // riverpod_scanner:ignore\n"
    "    state = await AsyncValue.guard(() async => 1);",
)


class TestSuppressionWiring:
    def test_violation_detected_without_suppression(self, tmp_path):
        f = tmp_path / "counter.dart"
        f.write_text(VIOLATING_NOTIFIER)
        scanner = RiverpodScanner()
        violations = scanner.scan_file(f)
        assert [v.violation_type.value for v in violations] == ["state_assign_await"]
        assert scanner.suppressed_count == 0

    def test_suppressed_violation_is_counted(self, tmp_path):
        f = tmp_path / "counter.dart"
        f.write_text(SUPPRESSED_NOTIFIER)
        scanner = RiverpodScanner()
        violations = scanner.scan_file(f)
        assert violations == []
        assert scanner.suppressed_count == 1

    def test_file_level_suppression_skips_file(self, tmp_path):
        f = tmp_path / "counter.dart"
        f.write_text("// riverpod_scanner:ignore-file\n" + VIOLATING_NOTIFIER)
        scanner = RiverpodScanner()
        assert scanner.scan_file(f) == []

    def test_scan_directory_resets_suppressed_count(self, tmp_path):
        f = tmp_path / "counter.dart"
        f.write_text(SUPPRESSED_NOTIFIER)
        scanner = RiverpodScanner()
        scanner.scan_directory(tmp_path)
        scanner.scan_directory(tmp_path)  # must not double-count
        assert scanner.suppressed_count == 1


class TestScanDirectory:
    def test_skips_generated_files(self, tmp_path):
        (tmp_path / "counter.g.dart").write_text(VIOLATING_NOTIFIER)
        (tmp_path / "counter.freezed.dart").write_text(VIOLATING_NOTIFIER)
        scanner = RiverpodScanner()
        assert scanner.scan_directory(tmp_path) == []

    def test_unreadable_file_does_not_abort_scan(self, tmp_path, capsys):
        (tmp_path / "bad.dart").write_bytes(b"\xff\xfe not utf8 \xc3")
        (tmp_path / "counter.dart").write_text(VIOLATING_NOTIFIER)
        scanner = RiverpodScanner()
        violations = scanner.scan_directory(tmp_path)
        assert [v.violation_type.value for v in violations] == ["state_assign_await"]


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "riverpod_3_scanner", *args],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )


class TestCli:
    def test_version_flag(self):
        result = run_cli("--version")
        assert result.returncode == 0
        assert __version__ in result.stdout

    def test_exit_code_2_for_missing_path(self, tmp_path):
        result = run_cli(str(tmp_path / "does-not-exist"))
        assert result.returncode == 2

    def test_exit_code_0_for_clean_directory(self, tmp_path):
        (tmp_path / "clean.dart").write_text("class Plain {}\n")
        result = run_cli(str(tmp_path))
        assert result.returncode == 0
        assert "No Riverpod 3.0 violations detected" in result.stdout

    def test_exit_code_1_and_json_for_violations(self, tmp_path):
        (tmp_path / "counter.dart").write_text(VIOLATING_NOTIFIER)
        result = run_cli(str(tmp_path), "--format", "json")
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["violations_count"] == 1
        assert payload["version"] == __version__
        assert payload["summary"]["by_type"] == {"state_assign_await": 1}

    def test_json_reports_suppressed_count(self, tmp_path):
        (tmp_path / "counter.dart").write_text(SUPPRESSED_NOTIFIER)
        result = run_cli(str(tmp_path), "--format", "json")
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["violations_count"] == 0
        assert payload["suppressed_count"] == 1

    def test_text_reports_suppressed_count(self, tmp_path):
        (tmp_path / "counter.dart").write_text(SUPPRESSED_NOTIFIER)
        result = run_cli(str(tmp_path))
        assert result.returncode == 0
        assert "Suppressed violations: 1" in result.stdout
