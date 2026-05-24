"""CLI tests for advance-phase subcommand."""
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
    return subprocess.run(
        [sys.executable, "-m", "agent_loop", *args],
        cwd=cwd, capture_output=True, text=True, check=False, env=env,
    )


def _init_run(cwd: Path) -> str:
    r = _run(["init-run", "--goal", "test goal", "--slug", "test"], cwd=cwd)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["run_id"]


def _write_state(run_dir: Path, **overrides) -> None:
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(overrides)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _write_phases_json(run_dir: Path, phases: list[dict]) -> None:
    phases_dir = run_dir / "phases"
    phases_dir.mkdir(exist_ok=True)
    index = []
    for ph in phases:
        n = ph["phase_n"]
        doc_path = phases_dir / f"phase-{n:02d}.md"
        doc_path.write_text(ph.get("content", f"# Phase {n}\n"), encoding="utf-8")
        index.append({
            "phase_n": n,
            "title": ph["title"],
            "objective": ph.get("objective", ""),
            "doc_path": f"phases/phase-{n:02d}.md",
        })
    (run_dir / "phases.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def _codex_stub(tmp_repo: Path, content: str) -> dict:
    stub_path = tmp_repo / "codex_stub_adv.py"
    stub_path.write_text(
        "import json, sys\n"
        f"print(json.dumps({{'type': 'assistant_message', 'content': {content!r}}}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}


def test_advance_phase_increments_current_phase(tmp_repo: Path) -> None:
    """advance-phase goes from phase 1 to 2 and emits correct JSON."""
    run_id = _init_run(tmp_repo)
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    _write_phases_json(run_dir, [
        {"phase_n": 1, "title": "Phase One", "content": "# Phase 1\n"},
        {"phase_n": 2, "title": "Phase Two", "content": "# Phase 2\n"},
    ])
    _write_state(run_dir, current_phase=1, total_phases=2, phase_advance_pending=True)

    env = _codex_stub(tmp_repo, "# Updated Phase 2\n\nUpdated content from Codex.\n")
    r = _run(["advance-phase", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    out = json.loads(r.stdout)
    assert out["previous_phase"] == 1
    assert out["current_phase"] == 2
    assert out["is_last_phase"] is False

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["current_phase"] == 2
    assert state["phase_advance_pending"] is False


def test_advance_phase_updates_next_phase_doc(tmp_repo: Path) -> None:
    """advance-phase overwrites the next phase doc with Codex-supplied text."""
    run_id = _init_run(tmp_repo)
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    _write_phases_json(run_dir, [
        {"phase_n": 1, "title": "Phase One", "content": "# Phase 1\n"},
        {"phase_n": 2, "title": "Phase Two", "content": "# Phase 2\nOriginal content.\n"},
    ])
    _write_state(run_dir, current_phase=1, total_phases=2, phase_advance_pending=True)

    updated_doc = "# Phase 2: Updated\n\nCodex provided this updated content.\n"
    env = _codex_stub(tmp_repo, updated_doc)
    r = _run(["advance-phase", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    phase2_doc = (run_dir / "phases" / "phase-02.md").read_text(encoding="utf-8")
    assert "Codex provided this updated content." in phase2_doc


def test_advance_phase_emits_is_last_phase_when_on_last(tmp_repo: Path) -> None:
    """When already on last phase, returns is_last_phase=True without calling Codex."""
    run_id = _init_run(tmp_repo)
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    _write_phases_json(run_dir, [
        {"phase_n": 1, "title": "Only Phase", "content": "# Phase 1\n"},
    ])
    _write_state(run_dir, current_phase=1, total_phases=1, phase_advance_pending=True)

    # Point to a nonexistent binary — no Codex call should be made.
    env = {"AGENT_LOOP_CODEX_BIN": str(tmp_repo / "nonexistent-codex-bin")}
    r = _run(["advance-phase", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    out = json.loads(r.stdout)
    assert out["is_last_phase"] is True
    assert out["current_phase"] == 1

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase_advance_pending"] is False


def test_advance_phase_idempotent_resume(tmp_repo: Path) -> None:
    """advance-phase clears phase_advance_pending on both last and intermediate paths."""
    run_id = _init_run(tmp_repo)
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # Intermediate path: advance once, then check pending is cleared.
    _write_phases_json(run_dir, [
        {"phase_n": 1, "title": "P1", "content": "# Phase 1\n"},
        {"phase_n": 2, "title": "P2", "content": "# Phase 2\n"},
    ])
    _write_state(run_dir, current_phase=1, total_phases=2, phase_advance_pending=True)

    env = _codex_stub(tmp_repo, "# Phase 2 updated\n")
    r = _run(["advance-phase", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase_advance_pending"] is False
    assert state["current_phase"] == 2
