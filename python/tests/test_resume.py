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
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_phase(1, "dispatched")
    round_dir = tmp_path / "rounds" / "01"
    round_dir.mkdir(parents=True)
    (round_dir / "claude-result.md").write_text("# Claude Result\n\n## Summary\nok\n")
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
