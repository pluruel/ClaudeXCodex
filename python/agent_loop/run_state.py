"""Run state persistence and phase machine."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

Phase = Literal[
    "planned",
    "init",
    "dispatched",
    "claude_completed",
    "reviewed",
    "memo_written",
    "completed",
]

PHASES: list[Phase] = [
    "planned",
    "init",
    "dispatched",
    "claude_completed",
    "reviewed",
    "memo_written",
    "completed",
]


def next_phase(current: Phase) -> Phase:
    if current == "completed":
        return "completed"
    idx = PHASES.index(current)
    return PHASES[idx + 1]


Decision = Literal["APPROVE", "NEEDS_CHANGES", "STOP_FOR_USER"]


@dataclass
class RoundEntry:
    n: int
    phase: Phase = "planned"
    decision: Optional[Decision] = None
    memo_lines: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


@dataclass
class RunState:
    run_id: str
    goal_path: str
    plan_path: str
    current_round: int = 0
    status: Literal["in_progress", "completed", "aborted"] = "in_progress"
    rounds: list[RoundEntry] = field(default_factory=list)
    safety_flags: list[str] = field(default_factory=list)
    last_heartbeat: Optional[str] = None

    @classmethod
    def new(cls, *, run_id: str, goal_path: str, plan_path: str) -> "RunState":
        return cls(run_id=run_id, goal_path=goal_path, plan_path=plan_path)

    @classmethod
    def load(cls, path: Path) -> "RunState":
        raw = json.loads(path.read_text())
        rounds = [RoundEntry(**r) for r in raw.pop("rounds", [])]
        return cls(rounds=rounds, **raw)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        path.write_text(json.dumps(data, indent=2) + "\n")

    def start_round(self, *, n: int, started_at: str) -> None:
        self.current_round = n
        self.rounds.append(RoundEntry(n=n, phase="init", started_at=started_at))

    def _round(self, n: int) -> RoundEntry:
        for r in self.rounds:
            if r.n == n:
                return r
        raise KeyError(f"round {n} not in state")

    def advance_round_phase(self, n: int) -> None:
        r = self._round(n)
        r.phase = next_phase(r.phase)

    def set_round_phase(self, n: int, phase: Phase) -> None:
        self._round(n).phase = phase

    def set_round_decision(self, n: int, decision: Decision) -> None:
        self._round(n).decision = decision

    def touch_heartbeat(self, ts: str) -> None:
        self.last_heartbeat = ts
