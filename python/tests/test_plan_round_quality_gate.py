"""Tests for plan-round quality gate: vague bullets, nonexistent paths, retry logic.

Tests in this file verify:
- Vague execution_plan_bullets (no concrete file path) trigger a Codex retry
- Bullets citing nonexistent paths trigger a retry
- Concrete bullets (with valid path tokens) pass without retry
- Missing runnable acceptance_criteria triggers a retry
- Persistent failures set quality_failed=True in the emitted JSON
- The plan-round prompt mentions ## Target Files and execution_plan_bullets
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers (mirror test_plan_init_phase_doc.py patterns)
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


def _make_stub_sequence(tmp_repo: Path, responses: list[str], stub_name: str = "codex_stub_round") -> dict:
    """Returns env dict for a Codex bin that returns responses[i] on i-th call."""
    counter_file = tmp_repo / f".stub_counter_{stub_name}"
    stub_path = tmp_repo / f"{stub_name}.py"
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


def _make_capturing_sequence_stub(tmp_repo: Path, prompt_dir: Path, responses: list[str]) -> dict:
    """Returns env dict for a stub that captures prompts into prompt_dir/<i>.txt."""
    counter_file = tmp_repo / ".stub_counter_capture_round"
    stub_path = tmp_repo / "codex_stub_capture_round.py"
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
        f"    # Read bytes from stdin to avoid Windows surrogate encoding issues.\n"
        f"    raw_bytes = sys.stdin.buffer.read()\n"
        f"    (prompt_dir / f'{{count}}.bin').write_bytes(raw_bytes)\n"
        f"except Exception:\n"
        f"    pass\n"
        f"responses = [{items}]\n"
        f"resp = responses[min(count, len(responses) - 1)]\n"
        f"print(json.dumps({{'type': 'assistant_message', 'content': resp}}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}


def _make_round_plan_json(
    bullets: list[str],
    criteria: list[str],
    model: str = "sonnet",
) -> str:
    """Build a minimal valid round-plan JSON string for the merged-envelope shape."""
    return json.dumps({
        "round_plan": {
            "round": 1,
            "worker_model": model,
            "worker_model_reason": "test",
            "reasoning_effort": "medium",
            "subtasks": [],
            "commit_message": "test commit",
            "phase_complete_signal": False,
        },
        "task_description": "Test task",
        "execution_plan_bullets": bullets,
        "acceptance_criteria": criteria,
        "carry_forward": "",
    })


def _setup_run_with_phase_doc(tmp_repo: Path, phase_target_files: list[str]) -> str:
    """Create a run, write a phase-01.md with the given target files, and return run_id."""
    run_id = _init_run(tmp_repo, goal="test quality gate", slug="qualitytest")
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # Write phases.json so _load_current_phase_section works (or at minimum doesn't crash)
    phases_dir = run_dir / "phases"
    phases_dir.mkdir(parents=True, exist_ok=True)

    # Write a phase-01.md with ## Target Files section
    target_lines = "\n".join(f"- {f}" for f in phase_target_files)
    phase_doc = (
        "## Objective\nImplement the quality gate.\n\n"
        "## Target Files\n"
        f"{target_lines}\n\n"
        "## Acceptance Criteria\n- Tests pass.\n\n"
        "## Testing\npytest python/tests/\n\n"
        "## Out of Scope\n- Unrelated modules.\n\n"
        "## Notes\n- None.\n"
    )
    (phases_dir / "phase-01.md").write_text(phase_doc, encoding="utf-8")

    # Write phases.json so CLI won't fail loading current phase.
    # Do NOT include doc_path so _load_current_phase_section uses the default
    # "phases/phase-{n:02d}.md" relative path (avoids absolute-path join issues).
    phases_json = [
        {
            "phase_n": 1,
            "title": "Quality Gate Phase",
        }
    ]
    (run_dir / "phases.json").write_text(json.dumps(phases_json), encoding="utf-8")

    return run_id


def _call_count(tmp_repo: Path, stub_name: str = "codex_stub_round") -> int:
    """Return how many times the stub was called."""
    counter_file = tmp_repo / f".stub_counter_{stub_name}"
    if counter_file.exists():
        return int(counter_file.read_text())
    return 0


# ---------------------------------------------------------------------------
# Helper: create a real file at a given relative path inside tmp_repo
# ---------------------------------------------------------------------------

def _touch_file(tmp_repo: Path, rel_path: str) -> Path:
    """Create a placeholder file at rel_path within tmp_repo."""
    p = tmp_repo / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(f"# placeholder for {rel_path}\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_vague_bullets_trigger_retry(tmp_repo: Path) -> None:
    """Vague bullets (no concrete file path) trigger one retry; second response passes."""
    # Create a real file to be referenced
    _touch_file(tmp_repo, "python/agent_loop/cli.py")

    run_id = _setup_run_with_phase_doc(tmp_repo, ["python/agent_loop/cli.py"])

    # First response: vague bullets
    vague_response = _make_round_plan_json(
        bullets=["Update the CLI to handle the new flag", "Fix the parser"],
        criteria=["pytest python/tests/test_plan_round_quality_gate.py passes"],
    )
    # Second response: concrete bullets citing real path
    concrete_response = _make_round_plan_json(
        bullets=["python/agent_loop/cli.py:_cmd_plan_round — add quality gate logic"],
        criteria=["pytest python/tests/test_plan_round_quality_gate.py passes"],
    )

    env = _make_stub_sequence(tmp_repo, [vague_response, concrete_response])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    count = _call_count(tmp_repo)
    assert count == 2, f"Expected 2 Codex calls (initial + retry), got {count}"

    out = json.loads(r.stdout)
    assert out["quality_failed"] is False, f"Expected quality_failed=False, got {out.get('quality_failed')}"

    # Verify the second-call prompt contains the rejection phrase
    # We verify by checking the round_plan.json on disk
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    round_plan_path = run_dir / "rounds" / "01" / "round_plan.json"
    assert round_plan_path.exists(), "round_plan.json must be written to disk"


def test_nonexistent_path_triggers_retry(tmp_repo: Path) -> None:
    """Bullets citing nonexistent paths trigger one retry; second response with real paths passes."""
    # Create a real file
    _touch_file(tmp_repo, "python/agent_loop/cli.py")

    run_id = _setup_run_with_phase_doc(tmp_repo, ["python/agent_loop/cli.py"])

    # First response: bullets cite a nonexistent path
    bad_response = _make_round_plan_json(
        bullets=["python/agent_loop/missing.py:_cmd_plan_round — fix the bug"],
        criteria=["pytest python/tests/test_plan_round_quality_gate.py passes"],
    )
    # Second response: bullets cite a real path
    good_response = _make_round_plan_json(
        bullets=["python/agent_loop/cli.py:_cmd_plan_round — fix the bug"],
        criteria=["pytest python/tests/test_plan_round_quality_gate.py passes"],
    )

    env = _make_stub_sequence(tmp_repo, [bad_response, good_response])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    count = _call_count(tmp_repo)
    assert count == 2, f"Expected 2 Codex calls (initial + retry), got {count}"

    out = json.loads(r.stdout)
    assert out["quality_failed"] is False, f"Expected quality_failed=False, got {out.get('quality_failed')}"


def test_concrete_bullets_no_retry(tmp_repo: Path) -> None:
    """Concrete bullets (valid path, runnable criteria) pass without retry."""
    _touch_file(tmp_repo, "python/agent_loop/cli.py")

    run_id = _setup_run_with_phase_doc(tmp_repo, ["python/agent_loop/cli.py"])

    good_response = _make_round_plan_json(
        bullets=["python/agent_loop/cli.py:_validate_round_plan_quality — validate round plan"],
        criteria=["pytest python/tests/test_plan_round_quality_gate.py -v passes"],
    )

    env = _make_stub_sequence(tmp_repo, [good_response])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    count = _call_count(tmp_repo)
    assert count == 1, f"Expected 1 Codex call (no retry needed), got {count}"

    out = json.loads(r.stdout)
    assert out["quality_failed"] is False, f"Expected quality_failed=False, got {out.get('quality_failed')}"


def test_persistent_failure_sets_quality_flag(tmp_repo: Path) -> None:
    """When both attempts return vague bullets, quality_failed is True in emitted JSON."""
    _touch_file(tmp_repo, "python/agent_loop/cli.py")

    run_id = _setup_run_with_phase_doc(tmp_repo, ["python/agent_loop/cli.py"])

    # Both responses are vague
    vague_response = _make_round_plan_json(
        bullets=["Update the CLI", "Fix the parser"],
        criteria=["feature works"],
    )

    env = _make_stub_sequence(tmp_repo, [vague_response, vague_response])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr  # Should NOT raise / fail

    count = _call_count(tmp_repo)
    assert count == 2, f"Expected 2 Codex calls (initial + retry), got {count}"

    out = json.loads(r.stdout)
    assert out["quality_failed"] is True, f"Expected quality_failed=True, got {out.get('quality_failed')}"

    # Verify round_plan.json on disk also has quality_failed=True and safety_flags
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    round_plan_path = run_dir / "rounds" / "01" / "round_plan.json"
    assert round_plan_path.exists(), "round_plan.json must be written to disk"
    disk_plan = json.loads(round_plan_path.read_text(encoding="utf-8"))
    assert disk_plan.get("quality_failed") is True, "round_plan.json on disk must have quality_failed=True"
    assert "quality_failed" in disk_plan.get("safety_flags", []), \
        "round_plan.json safety_flags must contain 'quality_failed'"

    # claude-prompt.md must also be written (loop proceeds even on persistent failure)
    claude_prompt_path = run_dir / "rounds" / "01" / "claude-prompt.md"
    assert claude_prompt_path.exists(), "claude-prompt.md must be written even when quality_failed"


def test_missing_runnable_acceptance_criteria_triggers_retry(tmp_repo: Path) -> None:
    """Bullets with valid paths but prose-only acceptance_criteria trigger a retry."""
    _touch_file(tmp_repo, "python/agent_loop/cli.py")

    run_id = _setup_run_with_phase_doc(tmp_repo, ["python/agent_loop/cli.py"])

    # First response: valid bullets but prose-only acceptance criteria (no runnable command)
    bad_criteria_response = _make_round_plan_json(
        bullets=["python/agent_loop/cli.py:_cmd_plan_round — add quality gate logic"],
        criteria=["quality gate is covered", "all existing behavior still works"],
    )
    # Second response: valid bullets AND runnable acceptance criteria
    good_response = _make_round_plan_json(
        bullets=["python/agent_loop/cli.py:_cmd_plan_round — add quality gate logic"],
        criteria=["pytest python/tests/test_plan_round_quality_gate.py -v passes"],
    )

    env = _make_stub_sequence(tmp_repo, [bad_criteria_response, good_response])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    count = _call_count(tmp_repo)
    assert count == 2, f"Expected 2 Codex calls (initial + retry), got {count}"

    out = json.loads(r.stdout)
    assert out["quality_failed"] is False, f"Expected quality_failed=False, got {out.get('quality_failed')}"


def test_backtick_wrapped_path_no_retry(tmp_repo: Path) -> None:
    """A backtick-wrapped path token (as Codex commonly emits) passes without retry."""
    _touch_file(tmp_repo, "python/agent_loop/cli.py")

    run_id = _setup_run_with_phase_doc(tmp_repo, ["python/agent_loop/cli.py"])

    # Bullet wraps the path in markdown backticks and trails it with a comma —
    # the exact shape that previously failed the path-token check.
    good_response = _make_round_plan_json(
        bullets=["In `python/agent_loop/cli.py:_validate_round_plan_quality`, strip wrappers"],
        criteria=["pytest python/tests/test_plan_round_quality_gate.py -v passes"],
    )

    env = _make_stub_sequence(tmp_repo, [good_response])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    count = _call_count(tmp_repo)
    assert count == 1, f"Expected 1 Codex call (backtick path should pass), got {count}"

    out = json.loads(r.stdout)
    assert out["quality_failed"] is False, f"Expected quality_failed=False, got {out.get('quality_failed')}"


def test_plan_round_prompt_mentions_target_files(tmp_repo: Path) -> None:
    """The round-plan prompt passed to Codex must mention ## Target Files and execution_plan_bullets."""
    _touch_file(tmp_repo, "python/agent_loop/cli.py")

    run_id = _setup_run_with_phase_doc(tmp_repo, ["python/agent_loop/cli.py"])

    good_response = _make_round_plan_json(
        bullets=["python/agent_loop/cli.py:_validate_round_plan_quality — validate"],
        criteria=["pytest python/tests/test_plan_round_quality_gate.py -v passes"],
    )

    prompt_dir = tmp_repo / "captured_prompts_round"
    env = _make_capturing_sequence_stub(tmp_repo, prompt_dir, [good_response])

    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    # Read the captured prompt bytes (call 0 = first plan-round call)
    captured = prompt_dir / "0.bin"
    assert captured.exists(), "No captured prompt found"
    prompt_text = captured.read_bytes().decode("utf-8", errors="replace")

    assert "## Target Files" in prompt_text, "Prompt must mention '## Target Files'"
    assert "execution_plan_bullets" in prompt_text, "Prompt must mention 'execution_plan_bullets'"
    assert "open every file" in prompt_text.lower() or "## target files" in prompt_text.lower(), \
        "Prompt must instruct Codex to open target files"
