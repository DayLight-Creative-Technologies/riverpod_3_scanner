"""Tests for the --baseline / --write-baseline remove-only ledger.

A baseline lets the scanner be adopted on a codebase with pre-existing
violations: accepted signatures are suppressed so the scan fails only on NEW
violations, while stale entries (the violation is gone) are reported, never a
failure.
"""

import json
import subprocess
import sys
from pathlib import Path

from riverpod_3_scanner.models import Violation, ViolationType
from riverpod_3_scanner.scanner import _baseline_key, _load_baseline, _write_baseline

# A sync + reactive provider and a dangerous state-mutating listener (two files
# so cross-file analysis resolves the provider).
PROVIDER = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class TeamListNotifier extends _$TeamListNotifier {
  @override
  TeamListState build() {
    final async = ref.watch(allTeamsStreamProvider);
    return TeamListState(items: async.value ?? const []);
  }
}
"""

LISTENER = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

@riverpod
class GameEditNotifier extends _$GameEditNotifier {
  @override
  GameEditState build(String gameKey) {
    ref.listen(teamListProvider, _onTeamListChanged);
    return const GameEditState();
  }
  void _onTeamListChanged(TeamListState? prev, TeamListState next) {
    state = state.copyWith(availableTeams: next.items);
  }
}
"""


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "riverpod_3_scanner", *args],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )


def _dangerous_dir(tmp_path):
    (tmp_path / "provider.dart").write_text(PROVIDER)
    (tmp_path / "listener.dart").write_text(LISTENER)
    return tmp_path


# ── Helper unit tests ────────────────────────────────────────────────────────

def test_baseline_key_is_root_relative(tmp_path):
    v = Violation(
        file_path=str(tmp_path / "sub" / "f.dart"),
        class_name="X",
        violation_type=ViolationType.BUILD_LISTEN_SYNC_STATE_MUTATION,
        line_number=42,
        context="",
        code_snippet="",
        fix_instructions="",
    )
    assert _baseline_key(v, tmp_path) == "sub/f.dart:42:build_listen_sync_state_mutation"


def test_write_then_load_baseline_roundtrip(tmp_path):
    keys = ["b.dart:2:t", "a.dart:1:t", "a.dart:1:t"]  # unsorted + duplicate
    path = tmp_path / "base.json"
    _write_baseline(path, keys)
    assert json.loads(path.read_text()) == ["a.dart:1:t", "b.dart:2:t"]  # sorted+unique
    assert _load_baseline(path) == {"a.dart:1:t", "b.dart:2:t"}


# ── End-to-end CLI tests ─────────────────────────────────────────────────────

def test_write_baseline_captures_current_violations_and_exits_zero(tmp_path):
    d = _dangerous_dir(tmp_path)
    base = tmp_path / "base.json"
    r = _run_cli(str(d), "--write-baseline", str(base))
    assert r.returncode == 0, r.stdout + r.stderr
    entries = json.loads(base.read_text())
    assert len(entries) == 1
    assert entries[0].endswith("build_listen_sync_state_mutation")


def test_baseline_suppresses_accepted_violation(tmp_path):
    d = _dangerous_dir(tmp_path)
    base = tmp_path / "base.json"
    _run_cli(str(d), "--write-baseline", str(base))
    r = _run_cli(str(d), "--baseline", str(base))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "baselined violation(s) suppressed" in r.stdout


def test_empty_baseline_fails_on_the_violation(tmp_path):
    d = _dangerous_dir(tmp_path)
    empty = tmp_path / "empty.json"
    empty.write_text("[]")
    r = _run_cli(str(d), "--baseline", str(empty))
    assert r.returncode == 1
    assert "BUILD LISTEN SYNC STATE MUTATION" in r.stdout


def test_stale_baseline_entry_is_reported_but_not_a_failure(tmp_path):
    d = _dangerous_dir(tmp_path)
    base = tmp_path / "base.json"
    _run_cli(str(d), "--write-baseline", str(base))
    entries = json.loads(base.read_text())
    entries.append("gone/file.dart:999:build_listen_sync_state_mutation")
    base.write_text(json.dumps(entries))
    r = _run_cli(str(d), "--baseline", str(base))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STALE baseline" in r.stdout
