from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False, env=env)


def test_review_round_emits_decision(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]
    rd = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rd.mkdir(parents=True)
    (rd / "claude-prompt.md").write_text("hi", encoding="utf-8")
    (rd / "claude-result.md").write_text(
        "# Claude Result\n\n## Summary\ndid stuff\n\n## Test Outcome\npass\n\n## Decision Hint\ncompleted\n\n## Requires User\nfalse\n",
        encoding="utf-8",
    )
    (rd / "diff.patch").write_text("", encoding="utf-8")

    # state needs round 1 registered
    state_p = tmp_repo / ".agent-loop" / "runs" / run_id / "state.json"
    state = json.loads(state_p.read_text(encoding="utf-8"))
    state["rounds"].append({
        "n": 1, "phase": "claude_completed", "decision": None,
        "memo_lines": None, "started_at": "t", "ended_at": None,
    })
    state["current_round"] = 1
    state_p.write_text(json.dumps(state), encoding="utf-8")

    fake_body = (
        "# Codex Review -- Round 1\n\n"
        "## Decision\nAPPROVE\n\n"
        "## Findings\n- none\n"
    )
    env = codex_stub(fake_body)
    r = _run(["review-round", "--run", run_id, "--round", "1"],
             cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["decision"] == "APPROVE"
    assert (rd / "codex-review.md").exists()

    state2 = json.loads(state_p.read_text(encoding="utf-8"))
    assert state2["rounds"][-1]["decision"] == "APPROVE"
    assert state2["rounds"][-1]["phase"] == "reviewed"
