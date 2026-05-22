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
