"""Tests for memo-note command and review-gate skip logic."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_loop.resume import determine_resume_action
from agent_loop.run_state import RunState


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "agent_loop", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _make_run(tmp_repo: Path, round_n: int = 1, commit_on_approve: bool = False) -> tuple[Path, str]:
    """Bootstrap a minimal run with one round at claude_completed phase."""
    r = _run(["init-run", "--goal", "test goal", "--slug", "gate-test"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    run_id = json.loads(r.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    state_p = run_dir / "state.json"
    rs = RunState.load(state_p)
    rs.start_round(n=round_n, started_at="2026-01-01T00:00:00")
    rs.set_round_phase(round_n, "claude_completed")
    rs.save(state_p)

    rd = run_dir / "rounds" / f"{round_n:02d}"
    rd.mkdir(parents=True, exist_ok=True)

    round_plan = {
        "round": round_n,
        "worker_model": "sonnet",
        "worker_model_reason": "test",
        "reasoning_effort": "medium",
        "subtasks": [],
        "task_description": "",
        "execution_plan_bullets": [],
        "acceptance_criteria": [],
        "carry_forward": "",
        "commit_on_approve": commit_on_approve,
        "commit_message": "" if not commit_on_approve else "feat: test",
        "parse_failed": False,
    }
    (rd / "round_plan.json").write_text(json.dumps(round_plan, indent=2), encoding="utf-8")

    return run_dir, run_id


def test_review_gate_skips_when_commit_on_approve_false(tmp_repo: Path) -> None:
    """When commit_on_approve=False, memo-note command should succeed and emit phase=skipped."""
    run_dir, run_id = _make_run(tmp_repo, round_n=1, commit_on_approve=False)

    r = _run(["memo-note", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["phase"] == "skipped"
    assert out["round"] == 1


def test_memo_note_sets_skipped_phase(tmp_repo: Path) -> None:
    """memo-note must flip phase to 'skipped' in state.json."""
    run_dir, run_id = _make_run(tmp_repo, round_n=1, commit_on_approve=False)
    state_p = run_dir / "state.json"

    r = _run(["memo-note", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr

    rs = RunState.load(state_p)
    assert rs.rounds[-1].phase == "skipped"
    assert rs.rounds[-1].ended_at is not None


def test_memo_note_appends_to_memo(tmp_repo: Path) -> None:
    """memo-note must append a CONTINUE block to memo.md."""
    run_dir, run_id = _make_run(tmp_repo, round_n=1, commit_on_approve=False)

    r = _run(["memo-note", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr

    memo = (run_dir / "memo.md").read_text(encoding="utf-8")
    assert "## Round 1 - CONTINUE" in memo
    assert "review deferred" in memo

    out = json.loads(r.stdout)
    assert out["memo_appended"] is True


def test_memo_note_idempotent(tmp_repo: Path) -> None:
    """Calling memo-note twice for the same round should not duplicate the memo block."""
    run_dir, run_id = _make_run(tmp_repo, round_n=1, commit_on_approve=False)

    _run(["memo-note", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    r2 = _run(["memo-note", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r2.returncode == 0, r2.stderr
    out2 = json.loads(r2.stdout)
    assert out2["memo_appended"] is False

    memo = (run_dir / "memo.md").read_text(encoding="utf-8")
    assert memo.count("## Round 1 - CONTINUE") == 1


def test_resume_claude_completed_always_write_review(tmp_path: Path) -> None:
    """When last phase is claude_completed, determine_resume_action always returns write_review
    regardless of commit_on_approve — the gate has been removed."""
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "claude_completed")

    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "write_review"


def test_resume_write_review_when_commit_on_approve_true(tmp_path: Path) -> None:
    """When commit_on_approve=True, determine_resume_action returns write_review as before."""
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "claude_completed")

    round_dir = tmp_path / "rounds" / "01"
    round_dir.mkdir(parents=True)
    round_plan = {
        "round": 1,
        "commit_on_approve": True,
        "commit_message": "feat: test",
    }
    (round_dir / "round_plan.json").write_text(json.dumps(round_plan), encoding="utf-8")

    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "write_review"


def test_resume_skipped_phase_returns_plan_round(tmp_path: Path) -> None:
    """When last phase is 'skipped', determine_resume_action returns plan_round."""
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "skipped")

    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "plan_round"
    assert "memo" in plan.notes


def test_review_round_proceeds_regardless_of_commit_on_approve(tmp_repo: Path) -> None:
    """review-round must always proceed (rc=0 or codex-call failure is acceptable)
    regardless of the commit_on_approve field — the gate has been removed."""
    run_dir, run_id = _make_run(tmp_repo, round_n=1, commit_on_approve=False)

    r = _run(["review-round", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    # Without a codex binary available in tests, review-round may fail with rc=1 due to
    # codex invocation error, but must NOT fail with commit_on_approve gating message.
    assert "commit_on_approve=false" not in r.stderr


def test_memo_note_succeeds_regardless_of_commit_on_approve(tmp_repo: Path) -> None:
    """memo-note must succeed (rc=0) regardless of commit_on_approve field — the gate is removed."""
    run_dir, run_id = _make_run(tmp_repo, round_n=1, commit_on_approve=True)

    r = _run(["memo-note", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["phase"] == "skipped"


def test_skip_metadata_in_state(tmp_repo: Path) -> None:
    """After memo-note, state.json must have skip_reason set and phase=skipped."""
    run_dir, run_id = _make_run(tmp_repo, round_n=1, commit_on_approve=False)
    state_p = run_dir / "state.json"

    r = _run(["memo-note", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr

    rs = RunState.load(state_p)
    entry = rs._round(1)
    assert entry.skip_reason == "supervisor-directed skip"
    assert entry.phase == "skipped"


def _make_run_hyphenated_plan(tmp_repo: Path, round_n: int = 1, commit_on_approve: bool = False) -> tuple[Path, str]:
    """Bootstrap a minimal run with only round-plan.json (hyphenated filename, no underscore version)."""
    r = _run(["init-run", "--goal", "test goal", "--slug", "gate-hyph-test"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    run_id = json.loads(r.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    state_p = run_dir / "state.json"
    rs = RunState.load(state_p)
    rs.start_round(n=round_n, started_at="2026-01-01T00:00:00")
    rs.set_round_phase(round_n, "claude_completed")
    rs.save(state_p)

    rd = run_dir / "rounds" / f"{round_n:02d}"
    rd.mkdir(parents=True, exist_ok=True)

    round_plan = {
        "round": round_n,
        "worker_model": "sonnet",
        "worker_model_reason": "test",
        "reasoning_effort": "medium",
        "subtasks": [],
        "task_description": "",
        "execution_plan_bullets": [],
        "acceptance_criteria": [],
        "carry_forward": "",
        "commit_on_approve": commit_on_approve,
        "commit_message": "" if not commit_on_approve else "feat: test",
        "parse_failed": False,
    }
    # Write only the hyphenated filename (round-plan.json), not round_plan.json
    (rd / "round-plan.json").write_text(json.dumps(round_plan, indent=2), encoding="utf-8")

    return run_dir, run_id


def test_review_round_proceeds_with_hyphenated_plan(tmp_repo: Path) -> None:
    """review-round must proceed (not gate on commit_on_approve) when only round-plan.json (hyphenated) exists."""
    run_dir, run_id = _make_run_hyphenated_plan(tmp_repo, round_n=1, commit_on_approve=False)

    r = _run(["review-round", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    # The gate is removed; review-round must not refuse with commit_on_approve message.
    assert "commit_on_approve=false" not in r.stderr


def test_memo_note_hyphenated_plan(tmp_repo: Path) -> None:
    """memo-note must succeed (rc=0) and emit phase=skipped when only round-plan.json (hyphenated) exists with commit_on_approve=false."""
    run_dir, run_id = _make_run_hyphenated_plan(tmp_repo, round_n=1, commit_on_approve=False)

    r = _run(["memo-note", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["phase"] == "skipped"


def test_review_round_refuses_missing_plan(tmp_repo: Path) -> None:
    """review-round must refuse (rc=1) with 'no round plan found' when neither round_plan.json nor round-plan.json exists."""
    r = _run(["init-run", "--goal", "test goal", "--slug", "rr-noplan-test"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    run_id = json.loads(r.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    state_p = run_dir / "state.json"
    rs = RunState.load(state_p)
    rs.start_round(n=1, started_at="2026-01-01T00:00:00")
    rs.set_round_phase(1, "claude_completed")
    rs.save(state_p)

    rd = run_dir / "rounds" / "01"
    rd.mkdir(parents=True, exist_ok=True)
    # Deliberately write NO round plan file

    r = _run(["review-round", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode == 1
    assert "no round plan found" in r.stderr


def test_memo_note_fails_closed_missing_plan(tmp_repo: Path) -> None:
    """memo-note must refuse (rc=1) with descriptive error when no round plan file exists at all."""
    r = _run(["init-run", "--goal", "test goal", "--slug", "gate-noplan-test"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    run_id = json.loads(r.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    state_p = run_dir / "state.json"
    rs = RunState.load(state_p)
    rs.start_round(n=1, started_at="2026-01-01T00:00:00")
    rs.set_round_phase(1, "claude_completed")
    rs.save(state_p)

    rd = run_dir / "rounds" / "01"
    rd.mkdir(parents=True, exist_ok=True)
    # Deliberately write NO round plan file

    r = _run(["memo-note", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode == 1
    assert "no round_plan.json or round-plan.json found" in r.stderr
