from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run([sys.executable, "-m", "agent_loop", *args],
                          cwd=cwd, capture_output=True,
                          text=True, check=False, env=env)


def test_review_round_emits_decision(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]
    rd = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rd.mkdir(parents=True)
    (rd / "round_plan.json").write_text(json.dumps({"commit_on_approve": True}), encoding="utf-8")
    (rd / "claude-prompt.md").write_text("hi", encoding="utf-8")
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
    assert js["artifact_mode"] == "compact"
    assert not (rd / "diff.patch").exists()
    assert not (rd / "diff-stats.json").exists()
    assert (rd / "review-payload.json").exists()
    # review-round must not emit missing_claude_result flag
    assert "missing_claude_result" not in js.get("safety_flags", [])

    state2 = json.loads(state_p.read_text(encoding="utf-8"))
    assert state2["rounds"][-1]["decision"] == "APPROVE"
    # review-round now auto-composes and appends the round memo, advancing
    # phase all the way through reviewed -> memo_written -> completed.
    assert state2["rounds"][-1]["phase"] == "completed"
    assert js["memo_appended"] is True
    memo_text = (tmp_repo / ".agent-loop" / "runs" / run_id / "memo.md").read_text(
        encoding="utf-8"
    )
    assert "## Round 1 - APPROVE" in memo_text


def test_review_round_debug_mode_preserves_intermediate_artifacts(
    tmp_repo: Path, codex_stub
) -> None:
    (tmp_repo / ".agent-loop").mkdir(exist_ok=True)
    (tmp_repo / ".agent-loop" / "config.toml").write_text(
        "[artifacts]\nmode = \"debug\"\n",
        encoding="utf-8",
    )
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    rd = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rd.mkdir(parents=True)
    (rd / "round_plan.json").write_text(json.dumps({"commit_on_approve": True}), encoding="utf-8")
    (rd / "diff.patch").write_text(
        "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -0,0 +1 @@\n+hi\n",
        encoding="utf-8",
    )

    state_p = tmp_repo / ".agent-loop" / "runs" / run_id / "state.json"
    state = json.loads(state_p.read_text(encoding="utf-8"))
    state["rounds"].append({
        "n": 1, "phase": "claude_completed", "decision": None,
        "memo_lines": None, "started_at": "t", "ended_at": None,
    })
    state["current_round"] = 1
    state_p.write_text(json.dumps(state), encoding="utf-8")

    env = codex_stub(
        "# Codex Review -- Round 1\n\n## Decision\nAPPROVE\n\n## Findings\n- none\n"
    )
    r = _run(["review-round", "--run", run_id, "--round", "1"],
             cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["artifact_mode"] == "debug"
    assert (rd / "diff.patch").exists()
    assert (rd / "diff-stats.json").exists()
    assert (rd / "review-payload.json").exists()


def test_review_round_emits_severity_and_carry_forward(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]
    rd = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rd.mkdir(parents=True)
    (rd / "round_plan.json").write_text(json.dumps({"commit_on_approve": True}), encoding="utf-8")
    (rd / "claude-prompt.md").write_text("hi", encoding="utf-8")
    (rd / "diff.patch").write_text("", encoding="utf-8")

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
        "## Decision\nNEEDS_CHANGES\n\n"
        "## Goal Alignment\nPartially done.\n\n"
        "## Findings\n"
        "- [severity: high] foo.py:10 -- critical issue\n"
        "- [severity: med] bar.py:5 -- moderate issue\n"
        "- [severity: low] baz.py:1 -- minor nit\n\n"
        "## Verification\n- Tests: pass\n\n"
        "## Risks\n- none\n\n"
        "## Carry-Forward For Next Round\n"
        "- fix the critical issue\n"
        "- address the moderate issue\n\n"
        "## Final Notes\nok\n"
    )
    env = codex_stub(fake_body)
    r = _run(["review-round", "--run", run_id, "--round", "1"],
             cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert "severity_counts" in js
    assert isinstance(js["severity_counts"]["high"], int)
    assert isinstance(js["severity_counts"]["med"], int)
    assert isinstance(js["severity_counts"]["low"], int)
    assert js["severity_counts"]["high"] == 1
    assert js["severity_counts"]["med"] == 1
    assert js["severity_counts"]["low"] == 1
    assert "carry_forward" in js
    assert isinstance(js["carry_forward"], list)


def test_review_round_rejects_invalid_artifact_mode(tmp_repo: Path) -> None:
    (tmp_repo / ".agent-loop").mkdir(exist_ok=True)
    (tmp_repo / ".agent-loop" / "config.toml").write_text(
        "[artifacts]\nmode = \"deubg\"\n",
        encoding="utf-8",
    )
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    rd = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rd.mkdir(parents=True)
    (rd / "round_plan.json").write_text(json.dumps({"commit_on_approve": True}), encoding="utf-8")
    r = _run(["review-round", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode != 0
    assert "invalid artifacts.mode" in r.stderr
