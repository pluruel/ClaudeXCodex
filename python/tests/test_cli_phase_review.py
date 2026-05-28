from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    import os
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "agent_loop", *args],
        cwd=cwd, capture_output=True, text=True, check=False, env=env,
    )


def _bootstrap_run(tmp_repo: Path, codex_stub) -> str:
    """Create a run with commits so HEAD~1 is valid."""
    (tmp_repo / "src.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "src.py"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_repo, check=True)

    (tmp_repo / "src.py").write_text("x = 2\n")
    subprocess.run(["git", "add", "src.py"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "phase 1: update x"], cwd=tmp_repo, check=True)
    phase_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    r = _run(["init-run", "--goal", "improve x", "--slug", "test"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    run_id = json.loads(r.stdout)["run_id"]

    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    phases_dir = run_dir / "phases"
    phases_dir.mkdir(parents=True, exist_ok=True)
    (phases_dir / "phase-01.md").write_text("# Phase 1\n\nUpdate x to 2.", encoding="utf-8")
    (run_dir / "phases.json").write_text(
        json.dumps([{"phase_n": 1, "title": "Update x", "objective": "set x=2", "doc_path": "phases/phase-01.md"}]),
        encoding="utf-8",
    )
    (run_dir / "shared").mkdir(exist_ok=True)

    # Record the phase-1 commit sha so phase-review's phase-commit gate passes
    # (the real flow records this via the phase-commit subcommand).
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.setdefault("phase_commits", {})["1"] = phase_sha
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return run_id


def test_phase_review_emits_approve(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)
    fake_review = (
        "# Phase Review -- Phase 1\n\n"
        "## Decision\nAPPROVE\n\n"
        "## Goal Alignment\nObjective met.\n\n"
        "## Findings\n- none\n\n"
        "## Verification\n- Tests: pass\n\n"
        "## Risks\n- none\n\n"
        "## Carry-Forward For Next Round\n- (none)\n"
    )
    env = codex_stub(fake_review)
    r = _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["decision"] == "APPROVE"
    assert js["phase"] == 1
    assert js["memo_appended"] is True


def test_phase_review_emits_needs_changes(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)
    fake_review = (
        "# Phase Review -- Phase 1\n\n"
        "## Decision\nNEEDS_CHANGES\n\n"
        "## Goal Alignment\nNot done.\n\n"
        "## Findings\n- [severity: high] src.py:1 -- value wrong\n\n"
        "## Verification\n- Tests: fail\n\n"
        "## Risks\n- regression risk\n\n"
        "## Carry-Forward For Next Round\n- fix x value\n"
    )
    env = codex_stub(fake_review)
    r = _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["decision"] == "NEEDS_CHANGES"
    assert js["severity_counts"]["high"] == 1
    assert "fix x value" in js["carry_forward"]


def test_phase_review_writes_review_file(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)
    fake_review = "# Phase Review -- Phase 1\n\n## Decision\nAPPROVE\n\n## Findings\n- none\n"
    env = codex_stub(fake_review)
    _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)
    review_path = tmp_repo / ".agent-loop" / "runs" / run_id / "phases" / "phase-01-review.md"
    assert review_path.exists()
    assert "APPROVE" in review_path.read_text(encoding="utf-8")


def test_phase_review_updates_state(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)
    fake_review = "# Phase Review -- Phase 1\n\n## Decision\nAPPROVE\n\n## Findings\n- none\n"
    env = codex_stub(fake_review)
    _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)
    state_path = tmp_repo / ".agent-loop" / "runs" / run_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state["phase_reviews"]) == 1
    assert state["phase_reviews"][0]["phase_n"] == 1
    assert state["phase_reviews"][0]["decision"] == "APPROVE"


def test_phase_review_consecutive_needs_changes(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)
    fake_review = "# Phase Review -- Phase 1\n\n## Decision\nNEEDS_CHANGES\n\n## Findings\n- none\n"

    env = codex_stub(fake_review)
    r = _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)
    assert json.loads(r.stdout)["consecutive_needs_changes"] == 1

    (tmp_repo / "src.py").write_text("x = 3\n")
    subprocess.run(["git", "add", "src.py"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "phase 1 fix"], cwd=tmp_repo, check=True)

    env = codex_stub(fake_review)
    r = _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)
    assert json.loads(r.stdout)["consecutive_needs_changes"] == 2


def test_phase_review_memo_idempotent(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)
    fake_review = "# Phase Review -- Phase 1\n\n## Decision\nAPPROVE\n\n## Findings\n- none\n"

    env = codex_stub(fake_review)
    _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)
    r2 = _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=codex_stub(fake_review))
    js2 = json.loads(r2.stdout)
    assert js2["memo_appended"] is False
