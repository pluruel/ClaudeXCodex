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
    "skipped",
]

PHASES: list[Phase] = [
    "planned",
    "init",
    "dispatched",
    "claude_completed",
    "reviewed",
    "memo_written",
    "completed",
    "skipped",
]


def next_phase(current: Phase) -> Phase:
    if current == "completed":
        return "completed"
    idx = PHASES.index(current)
    return PHASES[idx + 1]


Decision = Literal["APPROVE", "NEEDS_CHANGES", "PHASE_COMPLETE"]


@dataclass
class RoundEntry:
    n: int
    phase: Phase = "planned"
    decision: Optional[Decision] = None
    memo_lines: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    skip_reason: Optional[str] = None


@dataclass
class RunState:
    run_id: str
    goal_path: str
    plan_path: str
    current_round: int = 0
    current_phase: int = 1
    total_phases: int = 1
    phase_advance_pending: bool = False
    status: Literal["in_progress", "completed", "aborted"] = "in_progress"
    rounds: list[RoundEntry] = field(default_factory=list)
    safety_flags: list[str] = field(default_factory=list)
    last_heartbeat: Optional[str] = None
    phase_reviews: list[dict] = field(default_factory=list)

    @classmethod
    def new(cls, *, run_id: str, goal_path: str, plan_path: str) -> "RunState":
        return cls(run_id=run_id, goal_path=goal_path, plan_path=plan_path)

    @classmethod
    def load(cls, path: Path) -> "RunState":
        raw = json.loads(path.read_text(encoding="utf-8"))
        round_raws = raw.pop("rounds", [])
        for r in round_raws:
            r.setdefault("skip_reason", None)
            r.pop("skip_commit_on_approve", None)
        rounds = [RoundEntry(**r) for r in round_raws]
        raw.setdefault("current_phase", 1)
        raw.setdefault("total_phases", 1)
        raw.setdefault("phase_advance_pending", False)
        raw.setdefault("phase_reviews", [])
        return cls(rounds=rounds, **raw)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

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

    def advance_current_phase(self) -> None:
        """Increment current_phase (capped at total_phases) and clear pending flag."""
        self.current_phase = min(self.current_phase + 1, self.total_phases)
        self.phase_advance_pending = False

    def add_phase_review(self, *, phase_n: int, decision: str, sha: str, review_path: str) -> None:
        self.phase_reviews.append({
            "phase_n": phase_n,
            "decision": decision,
            "sha": sha,
            "review_path": review_path,
        })

    def consecutive_phase_needs_changes(self, phase_n: int) -> int:
        """Count consecutive NEEDS_CHANGES phase reviews for phase_n at the tail.

        Stops at the first non-matching phase entry once counting has begun,
        treating interleaved phases as streak-breakers.
        """
        count = 0
        for r in reversed(self.phase_reviews):
            if r["phase_n"] != phase_n:
                if count > 0:
                    break
                continue
            if r["decision"] == "NEEDS_CHANGES":
                count += 1
            else:
                break
        return count
