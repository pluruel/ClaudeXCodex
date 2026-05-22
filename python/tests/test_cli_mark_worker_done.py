from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(args, cwd):
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False)


def test_mark_worker_done_flips_phase(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]

    # register round 1 in state directly (skipping plan-round which would invoke codex)
    from agent_loop.run_state import RunState
    state_p = tmp_repo / ".agent-loop" / "runs" / run_id / "state.json"
    rs = RunState.load(state_p)
    rs.start_round(n=1, started_at="t0")
    rs.save(state_p)

    r = _run(["mark-worker-done", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    rs2 = RunState.load(state_p)
    assert rs2.rounds[-1].phase == "claude_completed"
