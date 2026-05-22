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


def test_plan_round_creates_round_dir_and_prompt(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]
    # write a fake plan first
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n2. [ ] do B\n", encoding="utf-8")

    env = codex_stub("## Task\nImplement A")
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["round_n"] == 1
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    assert pr.exists()
    assert "Implement A" in pr.read_text(encoding="utf-8")
