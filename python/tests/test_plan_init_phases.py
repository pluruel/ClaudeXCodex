"""Tests for plan-init phase generation: phases.json, phase docs, state fields, normalization."""
from __future__ import annotations

import json
import os
import re
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


# ---------------------------------------------------------------------------
# Helpers for parsed-plan tests
# ---------------------------------------------------------------------------

def _make_counting_stub(tmp_repo: Path, responses: list[str], counter_name: str = ".stub_counter_parsed") -> dict:
    """Returns env dict for a stub that counts calls and returns responses[i] on i-th call."""
    counter_file = tmp_repo / counter_name
    stub_path = tmp_repo / f"codex_stub_{counter_name.lstrip('.')}.py"
    items = ", ".join(repr(r) for r in responses)
    stub_path.write_text(
        f"import json, sys\n"
        f"from pathlib import Path\n"
        f"counter_file = Path({str(counter_file)!r})\n"
        f"try:\n"
        f"    count = int(counter_file.read_text())\n"
        f"except Exception:\n"
        f"    count = 0\n"
        f"counter_file.write_text(str(count + 1))\n"
        f"responses = [{items}]\n"
        f"resp = responses[min(count, len(responses) - 1)]\n"
        f"print(json.dumps({{'type': 'assistant_message', 'content': resp}}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}


def _plan_with_phases(phases_block: str) -> str:
    """Wrap a phases_block in a proper plan.md with ## Phases section."""
    return (
        "# Plan: Test plan\n\n"
        "## Goal\nDo something.\n\n"
        "## Tasks\n1. [ ] do it\n\n"
        f"## Phases\n{phases_block}"
    )


def _make_phase_block(n: int, title: str, objective: str, target_files: list[str]) -> str:
    """Render a single phase block in the plan template format."""
    tf_str = ", ".join(f"`{f}`" for f in target_files)
    return (
        f"{n}. **{title}** -- {objective}\n"
        f"  - Target files: {tf_str}\n"
        f"  - Acceptance criteria:\n"
        f"    - pytest python/tests -q passes\n"
        f"  - Testing: How to verify: `pytest python/tests -q` -- all tests pass\n"
        f"  - Out of scope: unrelated changes\n"
        f"  - Notes: keep it simple\n"
    )


def _create_real_files(tmp_repo: Path) -> list[str]:
    """Create real files in tmp_repo and return their repo-relative paths."""
    src = tmp_repo / "src"
    src.mkdir(exist_ok=True)
    (src / "alpha.py").write_text("# alpha\n")
    (src / "beta.py").write_text("# beta\n")
    subprocess.run(["git", "add", "src/"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add src files"], cwd=tmp_repo, check=True)
    return ["src/alpha.py", "src/beta.py"]


# ---------------------------------------------------------------------------
# Tests: parsed-plan path
# ---------------------------------------------------------------------------

def test_plan_init_parsed_when_plan_has_phases(tmp_repo: Path) -> None:
    """Pre-existing plan.md with ## Phases and valid target_files -> phase_source == 'parsed', zero Codex calls."""
    real_files = _create_real_files(tmp_repo)
    run_id = _init_run(tmp_repo, goal="test parsed path", slug="parsed")
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    phases_block = (
        _make_phase_block(1, "Alpha Phase", "Set up alpha.", [real_files[0]])
        + _make_phase_block(2, "Beta Phase", "Set up beta.", [real_files[1]])
    )
    plan_text = _plan_with_phases(phases_block)
    (run_dir / "plan.md").write_text(plan_text, encoding="utf-8")

    # Stub: should NOT be called at all (all target_files exist)
    counter_name = ".stub_counter_parsed_zero"
    env = _make_counting_stub(tmp_repo, ["unused"], counter_name=counter_name)
    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    out = json.loads(r.stdout)
    assert out.get("phase_source") == "parsed", \
        f"Expected phase_source='parsed', got {out.get('phase_source')!r}"
    assert out.get("plan_source") == "pre-existing"
    assert len(out["phases"]) == 2
    titles = [p["title"] for p in out["phases"]]
    assert "Alpha Phase" in titles
    assert "Beta Phase" in titles

    # Verify ZERO Codex calls were made
    counter_file = tmp_repo / counter_name
    call_count = int(counter_file.read_text()) if counter_file.exists() else 0
    assert call_count == 0, f"Expected 0 Codex calls, got {call_count}"

    # Phase docs must exist with all 6 headings
    for i in range(1, 3):
        doc = run_dir / "phases" / f"phase-{i:02d}.md"
        assert doc.exists(), f"phase-{i:02d}.md not found"
        content = doc.read_text(encoding="utf-8")
        for heading in ["## Objective", "## Target Files", "## Acceptance Criteria",
                        "## Testing", "## Out of Scope", "## Notes"]:
            assert heading in content, f"Missing heading {heading!r} in phase-{i:02d}.md"


def test_plan_init_falls_back_to_codex_when_unparseable(tmp_repo: Path) -> None:
    """Pre-existing plan.md with NO ## Phases section -> phase_source == 'codex', Codex called for phases."""
    _create_real_files(tmp_repo)
    run_id = _init_run(tmp_repo, goal="test fallback", slug="fallback")
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # Plan without ## Phases section
    plan_text = "# Plan\n\n## Tasks\n1. [ ] do it\n"
    (run_dir / "plan.md").write_text(plan_text, encoding="utf-8")

    # Stub returns a valid phase JSON
    phases_json = json.dumps({
        "phases": [{
            "phase_n": 1,
            "title": "Codex Phase",
            "objective": "Implement it.",
            "scope_hint": "src/",
            "target_files": ["src/alpha.py"],
            "acceptance_criteria": ["pytest python/tests -q passes"],
            "testing": {"command": "pytest python/tests -q", "expected": "pass"},
            "out_of_scope": [],
            "notes": "",
        }]
    })
    counter_name = ".stub_counter_fallback"
    env = _make_counting_stub(tmp_repo, [phases_json], counter_name=counter_name)

    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    out = json.loads(r.stdout)
    assert out.get("phase_source") == "codex", \
        f"Expected phase_source='codex', got {out.get('phase_source')!r}"
    assert out.get("plan_source") == "pre-existing"
    assert len(out["phases"]) >= 1

    # Verify Codex was called at least once (for the phases prompt)
    counter_file = tmp_repo / counter_name
    call_count = int(counter_file.read_text()) if counter_file.exists() else 0
    assert call_count >= 1, f"Expected >=1 Codex call for phases, got {call_count}"


def test_plan_init_parsed_phase_without_target_files(tmp_repo: Path) -> None:
    """Parsed phase with NO Target files sub-bullet -> phase_source='parsed', ZERO Codex calls."""
    _create_real_files(tmp_repo)
    run_id = _init_run(tmp_repo, goal="test no target files", slug="no-tf")
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # Phase block with no "Target files:" sub-bullet
    phase_block_no_tf = (
        "1. **Lone Phase** -- Objective with no target files.\n"
        "  - Acceptance criteria:\n"
        "    - pytest python/tests -q passes\n"
        "  - Testing: How to verify: `pytest python/tests -q` -- all tests pass\n"
        "  - Out of scope: unrelated changes\n"
        "  - Notes: keep it simple\n"
    )
    plan_text = _plan_with_phases(phase_block_no_tf)
    (run_dir / "plan.md").write_text(plan_text, encoding="utf-8")

    # Stub counter: must NOT be called
    counter_name = ".stub_counter_no_tf"
    env = _make_counting_stub(tmp_repo, ["unused"], counter_name=counter_name)

    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    out = json.loads(r.stdout)
    assert out.get("phase_source") == "parsed", \
        f"Expected phase_source='parsed', got {out.get('phase_source')!r}"
    assert len(out["phases"]) == 1, f"Expected 1 phase, got {len(out['phases'])}"
    assert out["phases"][0]["title"] == "Lone Phase"

    # ZERO Codex calls (no repair needed for missing target_files)
    counter_file = tmp_repo / counter_name
    call_count = int(counter_file.read_text()) if counter_file.exists() else 0
    assert call_count == 0, f"Expected 0 Codex calls, got {call_count}"

    # Phase doc must exist and show "(none)" for target files
    phase_doc = run_dir / "phases" / "phase-01.md"
    assert phase_doc.exists(), "phase-01.md not found"
    content = phase_doc.read_text(encoding="utf-8")
    assert "## Target Files" in content, "Missing '## Target Files' heading"
    assert "(none)" in content, "Expected '(none)' for empty target files list"


def test_plan_init_narrow_repair_when_target_missing(tmp_repo: Path) -> None:
    """Pre-existing plan.md with one nonexistent target_file -> exactly ONE repair Codex call made."""
    real_files = _create_real_files(tmp_repo)
    run_id = _init_run(tmp_repo, goal="test repair", slug="repair")
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # Phase with one real file and one nonexistent file
    nonexistent = "nonexistent/ghost.py"
    phases_block = _make_phase_block(
        1, "Repair Phase", "Test repair.",
        [real_files[0], nonexistent],
    )
    plan_text = _plan_with_phases(phases_block)
    (run_dir / "plan.md").write_text(plan_text, encoding="utf-8")

    # Repair stub returns a JSON with the repair mapping
    repair_response = json.dumps({"repairs": {nonexistent: real_files[1]}})
    counter_name = ".stub_counter_repair"
    env = _make_counting_stub(tmp_repo, [repair_response], counter_name=counter_name)

    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    out = json.loads(r.stdout)
    assert out.get("phase_source") == "parsed"
    assert len(out["phases"]) == 1

    # Exactly ONE Codex call for repair
    counter_file = tmp_repo / counter_name
    call_count = int(counter_file.read_text()) if counter_file.exists() else 0
    assert call_count == 1, f"Expected exactly 1 repair Codex call, got {call_count}"

    # The bad path is repaired or dropped; ghost.py must not be in the doc
    phase_doc = run_dir / "phases" / "phase-01.md"
    assert phase_doc.exists()
    content = phase_doc.read_text(encoding="utf-8")
    assert nonexistent not in content, \
        "Nonexistent path should not appear in the phase doc after repair"
    # The real file should be present (either original or repaired)
    assert real_files[0] in content or real_files[1] in content, \
        "At least one real file should appear in the phase doc"
