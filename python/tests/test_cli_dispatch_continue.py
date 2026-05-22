from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(args, cwd):
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False)


def test_continue_reports_resume_plan_on_init_phase(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    prompt = tmp_repo / "p.md"
    prompt.write_text("hi")
    _run(["init-round", "--run", run_id, "--prompt-file", str(prompt)], cwd=tmp_repo)
    r = _run(["continue", "--run", run_id], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["action"] == "dispatch"


def test_continue_no_active_run(tmp_repo: Path) -> None:
    r = _run(["continue"], cwd=tmp_repo)
    assert r.returncode != 0
    assert "no active run" in (r.stdout + r.stderr)


def test_dispatch_placeholder_present() -> None:
    """dispatch goes through SDK; covered in integration test (Task 5.1)."""
    assert True
