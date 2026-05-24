from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import run_cli


def test_init_run_copies_plan_file(tmp_repo: Path) -> None:
    plan_file = tmp_repo / "my-design.md"
    plan_file.write_text("---\nauthorized: CLAUDE_X_CODEX_PLAN\n---\n# Design\n", encoding="utf-8")

    r = run_cli(
        ["init-run", "--goal", "smoke", "--slug", "smoke", "--plan-file", str(plan_file)],
        cwd=tmp_repo,
    )
    assert r.returncode == 0, r.stderr
    run_id = json.loads(r.stdout)["run_id"]
    plan_md = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    assert plan_md.exists()
    assert "CLAUDE_X_CODEX_PLAN" in plan_md.read_text(encoding="utf-8")


def test_init_run_without_plan_file_leaves_no_plan_md(tmp_repo: Path) -> None:
    r = run_cli(["init-run", "--goal", "smoke", "--slug", "smoke"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    run_id = json.loads(r.stdout)["run_id"]
    plan_md = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    assert not plan_md.exists()


def test_init_run_missing_plan_file_errors(tmp_repo: Path) -> None:
    r = run_cli(
        ["init-run", "--goal", "smoke", "--slug", "smoke", "--plan-file", str(tmp_repo / "nonexistent.md")],
        cwd=tmp_repo,
    )
    assert r.returncode == 1
    assert "plan-file" in r.stderr.lower() or "not found" in r.stderr.lower()
    # No partial run directory should be left behind on failure
    runs_root = tmp_repo / ".agent-loop" / "runs"
    created_runs = list(runs_root.glob("*/")) if runs_root.exists() else []
    assert len(created_runs) == 0, f"Expected no run dirs, found: {created_runs}"
