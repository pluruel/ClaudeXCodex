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


def test_plan_init_writes_plan_md(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "smoke"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]

    env = codex_stub("# Plan\n\n## Tasks\n1. [ ] do thing")
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r2.returncode == 0, r2.stderr
    js = json.loads(r2.stdout)
    assert js["plan_path"].endswith("plan.md")
    plan_md = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    assert plan_md.exists()
    assert "# Plan" in plan_md.read_text(encoding="utf-8")
