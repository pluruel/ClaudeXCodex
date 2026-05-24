"""Detect interrupted runs and decide where to pick up."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from agent_loop.run_state import RunState

Action = Literal[
    "plan_round",
    "dispatch",
    "advance_to_review",
    "write_review",
    "skip_review",
    "write_memo",
    "branch_decision",
    "advance_phase",
    "user_confirm",
    "finalize",
]


@dataclass
class ResumePlan:
    action: Action
    notes: str = ""
    options: list[str] = field(default_factory=list)


def find_active_run(repo: Path) -> Optional[Path]:
    runs_root = repo / ".agent-loop" / "runs"
    if not runs_root.exists():
        return None
    candidates: list[Path] = []
    for d in runs_root.iterdir():
        if (d / "state.json").exists():
            try:
                rs = RunState.load(d / "state.json")
                if rs.status == "in_progress":
                    candidates.append(d)
            except Exception:
                continue
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p.name)[-1]


def determine_resume_action(rs: RunState, *, run_dir: Path) -> ResumePlan:
    if rs.phase_advance_pending:
        return ResumePlan(
            action="advance_phase",
            notes="PHASE_COMPLETE received; advance-phase has not yet run",
        )
    if not rs.rounds:
        return ResumePlan(action="plan_round", notes="no rounds started yet")
    last = rs.rounds[-1]
    round_dir = run_dir / "rounds" / f"{last.n:02d}"

    if last.phase == "planned":
        return ResumePlan(action="plan_round", notes="prompt not yet rendered")
    if last.phase == "init":
        return ResumePlan(action="dispatch", notes="prompt rendered, never dispatched")
    if last.phase == "dispatched":
        progress_md = round_dir / "progress.md"
        if progress_md.exists() and "[done]" in progress_md.read_text(encoding="utf-8"):
            # Check commit_on_approve to route correctly
            gate_path = round_dir / "round_plan.json"
            if not gate_path.exists():
                gate_path = round_dir / "round-plan.json"
            if not gate_path.exists():
                return ResumePlan(
                    action="user_confirm",
                    notes="dispatched with completed progress but no readable round plan; cannot determine commit_on_approve",
                    options=["review-round", "memo-note", "abandon-round"],
                )
            try:
                import json as _json
                rp = _json.loads(gate_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return ResumePlan(
                    action="user_confirm",
                    notes="dispatched with completed progress but unreadable round plan",
                    options=["review-round", "memo-note", "abandon-round"],
                )
            if not rp.get("commit_on_approve", False):
                return ResumePlan(
                    action="skip_review",
                    notes="commit_on_approve=false; use memo-note",
                )
            return ResumePlan(
                action="advance_to_review",
                notes="progress.md has completed entries; treating as worker done",
            )
        return ResumePlan(
            action="user_confirm",
            notes="dispatch interrupted without completed worker progress",
            options=["redispatch", "abandon-round", "abort-run"],
        )
    if last.phase == "claude_completed":
        round_plan_path = run_dir / "rounds" / f"{last.n:02d}" / "round_plan.json"
        if not round_plan_path.exists():
            round_plan_path = run_dir / "rounds" / f"{last.n:02d}" / "round-plan.json"
        if not round_plan_path.exists():
            return ResumePlan(
                action="user_confirm",
                notes="claude_completed but no readable round plan; cannot determine commit_on_approve",
                options=["review-round", "memo-note", "abandon-round"],
            )
        try:
            import json as _json
            rp_data = _json.loads(round_plan_path.read_text(encoding="utf-8"))
            commit_on_approve = bool(rp_data.get("commit_on_approve", True))
        except Exception:
            return ResumePlan(
                action="user_confirm",
                notes="claude_completed but no readable round plan; cannot determine commit_on_approve",
                options=["review-round", "memo-note", "abandon-round"],
            )
        if not commit_on_approve:
            return ResumePlan(action="skip_review", notes="commit_on_approve=false; use memo-note")
        return ResumePlan(action="write_review", notes="ready for Codex review")
    if last.phase == "skipped":
        return ResumePlan(action="plan_round", notes="review skipped (non-commit round); starting next round")
    if last.phase == "reviewed":
        return ResumePlan(action="write_memo", notes="review written, memo pending")
    if last.phase == "memo_written":
        return ResumePlan(action="branch_decision", notes="evaluate decision")
    if last.phase == "completed":
        return ResumePlan(action="finalize", notes="last round completed")
    return ResumePlan(action="user_confirm", notes=f"unknown phase {last.phase}")
