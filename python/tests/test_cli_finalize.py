from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import run_cli


def _init_run(tmp_repo: Path, goal: str = "test goal", slug: str = "test-run") -> str:
    r = run_cli(["init-run", "--goal", goal, "--slug", slug], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["run_id"]


def test_finalize_deletes_plan_file_when_exists(tmp_repo: Path) -> None:
    """When .agent-loop-plan.md exists, finalize should delete it and return plan_file_cleaned: true."""
    run_id = _init_run(tmp_repo)
    plan_file = tmp_repo / ".agent-loop-plan.md"
    plan_file.write_text("# Plan\n\nsome plan content\n", encoding="utf-8")
    assert plan_file.exists()

    r = run_cli(["finalize", "--run", run_id], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)

    assert js["plan_file_cleaned"] is True
    assert not plan_file.exists()
    assert js["status"] == "completed"
    assert "final_report" in js


def test_finalize_no_plan_file(tmp_repo: Path) -> None:
    """When .agent-loop-plan.md does not exist, finalize returns plan_file_cleaned: false."""
    run_id = _init_run(tmp_repo)
    plan_file = tmp_repo / ".agent-loop-plan.md"
    assert not plan_file.exists()

    r = run_cli(["finalize", "--run", run_id], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)

    assert js["plan_file_cleaned"] is False
    assert not plan_file.exists()
    assert js["status"] == "completed"
    assert "final_report" in js
