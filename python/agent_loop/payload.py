"""Build the review-payload.json that Codex consumes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_loop.diff_capture import DiffStats
from agent_loop.result_parser import ClaudeResult
from agent_loop.shared_io import SharedDelta


def build_review_payload(
    *,
    out_path: Path,
    round_n: int,
    goal_summary: str,
    result: ClaudeResult,
    stats: DiffStats,
    shared_delta: SharedDelta,
    artifact_paths: dict[str, str],
    safety_flags: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "round": round_n,
        "goal_summary": goal_summary,
        "claude_decision_hint": result.decision_hint,
        "result_summary": {
            "changed_files": result.changed_files,
            "commands_run": result.commands_run,
            "test_outcome": result.test_outcome,
            "claude_notes": result.summary,
            "open_questions": result.open_questions,
            "requested_reading": result.requested_reading,
            "requires_user": result.requires_user,
        },
        "diff_summary": {
            "files_changed": stats.files_changed,
            "insertions": stats.insertions,
            "deletions": stats.deletions,
            "by_file": stats.by_file,
            "sensitive_hits": stats.sensitive_hits,
        },
        "safety_flags": safety_flags,
        "artifact_paths": artifact_paths,
        "shared_delta": {
            "knowledge": shared_delta.knowledge,
            "decisions": shared_delta.decisions,
            "open_questions": shared_delta.open_questions,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
