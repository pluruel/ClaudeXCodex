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


def _two_response_stub(tmp_repo: Path, resp1: str, resp2: str) -> dict:
    """Returns env dict for a Codex bin that responds with resp1 first, resp2 second."""
    counter_file = tmp_repo / ".stub_counter"
    stub_path = tmp_repo / "codex_stub_two.py"
    stub_path.write_text(
        f"import json, sys\n"
        f"from pathlib import Path\n"
        f"counter_file = Path({str(counter_file)!r})\n"
        f"try:\n"
        f"    count = int(counter_file.read_text())\n"
        f"except Exception:\n"
        f"    count = 0\n"
        f"counter_file.write_text(str(count + 1))\n"
        f"resp = [{resp1!r}, {resp2!r}][min(count, 1)]\n"
        f"print(json.dumps({{'type': 'assistant_message', 'content': resp}}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}


def test_plan_init_writes_plan_md(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "smoke"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]

    phases_json = json.dumps({"phases": [{"phase_n": 1, "title": "Implementation", "objective": "Do it.", "content": "# Phase 1\n"}]})
    env = _two_response_stub(tmp_repo, "# Plan\n\n## Tasks\n1. [ ] do thing", phases_json)
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r2.returncode == 0, r2.stderr
    js = json.loads(r2.stdout)
    assert js["plan_path"].endswith("plan.md")
    plan_md = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    assert plan_md.exists()
    assert "# Plan" in plan_md.read_text(encoding="utf-8")


def test_plan_init_skips_draft_when_plan_md_exists(tmp_repo: Path) -> None:
    """plan-init must NOT call Codex for the plan draft when plan.md is pre-existing."""
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "skip"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]

    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    existing_plan = "---\nauthorized: CLAUDE_X_CODEX_PLAN\n---\n# Pre-existing Plan\n\n## Tasks\n1. [ ] pre task\n"
    (run_dir / "plan.md").write_text(existing_plan, encoding="utf-8")

    phases_json = json.dumps({"phases": [{"phase_n": 1, "title": "Impl", "objective": "Do it.", "content": "# Phase 1\n"}]})
    # Only one Codex response needed (phases call only); a two-call stub would fail
    # if the draft call is incorrectly made.
    stub_path = tmp_repo / "codex_one.py"
    stub_path.write_text(
        "import json, sys\n"
        f"print(json.dumps({{'type': 'assistant_message', 'content': {phases_json!r}}}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    env = {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r2.returncode == 0, r2.stderr

    out = json.loads(r2.stdout)
    assert out.get("plan_source") == "pre-existing"
    # plan.md content must be unchanged
    assert "Pre-existing Plan" in (run_dir / "plan.md").read_text(encoding="utf-8")


def test_plan_init_reports_codex_source_when_no_plan_md(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "codexsrc"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]

    phases_json = json.dumps({"phases": [{"phase_n": 1, "title": "Impl", "objective": "Do it.", "content": "# Phase 1\n"}]})
    env = _two_response_stub(tmp_repo, "# Plan\n\n## Tasks\n1. [ ] do thing", phases_json)
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r2.returncode == 0, r2.stderr
    out = json.loads(r2.stdout)
    assert out.get("plan_source") == "codex"


def test_plan_init_reports_missing_codex_without_traceback(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "smoke"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]

    env = {"AGENT_LOOP_CODEX_BIN": str(tmp_repo / "missing-codex-bin")}
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r2.returncode == 1
    assert "codex error: could not execute" in r2.stderr
    assert "Traceback" not in r2.stderr
