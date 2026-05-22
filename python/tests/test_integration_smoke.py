"""End-to-end smoke: init-run → init-round → mocked dispatch → finalize.

Uses a small Python script as a stand-in for the Claude SDK to verify the
plumbing (file IO, payload generation, state transitions) works front to back.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(args, cwd):
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False)


def test_e2e_through_finalize(tmp_repo: Path, monkeypatch) -> None:
    # 1. init-run
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "smoke"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # 2. init-round
    prompt = tmp_repo / "p.md"
    prompt.write_text("PROMPT")
    r2 = _run(["init-round", "--run", run_id, "--prompt-file", str(prompt)],
              cwd=tmp_repo)
    assert r2.returncode == 0, r2.stderr

    # 3. Simulate Claude having done its work: write claude-result.md +
    # a small file in the repo so diff is non-empty.
    rd = run_dir / "rounds" / "01"
    (tmp_repo / "src.txt").write_text("hello\n")
    subprocess.run(["git", "add", "src.txt"], cwd=tmp_repo, check=True)
    (rd / "claude-result.md").write_text(
        "# Claude Result\n\n## Summary\nadded src.txt\n\n"
        "## Changed Files\n- src.txt\n\n## Test Outcome\npass\n\n"
        "## Decision Hint\ncompleted\n\n## Requires User\nfalse\n"
    )
    (rd / "test-log.txt").write_text("ok\n")
    # Pretend SDK wrote messages
    (rd / "claude-messages.jsonl").write_text('{"type":"text","content":"ok"}\n')

    # 4. Run a fake dispatch that skips SDK: we directly compute payload via the
    # CLI's payload builder path. Easiest: import and call.
    from agent_loop.diff_capture import capture_baseline, capture_diff, compute_stats
    from agent_loop.payload import build_review_payload
    from agent_loop.result_parser import parse_result
    from agent_loop.shared_io import SharedDelta

    baseline_before = subprocess.run(
        ["git", "rev-parse", "HEAD~0"], cwd=tmp_repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    diff = capture_diff(tmp_repo, baseline_before)
    (rd / "diff.patch").write_text(diff)
    stats = compute_stats(diff)
    result = parse_result(rd / "claude-result.md")
    build_review_payload(
        out_path=rd / "review-payload.json",
        round_n=1,
        goal_summary="smoke",
        result=result,
        stats=stats,
        shared_delta=SharedDelta(),
        artifact_paths={
            "result": str((rd / "claude-result.md").relative_to(tmp_repo)),
            "diff": str((rd / "diff.patch").relative_to(tmp_repo)),
            "test_log": str((rd / "test-log.txt").relative_to(tmp_repo)),
            "messages": str((rd / "claude-messages.jsonl").relative_to(tmp_repo)),
        },
        safety_flags=[],
    )

    # 5. write-review APPROVE
    review = tmp_repo / "rev.md"
    review.write_text("# Codex Review\n\n## Decision\nAPPROVE\n")
    r3 = _run(
        ["write-review", "--run", run_id, "--round", "1",
         "--decision", "APPROVE", "--review-file", str(review)],
        cwd=tmp_repo,
    )
    assert r3.returncode == 0, r3.stderr

    # 6. append-memo
    memo = tmp_repo / "m.md"
    memo.write_text(
        "## Round 1 — APPROVE\n- Goal progress: done\n- Top risks: none\n"
        "- Carry forward: n/a\n- Sensitive: none\n- Diff size: 1 file, +1 -0\n"
    )
    r4 = _run(
        ["append-memo", "--run", run_id, "--round", "1", "--memo-file", str(memo)],
        cwd=tmp_repo,
    )
    assert r4.returncode == 0, r4.stderr

    # 7. finalize
    r5 = _run(["finalize", "--run", run_id], cwd=tmp_repo)
    assert r5.returncode == 0, r5.stderr
    assert (run_dir / "final-report.md").exists()

    state = json.loads((run_dir / "state.json").read_text())
    assert state["status"] == "completed"
    assert state["rounds"][-1]["decision"] == "APPROVE"
