"""Tests for plan-init phase generation: phases.json, phase docs, state fields, normalization."""
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


def _init_run(cwd: Path, goal: str = "test goal", slug: str = "test") -> str:
    r = _run(["init-run", "--goal", goal, "--slug", slug], cwd=cwd)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["run_id"]


def _two_response_stub(tmp_repo: Path, resp1: str, resp2: str) -> dict:
    """Factory: returns env dict for a Codex bin that returns resp1 on first call, resp2 on second."""
    counter_file = tmp_repo / ".stub_counter_phases"
    stub_path = tmp_repo / "codex_stub_phases.py"
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


_PLAN_TEXT = "# Plan\n\n## Tasks\n1. [ ] do thing\n2. [ ] do another thing\n"

_THREE_PHASES_JSON = json.dumps({
    "phases": [
        {
            "phase_n": 1,
            "title": "Setup",
            "objective": "Initialize the project structure.",
            "content": "# Phase 1: Setup\n\n## Objective\nInitialize the project structure.\n",
        },
        {
            "phase_n": 2,
            "title": "Implementation",
            "objective": "Write the core logic.",
            "content": "# Phase 2: Implementation\n\n## Objective\nWrite the core logic.\n",
        },
        {
            "phase_n": 3,
            "title": "Validation",
            "objective": "Test and validate the result.",
            "content": "# Phase 3: Validation\n\n## Objective\nTest and validate the result.\n",
        },
    ]
})


def test_plan_init_writes_phases_json(tmp_repo: Path) -> None:
    """phases.json is created with correct entries after plan-init."""
    run_id = _init_run(tmp_repo)
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    env = _two_response_stub(tmp_repo, _PLAN_TEXT, _THREE_PHASES_JSON)
    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    phases_json_path = run_dir / "phases.json"
    assert phases_json_path.exists(), "phases.json not found"
    phases = json.loads(phases_json_path.read_text(encoding="utf-8"))
    assert isinstance(phases, list)
    assert len(phases) == 3
    phase_ns = [p["phase_n"] for p in phases]
    assert phase_ns == [1, 2, 3], f"Expected [1,2,3], got {phase_ns}"
    assert phases[0]["title"] == "Setup"
    assert phases[1]["title"] == "Implementation"
    assert phases[2]["title"] == "Validation"


def test_plan_init_writes_phase_docs(tmp_repo: Path) -> None:
    """phase-01.md, phase-02.md, phase-03.md are created in the phases/ directory."""
    run_id = _init_run(tmp_repo)
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    env = _two_response_stub(tmp_repo, _PLAN_TEXT, _THREE_PHASES_JSON)
    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    phases_dir = run_dir / "phases"
    for i in range(1, 4):
        doc = phases_dir / f"phase-{i:02d}.md"
        assert doc.exists(), f"phase-{i:02d}.md not found"
        content = doc.read_text(encoding="utf-8")
        assert f"# Phase {i}" in content, f"Expected '# Phase {i}' in phase-{i:02d}.md"


def test_plan_init_sets_state_phase_fields(tmp_repo: Path) -> None:
    """state.json is updated with current_phase=1 and total_phases=3 after plan-init."""
    run_id = _init_run(tmp_repo)
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    env = _two_response_stub(tmp_repo, _PLAN_TEXT, _THREE_PHASES_JSON)
    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["current_phase"] == 1, f"current_phase expected 1, got {state.get('current_phase')}"
    assert state["total_phases"] == 3, f"total_phases expected 3, got {state.get('total_phases')}"


def test_plan_init_emits_phases_in_json(tmp_repo: Path) -> None:
    """stdout JSON from plan-init includes 'phases' key and summary mentioning count."""
    run_id = _init_run(tmp_repo)

    env = _two_response_stub(tmp_repo, _PLAN_TEXT, _THREE_PHASES_JSON)
    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    out = json.loads(r.stdout)
    assert "phases" in out, "Expected 'phases' key in plan-init output"
    assert len(out["phases"]) == 3
    assert "3 phase" in out.get("summary", ""), f"Expected '3 phase' in summary, got: {out.get('summary')}"


def test_plan_init_single_phase_fallback_on_bad_json(tmp_repo: Path) -> None:
    """Malformed phases JSON from Codex results in 1 phase fallback and total_phases=1."""
    run_id = _init_run(tmp_repo)
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    bad_phases_json = "this is not valid json {{{ garbage"
    env = _two_response_stub(tmp_repo, _PLAN_TEXT, bad_phases_json)
    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    phases_json_path = run_dir / "phases.json"
    assert phases_json_path.exists(), "phases.json not found even in fallback case"
    phases = json.loads(phases_json_path.read_text(encoding="utf-8"))
    assert len(phases) == 1, f"Expected 1 phase fallback, got {len(phases)}"
    assert phases[0]["phase_n"] == 1

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["total_phases"] == 1, f"Expected total_phases=1 in fallback, got {state.get('total_phases')}"

    phase01 = run_dir / "phases" / "phase-01.md"
    assert phase01.exists(), "phase-01.md not found in fallback case"


def test_plan_init_normalizes_non_contiguous_phase_ns(tmp_repo: Path) -> None:
    """Codex returns phases with phase_n=[0, 5, 99] — normalized to [1, 2, 3]."""
    run_id = _init_run(tmp_repo)
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # Codex returns 3 phases with unusual phase_n values: 0, 5, 99
    weird_phases_json = json.dumps({
        "phases": [
            {
                "phase_n": 0,
                "title": "Zero Phase",
                "objective": "First weird phase.",
                "content": "# Phase 0: Zero Phase\n\n## Objective\nFirst weird phase.\n",
            },
            {
                "phase_n": 5,
                "title": "Five Phase",
                "objective": "Second weird phase.",
                "content": "# Phase 5: Five Phase\n\n## Objective\nSecond weird phase.\n",
            },
            {
                "phase_n": 99,
                "title": "NinetyNine Phase",
                "objective": "Third weird phase.",
                "content": "# Phase 99: NinetyNine Phase\n\n## Objective\nThird weird phase.\n",
            },
        ]
    })

    env = _two_response_stub(tmp_repo, _PLAN_TEXT, weird_phases_json)
    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    phases_json_path = run_dir / "phases.json"
    assert phases_json_path.exists()
    phases = json.loads(phases_json_path.read_text(encoding="utf-8"))

    # Must be normalized to [1, 2, 3]
    phase_ns = [p["phase_n"] for p in phases]
    assert phase_ns == [1, 2, 3], f"Expected normalized [1,2,3], got {phase_ns}"

    # Titles must be preserved (sorted by original phase_n: 0, 5, 99)
    assert phases[0]["title"] == "Zero Phase"
    assert phases[1]["title"] == "Five Phase"
    assert phases[2]["title"] == "NinetyNine Phase"

    # Phase doc files must exist with normalized names
    phases_dir = run_dir / "phases"
    for i in range(1, 4):
        assert (phases_dir / f"phase-{i:02d}.md").exists(), f"phase-{i:02d}.md missing"

    # No files with old numbering should exist
    assert not (phases_dir / "phase-00.md").exists(), "phase-00.md should not exist"
    assert not (phases_dir / "phase-05.md").exists(), "phase-05.md should not exist"
    assert not (phases_dir / "phase-99.md").exists(), "phase-99.md should not exist"

    # State should reflect normalized count
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["current_phase"] == 1
    assert state["total_phases"] == 3
