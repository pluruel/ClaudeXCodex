"""Tests for plan-init phase doc generation with strict JSON schema and validation.

Tests in this file verify:
- _assemble_phase_doc produces docs with all 6 required headings
- Nonexistent paths in target_files trigger a Codex retry
- Scout signal (file_tree, grep_hits, headers) is injected into the phases prompt
- skills/plan/SKILL.md uses lean phase template (Scope hint, not per-phase Target files)
- Pre-existing plan.md still works (plan_source == "pre-existing")
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(args, cwd, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "agent_loop", *args],
        cwd=cwd, capture_output=True, text=True, check=False, env=env,
    )


def _init_run(tmp_repo: Path, goal: str = "test goal", slug: str = "test") -> str:
    r = _run(["init-run", "--goal", goal, "--slug", slug], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["run_id"]


def _make_stub_sequence(tmp_repo: Path, responses: list[str]) -> dict:
    """Returns env dict for a Codex bin that returns responses[i] on i-th call.

    The stub writes a counter file to track call count and returns the
    appropriate response. After all responses are exhausted, repeats the last.
    """
    counter_file = tmp_repo / ".stub_counter_phase_doc"
    stub_path = tmp_repo / "codex_stub_phase_doc.py"

    # Build a Python list literal with each response as a repr'd string.
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


def _make_capturing_stub(tmp_repo: Path, prompt_file: Path, response: str) -> dict:
    """Returns env dict for a Codex bin that saves its stdin to prompt_file.

    The stub captures the prompt passed via stdin (which is the phases prompt)
    and writes it to prompt_file, then returns the given response.
    """
    stub_path = tmp_repo / "codex_stub_capture.py"
    stub_path.write_text(
        f"import json, sys\n"
        f"from pathlib import Path\n"
        f"prompt_file = Path({str(prompt_file)!r})\n"
        f"# Read stdin to capture the prompt\n"
        f"try:\n"
        f"    prompt_text = sys.stdin.read()\n"
        f"    prompt_file.write_text(prompt_text, encoding='utf-8')\n"
        f"except Exception:\n"
        f"    pass\n"
        f"resp = {response!r}\n"
        f"print(json.dumps({{'type': 'assistant_message', 'content': resp}}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}


def _make_capturing_sequence_stub(tmp_repo: Path, prompt_dir: Path, responses: list[str]) -> dict:
    """Returns env dict for a stub that captures prompts into prompt_dir/<i>.txt."""
    counter_file = tmp_repo / ".stub_counter_capture"
    stub_path = tmp_repo / "codex_stub_capture_seq.py"
    # Build a Python list literal with each response as a repr'd string.
    items = ", ".join(repr(r) for r in responses)
    stub_path.write_text(
        f"import json, sys\n"
        f"from pathlib import Path\n"
        f"counter_file = Path({str(counter_file)!r})\n"
        f"prompt_dir = Path({str(prompt_dir)!r})\n"
        f"prompt_dir.mkdir(parents=True, exist_ok=True)\n"
        f"try:\n"
        f"    count = int(counter_file.read_text())\n"
        f"except Exception:\n"
        f"    count = 0\n"
        f"counter_file.write_text(str(count + 1))\n"
        f"try:\n"
        f"    prompt_text = sys.stdin.read()\n"
        f"    (prompt_dir / f'{{count}}.txt').write_text(prompt_text, encoding='utf-8')\n"
        f"except Exception:\n"
        f"    pass\n"
        f"responses = [{items}]\n"
        f"resp = responses[min(count, len(responses) - 1)]\n"
        f"print(json.dumps({{'type': 'assistant_message', 'content': resp}}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

def _valid_phase_json(tmp_repo: Path, phase_n: int = 1, extra_files: list[str] | None = None) -> str:
    """Return JSON for a valid phase spec referencing real files in tmp_repo."""
    real_files = extra_files or ["src/foo.py"]
    return json.dumps({
        "phases": [
            {
                "phase_n": phase_n,
                "title": f"Phase {phase_n} Title",
                "objective": "Implement the feature.",
                "scope_hint": "src/",
                "target_files": real_files,
                "acceptance_criteria": [
                    "pytest src/test_foo.py passes",
                ],
                "testing": {
                    "command": "pytest src/test_foo.py",
                    "expected": "all tests pass",
                },
                "out_of_scope": ["unrelated modules"],
                "notes": "Keep it simple.",
            }
        ]
    })


def _create_src_files(tmp_repo: Path) -> None:
    """Create src/foo.py and src/bar.py in tmp_repo and git-add them."""
    src = tmp_repo / "src"
    src.mkdir(exist_ok=True)
    (src / "foo.py").write_text("def foo(): pass\n")
    (src / "bar.py").write_text("def bar(): pass\n")
    subprocess.run(["git", "add", "src/"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add src files"], cwd=tmp_repo, check=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_phase_doc_has_all_six_headings(tmp_repo: Path) -> None:
    """Generated phase-01.md must contain all six required headings in order."""
    _create_src_files(tmp_repo)
    run_id = _init_run(tmp_repo, goal="implement feature X", slug="sixheadings")
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # Stub: plan text first (for when plan.md doesn't exist), then phase JSON
    phases_json = _valid_phase_json(tmp_repo, phase_n=1, extra_files=["src/foo.py", "src/bar.py"])
    plan_stub = "# Plan\n\n## Tasks\n1. [ ] do it\n"
    env = _make_stub_sequence(tmp_repo, [plan_stub, phases_json])

    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    phase_doc = run_dir / "phases" / "phase-01.md"
    assert phase_doc.exists(), "phase-01.md not created"
    content = phase_doc.read_text(encoding="utf-8")

    required_headings = [
        "## Objective",
        "## Target Files",
        "## Acceptance Criteria",
        "## Testing",
        "## Out of Scope",
        "## Notes",
    ]
    for heading in required_headings:
        assert re.search(re.escape(heading), content, re.MULTILINE), \
            f"Missing heading {heading!r} in phase-01.md"

    # Check order: each heading must appear after the previous
    positions = [content.index(h) for h in required_headings]
    assert positions == sorted(positions), \
        f"Headings not in expected order. Positions: {dict(zip(required_headings, positions))}"


def test_nonexistent_path_triggers_retry(tmp_repo: Path) -> None:
    """First response citing nonexistent path triggers a retry call to Codex."""
    _create_src_files(tmp_repo)
    run_id = _init_run(tmp_repo, goal="fix bug", slug="retry")
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # First response: cites nonexistent path
    bad_phases_json = json.dumps({
        "phases": [{
            "phase_n": 1,
            "title": "Bad Phase",
            "objective": "Fix things.",
            "scope_hint": "src/",
            "target_files": ["nonexistent/foo.py"],
            "acceptance_criteria": ["pytest src/test_foo.py passes"],
            "testing": {"command": "pytest src/test_foo.py", "expected": "pass"},
            "out_of_scope": [],
            "notes": "",
        }]
    })

    # Second response: cites valid path
    good_phases_json = _valid_phase_json(tmp_repo, phase_n=1, extra_files=["src/foo.py"])
    plan_stub = "# Plan\n\n## Tasks\n1. [ ] fix it\n"

    # Sequence: plan stub, bad phases, good phases (retry response)
    env = _make_stub_sequence(tmp_repo, [plan_stub, bad_phases_json, good_phases_json])

    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    # call_codex must have been called at least twice for the phases part
    # (once for the bad response, once for the retry)
    counter_file = tmp_repo / ".stub_counter_phase_doc"
    call_count = int(counter_file.read_text()) if counter_file.exists() else 0
    # plan stub = 1 call, phases = 1, retry = 1 => total 3
    assert call_count == 3, f"Expected 3 calls (plan + phases + retry), got {call_count}"

    # Final phase doc should NOT include the nonexistent path
    phase_doc = run_dir / "phases" / "phase-01.md"
    assert phase_doc.exists(), "phase-01.md not found"
    content = phase_doc.read_text(encoding="utf-8")
    assert "nonexistent/foo.py" not in content, \
        "Nonexistent path should not appear in final phase doc"


def test_scout_signal_injected_into_prompt(tmp_repo: Path) -> None:
    """The phases prompt passed to Codex must contain file_tree, grep_hits, and headers."""
    _create_src_files(tmp_repo)
    run_id = _init_run(tmp_repo, goal="add caching layer", slug="scouttest")
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # Write a pre-existing plan.md so only the phases call is made
    pre_plan = (
        "---\nauthorized: CLAUDE_X_CODEX_PLAN\n---\n"
        "# Plan: Add caching\n\n"
        "## Tasks\n1. [ ] implement cache\n"
    )
    (run_dir / "plan.md").write_text(pre_plan, encoding="utf-8")

    # Use a capturing stub to record the prompt
    prompt_dir = tmp_repo / "captured_prompts"
    phases_json = _valid_phase_json(tmp_repo, extra_files=["src/foo.py"])
    env = _make_capturing_sequence_stub(tmp_repo, prompt_dir, [phases_json])

    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    # Read the captured prompt (call 0 = first phases call)
    captured = prompt_dir / "0.txt"
    assert captured.exists(), "No captured prompt found"
    prompt_text = captured.read_text(encoding="utf-8")

    # Assert the scout signal markers are present
    assert "file_tree" in prompt_text, "Prompt must contain 'file_tree' scout heading"
    assert "grep_hits" in prompt_text, "Prompt must contain 'grep_hits' scout heading"
    assert "headers" in prompt_text, "Prompt must contain 'headers' scout heading"


def test_lean_plan_template_in_skill_md() -> None:
    """skills/plan/SKILL.md uses lean phase template: has 'Scope hint', no 'Target files:'."""
    skill_md = Path(__file__).resolve().parents[2] / "skills" / "plan" / "SKILL.md"
    assert skill_md.exists(), f"SKILL.md not found at {skill_md}"
    content = skill_md.read_text(encoding="utf-8")

    # Should have Scope hint in the template
    assert "Scope hint" in content, "skills/plan/SKILL.md must contain 'Scope hint'"

    # Should NOT have per-phase "Target files:" as authoring instruction
    assert "Target files:" not in content, \
        "skills/plan/SKILL.md must not contain 'Target files:' as a per-phase authoring instruction"


def test_pre_existing_plan_still_works(tmp_repo: Path) -> None:
    """When plan.md already exists, plan-init should report plan_source == 'pre-existing'."""
    _create_src_files(tmp_repo)
    run_id = _init_run(tmp_repo, goal="improve logging", slug="preexisting")
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # Write a pre-existing plan.md
    pre_plan = (
        "---\nauthorized: CLAUDE_X_CODEX_PLAN\n---\n"
        "# Plan: Improve logging\n\n"
        "## Goal\nAdd better logging.\n\n"
        "## Tasks\n1. [ ] add log calls\n"
    )
    (run_dir / "plan.md").write_text(pre_plan, encoding="utf-8")

    phases_json = _valid_phase_json(tmp_repo, extra_files=["src/foo.py"])
    env = _make_stub_sequence(tmp_repo, [phases_json])

    r = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    out = json.loads(r.stdout)
    assert out.get("plan_source") == "pre-existing", \
        f"Expected plan_source='pre-existing', got {out.get('plan_source')!r}"

    # Verify phases were generated
    assert "phases" in out
    assert len(out["phases"]) >= 1

    # plan.md content must be unchanged
    plan_content = (run_dir / "plan.md").read_text(encoding="utf-8")
    assert "Improve logging" in plan_content, "plan.md content must not be overwritten"
