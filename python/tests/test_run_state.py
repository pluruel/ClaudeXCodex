from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_loop.run_state import (
    PHASES,
    RoundEntry,
    RunState,
    next_phase,
)


def test_phases_in_order() -> None:
    assert PHASES == [
        "planned",
        "init",
        "dispatched",
        "claude_completed",
        "reviewed",
        "memo_written",
        "completed",
        "skipped",
    ]


def test_next_phase_advances() -> None:
    assert next_phase("planned") == "init"
    assert next_phase("dispatched") == "claude_completed"
    assert next_phase("memo_written") == "completed"


def test_next_phase_at_terminal_returns_completed() -> None:
    assert next_phase("completed") == "completed"


def test_runstate_roundtrip(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    rs = RunState(
        run_id="2026-05-22-x",
        goal_path="goal.md",
        plan_path="plan.md",
        current_round=1,
        status="in_progress",
        rounds=[
            RoundEntry(n=1, phase="dispatched", decision=None,
                       memo_lines=None, started_at="2026-05-22T09:00:00",
                       ended_at=None)
        ],
        safety_flags=[],
        last_heartbeat="2026-05-22T09:05:00",
    )
    rs.save(state_path)
    loaded = RunState.load(state_path)
    assert loaded == rs


def test_runstate_advance_round_phase(tmp_path: Path) -> None:
    rs = RunState.new(run_id="r1", goal_path="goal.md", plan_path="plan.md")
    rs.start_round(n=1, started_at="t0")
    assert rs.rounds[-1].phase == "init"
    rs.advance_round_phase(1)
    assert rs.rounds[-1].phase == "dispatched"
    rs.advance_round_phase(1)
    assert rs.rounds[-1].phase == "claude_completed"


def test_runstate_set_decision(tmp_path: Path) -> None:
    rs = RunState.new(run_id="r1", goal_path="goal.md", plan_path="plan.md")
    rs.start_round(n=1, started_at="t0")
    rs.set_round_decision(1, "NEEDS_CHANGES")
    assert rs.rounds[-1].decision == "NEEDS_CHANGES"


def test_runstate_heartbeat(tmp_path: Path) -> None:
    rs = RunState.new(run_id="r1", goal_path="goal.md", plan_path="plan.md")
    rs.touch_heartbeat("t1")
    assert rs.last_heartbeat == "t1"


def test_phase_reviews_default_empty():
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    assert rs.phase_reviews == []


def test_add_phase_review_appends():
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.add_phase_review(phase_n=1, decision="APPROVE", sha="abc123", review_path="phases/phase-01-review.md")
    assert len(rs.phase_reviews) == 1
    assert rs.phase_reviews[0] == {
        "phase_n": 1, "decision": "APPROVE", "sha": "abc123",
        "review_path": "phases/phase-01-review.md",
    }


def test_consecutive_phase_needs_changes_counts_tail():
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.add_phase_review(phase_n=1, decision="NEEDS_CHANGES", sha="a", review_path="r1")
    rs.add_phase_review(phase_n=1, decision="NEEDS_CHANGES", sha="b", review_path="r2")
    assert rs.consecutive_phase_needs_changes(1) == 2


def test_consecutive_phase_needs_changes_resets_on_approve():
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.add_phase_review(phase_n=1, decision="NEEDS_CHANGES", sha="a", review_path="r1")
    rs.add_phase_review(phase_n=1, decision="APPROVE", sha="b", review_path="r2")
    rs.add_phase_review(phase_n=1, decision="NEEDS_CHANGES", sha="c", review_path="r3")
    assert rs.consecutive_phase_needs_changes(1) == 1


def test_phase_reviews_round_trip(tmp_path):
    path = tmp_path / "state.json"
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.add_phase_review(phase_n=2, decision="NEEDS_CHANGES", sha="xyz", review_path="phases/phase-02-review.md")
    rs.save(path)
    rs2 = RunState.load(path)
    assert rs2.phase_reviews == [{"phase_n": 2, "decision": "NEEDS_CHANGES", "sha": "xyz", "review_path": "phases/phase-02-review.md"}]


def test_phase_reviews_load_backward_compat(tmp_path):
    """Old state.json without phase_reviews field loads without error."""
    path = tmp_path / "state.json"
    path.write_text('{"run_id":"r","goal_path":"g","plan_path":"p","rounds":[]}', encoding="utf-8")
    rs = RunState.load(path)
    assert rs.phase_reviews == []
