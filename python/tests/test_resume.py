from __future__ import annotations

from pathlib import Path

from agent_loop.resume import (
    ResumePlan,
    determine_resume_action,
    find_active_run,
)
from agent_loop.run_state import RunState, RoundEntry


def _write_state(run_dir: Path, rs: RunState) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    rs.save(run_dir / "state.json")


def test_find_active_run_returns_most_recent(tmp_repo: Path) -> None:
    runs_root = tmp_repo / ".agent-loop" / "runs"
    a = runs_root / "2026-05-20-old"
    b = runs_root / "2026-05-22-new"
    _write_state(a, RunState.new(run_id="old", goal_path="g", plan_path="p"))
    _write_state(b, RunState.new(run_id="new", goal_path="g", plan_path="p"))
    assert find_active_run(tmp_repo).name == "2026-05-22-new"


def test_resume_action_from_dispatched_with_result(tmp_path: Path) -> None:
    import json

    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "dispatched")
    round_dir = tmp_path / "rounds" / "01"
    round_dir.mkdir(parents=True)
    (round_dir / "progress.md").write_text("[done] r1-i1 implementation: task completed\n")
    (round_dir / "round_plan.json").write_text(
        json.dumps({"commit_on_approve": True, "commit_message": "feat: test"}),
        encoding="utf-8",
    )
    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "advance_to_review"
    assert plan.notes  # explanatory text included


def test_resume_action_from_dispatched_without_result_requires_confirm(tmp_path: Path) -> None:
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "dispatched")
    (tmp_path / "rounds" / "01").mkdir(parents=True)
    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "user_confirm"
    assert "redispatch" in plan.options
    assert "abandon-round" in plan.options
    assert "abort-run" in plan.options


def test_resume_action_from_init(tmp_path: Path) -> None:
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "dispatch"


def test_resume_action_from_reviewed(tmp_path: Path) -> None:
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "reviewed")
    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "write_memo"


def test_determine_resume_action_advance_phase_when_pending(tmp_path: Path) -> None:
    """phase_advance_pending=True must return advance_phase, even when last round is completed."""
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.total_phases = 2
    rs.current_phase = 1
    rs.phase_advance_pending = True
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "completed")
    rs.set_round_decision(1, "PHASE_COMPLETE")
    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "advance_phase"


def test_resume_user_confirm_missing_plan_after_claude_completed(tmp_path: Path) -> None:
    """When last phase is claude_completed but NO round plan file exists (neither
    round_plan.json nor round-plan.json), determine_resume_action must return
    user_confirm so an unattended run does not silently attempt a review without
    knowing whether commit_on_approve is True or False."""
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "claude_completed")

    # Deliberately create the round dir with NO plan file
    round_dir = tmp_path / "rounds" / "01"
    round_dir.mkdir(parents=True)
    # (no round_plan.json or round-plan.json written)

    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "user_confirm"
    assert "no readable round plan" in plan.notes


def test_resume_skip_review_after_claude_completed_non_commit(tmp_path: Path) -> None:
    """When last phase is claude_completed and round_plan.json has commit_on_approve=False,
    determine_resume_action must return skip_review (non-commit round path)."""
    import json

    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "claude_completed")

    round_dir = tmp_path / "rounds" / "01"
    round_dir.mkdir(parents=True)
    (round_dir / "round_plan.json").write_text(
        json.dumps({"commit_on_approve": False, "commit_message": ""}),
        encoding="utf-8",
    )

    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "skip_review"


def test_resume_write_review_after_claude_completed_commit(tmp_path: Path) -> None:
    """When last phase is claude_completed and round_plan.json has commit_on_approve=True,
    determine_resume_action must return write_review (real Codex review required)."""
    import json

    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "claude_completed")

    round_dir = tmp_path / "rounds" / "01"
    round_dir.mkdir(parents=True)
    (round_dir / "round_plan.json").write_text(
        json.dumps({"commit_on_approve": True, "commit_message": "feat: test"}),
        encoding="utf-8",
    )

    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "write_review"


def test_resume_dispatched_non_commit_returns_skip_review(tmp_path: Path) -> None:
    """When dispatched phase has completed progress and commit_on_approve=False,
    determine_resume_action must return skip_review."""
    import json

    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "dispatched")

    round_dir = tmp_path / "rounds" / "01"
    round_dir.mkdir(parents=True)
    (round_dir / "progress.md").write_text("[done] r1-i1 task complete\n", encoding="utf-8")
    (round_dir / "round_plan.json").write_text(
        json.dumps({"commit_on_approve": False}),
        encoding="utf-8",
    )

    plan = determine_resume_action(rs, run_dir=tmp_path)
    assert plan.action == "skip_review"
