from __future__ import annotations

import json
from pathlib import Path

from agent_loop.diff_capture import DiffStats
from agent_loop.payload import build_review_payload
from agent_loop.result_parser import ClaudeResult
from agent_loop.shared_io import SharedDelta


def test_build_review_payload_writes_and_returns(tmp_path: Path) -> None:
    out = tmp_path / "review-payload.json"
    result = ClaudeResult(
        summary="JWT verify added",
        changed_files=["src/auth/middleware.py"],
        commands_run=["pytest tests/auth -x"],
        test_outcome="pass",
        decision_hint="completed",
        open_questions=["refresh tokens?"],
        requested_reading=["src/sessions/store.py"],
        requires_user=False,
    )
    stats = DiffStats(
        files_changed=1,
        insertions=62,
        deletions=4,
        by_file=[{"path": "src/auth/middleware.py", "ins": 62, "del": 4, "sensitive": False}],
        sensitive_hits=[],
    )
    delta = SharedDelta(knowledge="- fact A\n", decisions="", open_questions="")
    payload = build_review_payload(
        out_path=out,
        round_n=2,
        goal_summary="Add JWT auth",
        result=result,
        stats=stats,
        shared_delta=delta,
        artifact_paths={
            "result": ".agent-loop/runs/x/rounds/02/claude-result.md",
            "diff": ".agent-loop/runs/x/rounds/02/diff.patch",
            "test_log": ".agent-loop/runs/x/rounds/02/test-log.txt",
            "messages": ".agent-loop/runs/x/rounds/02/claude-messages.jsonl",
        },
        safety_flags=["diff_too_many_lines"],
    )

    assert payload["round"] == 2
    assert payload["goal_summary"] == "Add JWT auth"
    assert payload["claude_decision_hint"] == "completed"
    assert payload["result_summary"]["changed_files"] == ["src/auth/middleware.py"]
    assert payload["diff_summary"]["files_changed"] == 1
    assert payload["safety_flags"] == ["diff_too_many_lines"]
    assert "shared_delta" in payload

    on_disk = json.loads(out.read_text())
    assert on_disk == payload


def test_payload_under_size_limit(tmp_path: Path) -> None:
    out = tmp_path / "p.json"
    payload = build_review_payload(
        out_path=out,
        round_n=1,
        goal_summary="g",
        result=ClaudeResult(summary="s"),
        stats=DiffStats(files_changed=0, insertions=0, deletions=0),
        shared_delta=SharedDelta(),
        artifact_paths={},
        safety_flags=[],
    )
    raw = out.read_bytes()
    assert len(raw) < 2048
