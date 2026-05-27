"""Tests for phase-commit subcommand and phase-review enforcement."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_loop.cli import main
from agent_loop.run_state import RunState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _setup_git_repo(tmp_path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    _git(["init"], tmp_path)
    _git(["config", "user.email", "test@test.com"], tmp_path)
    _git(["config", "user.name", "Test User"], tmp_path)
    # Create an initial file and commit
    src = tmp_path / "src.py"
    src.write_text("# initial\n", encoding="utf-8")
    _git(["add", "src.py"], tmp_path)
    _git(["commit", "-m", "initial commit"], tmp_path)


def _setup_run(tmp_path: Path, run_id: str = "test-run-01") -> Path:
    """Create minimal run directory structure."""
    run_dir = tmp_path / ".agent-loop" / "runs" / run_id
    (run_dir / "rounds").mkdir(parents=True, exist_ok=True)
    (run_dir / "shared").mkdir(parents=True, exist_ok=True)
    (run_dir / "phases").mkdir(parents=True, exist_ok=True)
    (run_dir / "goal.md").write_text("test goal\n", encoding="utf-8")
    (run_dir / "plan.md").write_text("# Plan\n\n## Tasks\n1. [ ] do something\n", encoding="utf-8")
    (run_dir / "memo.md").write_text("# Round Memos\n\n", encoding="utf-8")
    phases_index = [
        {"phase_n": 1, "title": "Foundation", "objective": "Set up base.", "doc_path": "phases/phase-01.md"},
    ]
    (run_dir / "phases.json").write_text(json.dumps(phases_index, indent=2), encoding="utf-8")
    (run_dir / "phases" / "phase-01.md").write_text(
        "# Phase 1: Foundation\n\n## Objective\nSet up base.\n",
        encoding="utf-8",
    )
    rs = RunState.new(run_id=run_id, goal_path="goal.md", plan_path="plan.md")
    rs.save(run_dir / "state.json")
    return run_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_phase_commit_records_sha(tmp_path, capsys):
    """phase-commit creates a commit, emits JSON, and records sha in state.json."""
    _setup_git_repo(tmp_path)
    run_id = "test-run-01"
    run_dir = _setup_run(tmp_path, run_id)

    # Create a new file so there's something to stage
    new_file = tmp_path / "feature.py"
    new_file.write_text("def hello(): pass\n", encoding="utf-8")

    rc = main(["phase-commit", "--repo", str(tmp_path), "--run", run_id, "--phase", "1"])
    assert rc == 0

    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["phase"] == 1
    assert out["message"] == "phase 1: Foundation"
    assert out["commit_sha"]  # non-empty

    # Verify git HEAD is that sha
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out["commit_sha"] == git_sha

    # Verify state.json was updated
    rs = RunState.load(run_dir / "state.json")
    assert rs.phase_commits.get("1") == git_sha


def test_phase_commit_empty_staging_errors(tmp_path, capsys):
    """phase-commit fails with the right message when nothing is staged."""
    _setup_git_repo(tmp_path)
    run_id = "test-run-01"
    _setup_run(tmp_path, run_id)

    # No new/modified files — nothing to stage
    rc = main(["phase-commit", "--repo", str(tmp_path), "--run", run_id, "--phase", "1"])
    assert rc == 1

    captured = capsys.readouterr()
    assert captured.err.strip() == "phase-commit: nothing staged to commit"


def test_phase_review_refuses_without_commit(tmp_path, capsys, monkeypatch):
    """phase-review returns 1 before calling Codex when phase_commits is missing."""
    _setup_git_repo(tmp_path)
    run_id = "test-run-01"
    _setup_run(tmp_path, run_id)

    call_count = {"n": 0}

    def _stub_call_codex(prompt, **kwargs):
        call_count["n"] += 1
        from agent_loop.codex_client import CodexResult
        return CodexResult(final_text="# Phase Review -- Phase 1\n\n## Decision\nAPPROVE\n")

    monkeypatch.setattr("agent_loop.codex_client.call_codex", _stub_call_codex)

    rc = main(["phase-review", "--repo", str(tmp_path), "--run", run_id, "--phase", "1"])
    assert rc == 1

    captured = capsys.readouterr()
    assert captured.err.strip() == "phase-commit not recorded for phase 1"
    # Codex must NOT have been called
    assert call_count["n"] == 0


def test_phase_review_proceeds_after_commit(tmp_path, capsys, monkeypatch):
    """phase-review exits 0 with expected JSON when phase_commit is recorded."""
    _setup_git_repo(tmp_path)
    run_id = "test-run-01"
    run_dir = _setup_run(tmp_path, run_id)

    # Create a file and do a phase-commit first
    (tmp_path / "feature.py").write_text("def hello(): pass\n", encoding="utf-8")
    rc_commit = main(["phase-commit", "--repo", str(tmp_path), "--run", run_id, "--phase", "1"])
    assert rc_commit == 0
    capsys.readouterr()  # discard phase-commit output

    # Stub Codex for phase-review
    def _stub_call_codex(prompt, **kwargs):
        from agent_loop.codex_client import CodexResult
        return CodexResult(final_text=(
            "# Phase Review -- Phase 1\n\n"
            "## Decision\nAPPROVE\n\n"
            "## Goal Alignment\nPhase objective achieved.\n\n"
            "## Findings\n- (none)\n\n"
            "## Verification\n- Tests: pass -- all passed\n\n"
            "## Risks\n- (none)\n\n"
            "## Carry-Forward For Next Round\n- keep docs updated\n\n"
            "## Final Notes\nLooks good.\n"
        ))

    monkeypatch.setattr("agent_loop.codex_client.call_codex", _stub_call_codex)

    rc = main(["phase-review", "--repo", str(tmp_path), "--run", run_id, "--phase", "1"])
    assert rc == 0

    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["decision"] == "APPROVE"
    assert out["phase"] == 1


def test_legacy_state_loads_without_phase_commits(tmp_path):
    """RunState.load works on state.json missing the phase_commits key."""
    run_dir = tmp_path / ".agent-loop" / "runs" / "legacy-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    # Write a legacy state.json without phase_commits
    legacy_state = {
        "run_id": "legacy-run",
        "goal_path": "goal.md",
        "plan_path": "plan.md",
        "current_round": 0,
        "current_phase": 1,
        "total_phases": 1,
        "phase_advance_pending": False,
        "status": "in_progress",
        "rounds": [],
        "safety_flags": [],
        "last_heartbeat": None,
        "phase_reviews": [],
        # NOTE: no "phase_commits" key — legacy file
    }
    (run_dir / "state.json").write_text(json.dumps(legacy_state, indent=2), encoding="utf-8")

    rs = RunState.load(run_dir / "state.json")
    assert rs.phase_commits == {}
