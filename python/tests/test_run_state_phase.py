"""Tests for RunState phase fields, advance method, serialize round-trip, and backward compat."""
from __future__ import annotations

import json
import typing
from pathlib import Path

import pytest

from agent_loop.run_state import Decision, RunState, RoundEntry


def test_run_state_has_current_phase_default() -> None:
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    assert rs.current_phase == 1


def test_run_state_has_total_phases_default() -> None:
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    assert rs.total_phases == 1


def test_run_state_has_phase_advance_pending_default() -> None:
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    assert rs.phase_advance_pending is False


def test_run_state_advance_current_phase_increments() -> None:
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.total_phases = 3
    rs.current_phase = 1
    rs.phase_advance_pending = True
    rs.advance_current_phase()
    assert rs.current_phase == 2
    assert rs.phase_advance_pending is False


def test_run_state_advance_current_phase_clamps_at_total() -> None:
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.total_phases = 2
    rs.current_phase = 2
    rs.advance_current_phase()
    assert rs.current_phase == 2


def test_run_state_advance_current_phase_clears_pending() -> None:
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.total_phases = 3
    rs.current_phase = 1
    rs.phase_advance_pending = True
    rs.advance_current_phase()
    assert rs.phase_advance_pending is False


def test_run_state_serialize_deserialize_phase_fields(tmp_path: Path) -> None:
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.total_phases = 3
    rs.current_phase = 2
    rs.phase_advance_pending = True
    state_path = tmp_path / "state.json"
    rs.save(state_path)
    loaded = RunState.load(state_path)
    assert loaded.total_phases == 3
    assert loaded.current_phase == 2
    assert loaded.phase_advance_pending is True


def test_run_state_load_missing_phase_fields_defaults(tmp_path: Path) -> None:
    """Legacy state.json without phase keys still loads with defaults."""
    legacy = {
        "run_id": "old-run",
        "goal_path": "goal.md",
        "plan_path": "plan.md",
        "current_round": 0,
        "status": "in_progress",
        "rounds": [],
        "safety_flags": [],
        "last_heartbeat": None,
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(legacy), encoding="utf-8")
    rs = RunState.load(state_path)
    assert rs.current_phase == 1
    assert rs.total_phases == 1
    assert rs.phase_advance_pending is False


def test_decision_literal_contains_phase_complete() -> None:
    args = typing.get_args(Decision)
    assert "PHASE_COMPLETE" in args
    assert "STOP_FOR_USER" not in args
