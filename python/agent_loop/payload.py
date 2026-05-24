"""Build the review-payload.json that Codex consumes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_loop.diff_capture import DiffStats
from agent_loop.shared_io import SharedDelta


def build_review_payload(
    *,
    out_path: Path | None = None,
    round_n: int,
    goal_summary: str,
    stats: DiffStats,
    shared_delta: SharedDelta,
    artifact_paths: dict[str, str],
    safety_flags: list[str],
    verification_outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "round": round_n,
        "goal_summary": goal_summary,
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
        # B3: verification subtask outcomes parsed from progress.md.
        "verification_outcomes": verification_outcomes if verification_outcomes is not None else [],
    }
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
