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


def _codex_stub_sequence(tmp_repo: Path, contents: list[str]) -> dict[str, str]:
    stub_path = tmp_repo / "codex_stub_sequence.py"
    data_path = tmp_repo / "codex_stub_sequence.json"
    data_path.write_text(json.dumps({"i": 0, "contents": contents}), encoding="utf-8")
    stub_path.write_text(
        "import json\n"
        f"p = {str(data_path)!r}\n"
        "data = json.load(open(p, encoding='utf-8'))\n"
        "i = data['i']\n"
        "content = data['contents'][i]\n"
        "data['i'] = i + 1\n"
        "json.dump(data, open(p, 'w', encoding='utf-8'))\n"
        "print(json.dumps({'type': 'assistant_message', 'content': content}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}


def _merged_envelope(round_n=1, worker_model="haiku", reason="single file mechanical change",
                     reasoning_effort="low", subtasks=None,
                     task_description="", execution_plan_bullets=None,
                     acceptance_criteria=None, carry_forward="") -> str:
    """Build a merged envelope JSON string (A1 single-call format)."""
    env = {
        "round_plan": {
            "round": round_n,
            "worker_model": worker_model,
            "worker_model_reason": reason,
            "reasoning_effort": reasoning_effort,
            "subtasks": subtasks or [],
        },
        "task_description": task_description,
        "execution_plan_bullets": execution_plan_bullets or [],
        "acceptance_criteria": acceptance_criteria or [],
        "carry_forward": carry_forward,
    }
    return json.dumps(env)


def test_plan_round_creates_round_dir_and_prompt(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]
    # write a fake plan first
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n2. [ ] do B\n", encoding="utf-8")

    # A1: single merged envelope call
    env = _codex_stub_sequence(tmp_repo, [
        _merged_envelope(
            round_n=1, worker_model="haiku", reason="single file mechanical change",
            reasoning_effort="low", task_description="Implement A",
        ),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["round_n"] == 1
    assert js["worker_model"] == "haiku"
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round-plan.json"
    rp_canon = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    assert pr.exists()
    assert rp.exists(), "compat alias round-plan.json must exist"
    assert rp_canon.exists(), "canonical round_plan.json must exist"
    assert json.loads(rp.read_text(encoding="utf-8"))["worker_model"] == "haiku"
    assert "Implement A" in pr.read_text(encoding="utf-8")


def test_plan_round_normalizes_invalid_worker_model(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    # A1: single merged envelope; invalid worker_model must be normalized
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round_plan": {
                "round": 1,
                "worker_model": "mega-opus",  # invalid -> normalized to default (sonnet)
                "worker_model_reason": "invalid",
                "reasoning_effort": "medium",
                "subtasks": [],
            },
            "task_description": "Implement A",
            "execution_plan_bullets": [],
            "acceptance_criteria": [],
            "carry_forward": "",
        }),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["worker_model"] == "sonnet"
    # scope key must NOT be present after C1a
    assert "scope" not in js
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round-plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    assert plan_json["worker_model"] == "sonnet"
    assert "scope" not in plan_json




def test_plan_round_survives_backslashes_in_worker_model_reason(tmp_repo: Path) -> None:
    """Codex-supplied ``worker_model_reason`` containing backslashes (e.g. a
    Windows path) must not crash ``plan-round``. Round 1 used the reason as a
    regex replacement template; ``re.sub`` would then interpret ``\\U`` /
    ``\\1`` style escapes and raise. The fix passes a callable replacement so
    the reason is treated as literal text.
    """
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    reason = r"touches C:\Users\foo\bar and group \1 matches"
    # A1: single merged envelope
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round_plan": {
                "round": 1,
                "worker_model": "haiku",
                "worker_model_reason": reason,
                "reasoning_effort": "low",
                "subtasks": [],
            },
            "task_description": "Do A",
            "execution_plan_bullets": [],
            "acceptance_criteria": [],
            "carry_forward": "",
        }),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    # Reason is preserved verbatim (backslashes intact) in the round plan JSON.
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    assert plan_json["worker_model_reason"] == reason


def test_plan_round_collapses_multiline_worker_model_reason(tmp_repo: Path) -> None:
    """A multiline reason must not inject extra ``##`` headings.
    We collapse the reason to one whitespace-separated line before storing and rendering it.
    """
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    multiline_reason = "first line of reason\n## Injected Heading\nstill same reason"
    # A1: single merged envelope
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round_plan": {
                "round": 1,
                "worker_model": "sonnet",
                "worker_model_reason": multiline_reason,
                "reasoning_effort": "medium",
                "subtasks": [],
            },
            "task_description": "Do A",
            "execution_plan_bullets": [],
            "acceptance_criteria": [],
            "carry_forward": "",
        }),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    # round-plan.json stores the collapsed (single-line) form.
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round-plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    stored_reason = plan_json["worker_model_reason"]
    assert "\n" not in stored_reason
    assert "## Injected Heading" in stored_reason  # text preserved, just inlined


def test_plan_round_handles_non_json_model_selection(tmp_repo: Path) -> None:
    """If Codex returns garbage for the merged envelope call, plan-round must
    still produce a usable prompt with the default model."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    # B1: non-JSON triggers parse_failed
    env = _codex_stub_sequence(tmp_repo, [
        "not json at all -- the model returned prose",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["worker_model"] == "sonnet"  # config default
    # C1a: no scope key in output
    assert "scope" not in js
    # B1: round_plan.json must have parse_failed=True
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    assert plan_json.get("parse_failed") is True


def test_plan_round_parses_and_persists_subtasks(tmp_repo: Path) -> None:
    """When Codex emits a valid subtasks array, plan-round must normalize and
    persist them in round_plan.json and inject a readable block into the prompt."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    subtasks = [
        {
            "id": "r1-i1",
            "role": "implementation",
            "model": "haiku",
            "reasoning_effort": "low",
            "description": "Map CLI entry points",
            "required_reading": ["python/agent_loop/cli.py"],
            "out_of_scope": [".git/"],
            "depends_on": [],
            "deliverable": "Append findings to shared/knowledge.md",
        },
        {
            "id": "r1-i2",
            "role": "implementation",
            "model": "sonnet",
            "reasoning_effort": "medium",
            "description": "Implement subtask parsing",
            "required_reading": ["python/agent_loop/cli.py"],
            "out_of_scope": [".git/"],
            "depends_on": ["r1-i1"],
            "deliverable": "Pass tests for subtask normalization",
        },
    ]
    # A1: single merged envelope
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round_plan": {
                "round": 1,
                "worker_model": "sonnet",
                "worker_model_reason": "integration work",
                "reasoning_effort": "medium",
                "subtasks": subtasks,
            },
            "task_description": "Implement subtask parsing",
            "execution_plan_bullets": ["Edit cli.py"],
            "acceptance_criteria": ["Tests pass"],
            "carry_forward": "",
        }),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["subtask_count"] == 2
    assert len(js["subtasks"]) == 2
    assert js["subtasks"][0]["id"] == "r1-i1"
    assert js["subtasks"][0]["role"] == "implementation"
    assert js["subtasks"][1]["id"] == "r1-i2"
    assert js["subtasks"][1]["depends_on"] == ["r1-i1"]

    # round_plan.json must include normalized subtasks
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    assert rp.exists(), "round_plan.json (canonical name) must exist"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    assert "subtasks" in plan_json
    assert len(plan_json["subtasks"]) == 2

    # C1a: no complexity or scope keys in round_plan.json
    assert "complexity" not in plan_json
    assert "scope" not in plan_json

    # Compatibility alias must also exist
    rp_compat = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round-plan.json"
    assert rp_compat.exists(), "round-plan.json (compat alias) must exist"

    # Prompt must include the subtask block
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    prompt_text = pr.read_text(encoding="utf-8")
    assert "### Subtasks (this round)" in prompt_text
    assert "r1-i1" in prompt_text
    assert "r1-i2" in prompt_text
    assert "implementation" in prompt_text


def test_plan_round_normalizes_invalid_subtask_fields(tmp_repo: Path) -> None:
    """Invalid per-subtask model or reasoning_effort must fall back to safe defaults
    without crashing plan-round."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    bad_subtasks = [
        {
            "id": "r1-bad",
            "role": "unknown-role",       # invalid role -> normalized to implementation
            "model": "mega-ultra-opus",   # invalid model -> normalized to default (sonnet)
            "reasoning_effort": "extreme", # invalid effort -> role-aware default
            "description": "bad subtask",
            "required_reading": [],
            "out_of_scope": [],
            "depends_on": [],
            "deliverable": "do something",
        },
    ]
    # A1: single merged envelope
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round_plan": {
                "round": 1,
                "worker_model": "sonnet",
                "worker_model_reason": "test",
                "reasoning_effort": "medium",
                "subtasks": bad_subtasks,
            },
            "task_description": "Implement A",
            "execution_plan_bullets": [],
            "acceptance_criteria": [],
            "carry_forward": "",
        }),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    st = plan_json["subtasks"][0]
    assert st["role"] == "implementation"   # unknown-role -> implementation
    assert st["model"] == "sonnet"          # invalid model -> default
    # C1a: no scope key in subtask
    assert "scope" not in st
    assert st["reasoning_effort"] in ("low", "medium", "high")  # valid effort


def test_plan_round_missing_subtasks_triggers_empty_list(tmp_repo: Path) -> None:
    """When Codex omits subtasks entirely, plan-round must persist an empty
    subtasks list (not crash) and not inject a subtask block into the prompt."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    # A1: single merged envelope, subtasks deliberately omitted
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round_plan": {
                "round": 1,
                "worker_model": "haiku",
                "worker_model_reason": "mechanical",
                "reasoning_effort": "low",
                # subtasks deliberately omitted
            },
            "task_description": "Implement A",
            "execution_plan_bullets": [],
            "acceptance_criteria": [],
            "carry_forward": "",
        }),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["subtask_count"] == 0
    assert js["subtasks"] == []

    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    assert plan_json["subtasks"] == []

    # No subtask block should appear in the prompt
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    prompt_text = pr.read_text(encoding="utf-8")
    assert "### Subtasks (this round)" not in prompt_text


def test_plan_round_prompt_asks_codex_for_subtasks(tmp_repo: Path) -> None:
    """The round plan Codex prompt must include 'subtasks' in its schema so Codex
    knows to produce subtask decomposition. This test verifies the schema wording
    by checking that the CLI exits successfully and the persisted plan has the key."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    # A1: single merged envelope with a verification subtask
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round_plan": {
                "round": 1,
                "worker_model": "sonnet",
                "worker_model_reason": "test",
                "reasoning_effort": "medium",
                "subtasks": [
                    {
                        "id": "r1-v1",
                        "role": "verification",
                        "model": "haiku",
                        "reasoning_effort": "low",
                        "description": "Run tests",
                        "required_reading": [],
                        "out_of_scope": [],
                        "depends_on": [],
                        "deliverable": "Run: python -m pytest tests/ -x and report pass/fail",
                    }
                ],
            },
            "task_description": "Run verification",
            "execution_plan_bullets": [],
            "acceptance_criteria": [],
            "carry_forward": "",
        }),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    # The key must be present (Codex was asked for it; stub provided it)
    assert "subtasks" in plan_json
    assert plan_json["subtasks"][0]["role"] == "verification"


def test_plan_round_respects_custom_allowed_efforts(tmp_repo: Path) -> None:
    """Custom [worker_reasoning].allowed in repo config must be enforced.
    When a custom allowed list removes 'medium', an invalid effort value must
    fall back to the config default in round_plan.json."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    # Create a custom config that allows only ["low", "high"] (no "medium")
    # and sets default to "low".
    config_dir = tmp_repo / ".agent-loop"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    config_path.write_text(
        '[worker_reasoning]\n'
        'allowed = ["low", "high"]\n'
        'default = "low"\n',
        encoding="utf-8"
    )

    # A1: single merged envelope; Codex returns reasoning_effort="medium" (no longer allowed)
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round_plan": {
                "round": 1,
                "worker_model": "haiku",
                "worker_model_reason": "mechanical change",
                "reasoning_effort": "medium",  # invalid under custom config
                "subtasks": [],
            },
            "task_description": "Implement A",
            "execution_plan_bullets": [],
            "acceptance_criteria": [],
            "carry_forward": "",
        }),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    # The round_plan.json should show the invalid "medium" was normalized to
    # the custom default "low" by _parse_round_plan.
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    assert plan_json["reasoning_effort"] == "low"


# ---------------------------------------------------------------------------
# New acceptance-criteria tests
# ---------------------------------------------------------------------------

def test_plan_round_single_codex_call(tmp_repo: Path) -> None:
    """A1: plan-round must make exactly ONE Codex call per round (merged envelope).

    The stub is configured with two entries; if a second call is made the stub
    counter advances and the test can detect it by checking that the data_path
    counter == 1 after the run.
    """
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    # Provide two entries; only the first should be consumed.
    env = _codex_stub_sequence(tmp_repo, [
        _merged_envelope(
            round_n=1, worker_model="haiku", reason="mechanical",
            reasoning_effort="low", task_description="Implement A",
        ),
        "SHOULD_NOT_BE_CALLED",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    # Check stub counter: index should be 1 (only first entry consumed)
    data_path = tmp_repo / "codex_stub_sequence.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    assert data["i"] == 1, f"Expected exactly 1 Codex call but stub index is {data['i']}"

    # Both round_plan.json and claude-prompt.md should be populated
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    assert rp.exists()
    assert pr.exists()
    assert json.loads(rp.read_text(encoding="utf-8"))["worker_model"] == "haiku"
    assert "Implement A" in pr.read_text(encoding="utf-8")


def test_plan_round_deterministic_sections_present(tmp_repo: Path) -> None:
    """A2: claude-prompt.md must contain deterministic sections regardless of
    what Codex content fields provide (including minimal/empty content fields)."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    # Minimal content fields: task_description empty, no bullets
    env = _codex_stub_sequence(tmp_repo, [
        _merged_envelope(
            round_n=1, worker_model="sonnet", reason="test",
            reasoning_effort="medium", task_description="",
        ),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    prompt_text = pr.read_text(encoding="utf-8")

    # These deterministic sections must always appear
    assert "## Goal" in prompt_text
    assert "## Required Reading" in prompt_text
    assert "## Out of Scope" in prompt_text
    assert "## Forbidden Actions" in prompt_text
    assert "## Mandatory Outputs" in prompt_text
    assert "## Reading List Discipline" in prompt_text


def test_parse_round_plan_no_complexity_key() -> None:
    """A3: _parse_round_plan must never include a 'complexity' key in the result."""
    from agent_loop.cli import _parse_round_plan

    # Legacy flat format with complexity block
    raw_with_complexity = json.dumps({
        "round": 1,
        "worker_model": "haiku",
        "worker_model_reason": "test",
        "reasoning_effort": "low",
        "complexity": {
            "files_expected": 1,
            "requires_architecture": False,
            "risk": "low",
        },
    })
    result = _parse_round_plan(
        raw_with_complexity,
        round_n=1,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
    )
    assert "complexity" not in result, f"'complexity' should not be in result but got keys: {list(result.keys())}"

    # Merged envelope format with complexity in round_plan
    raw_merged = json.dumps({
        "round_plan": {
            "round": 1,
            "worker_model": "sonnet",
            "worker_model_reason": "test",
            "reasoning_effort": "medium",
            "complexity": {"files_expected": 5, "risk": "high"},
        },
        "task_description": "Do work",
        "execution_plan_bullets": [],
        "acceptance_criteria": [],
        "carry_forward": "",
    })
    result2 = _parse_round_plan(
        raw_merged,
        round_n=1,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
    )
    assert "complexity" not in result2


def test_bounded_memo_limits_rounds() -> None:
    """A4: _bounded_memo with a 5-round memo returns only the last 3 rounds.
    With a 2-round memo, all rounds are returned."""
    from agent_loop.cli import _bounded_memo

    def make_memo(n: int) -> str:
        header = "# Round Memos\n\n"
        rounds = "\n\n".join(
            f"## Round {i}\n- Goal progress: done round {i}" for i in range(1, n + 1)
        )
        return header + rounds + "\n"

    # 5-round memo -> only last 3
    memo5 = make_memo(5)
    bounded = _bounded_memo(memo5, max_rounds=3)
    assert "## Round 3" in bounded
    assert "## Round 4" in bounded
    assert "## Round 5" in bounded
    assert "## Round 1" not in bounded
    assert "## Round 2" not in bounded

    # 2-round memo -> all returned (no truncation)
    memo2 = make_memo(2)
    bounded2 = _bounded_memo(memo2, max_rounds=3)
    assert "## Round 1" in bounded2
    assert "## Round 2" in bounded2


def test_parse_round_plan_parse_failed_flag() -> None:
    """B1: When Codex returns invalid JSON, parse_failed must be True in result."""
    from agent_loop.cli import _parse_round_plan

    result = _parse_round_plan(
        "not valid json at all",
        round_n=1,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
    )
    assert result.get("parse_failed") is True
    # Defaults should still be usable
    assert result["worker_model"] == "sonnet"

    # Also assert that a dict envelope with a non-dict round_plan yields parse_failed.
    import json as _json
    for bad_value in [["list", "not", "dict"], None, "oops", 42]:
        envelope = _json.dumps({"round_plan": bad_value})
        r = _parse_round_plan(
            envelope,
            round_n=1,
            allowed_models=["haiku", "sonnet", "opus"],
            default_model="sonnet",
        )
        assert r.get("parse_failed") is True, (
            f"Expected parse_failed=True for round_plan={bad_value!r}, got {r.get('parse_failed')}"
        )
        assert r["worker_model"] == "sonnet"


def test_parse_round_plan_inner_non_dict_round_plan() -> None:
    """B1 regression: a merged envelope with a non-dict round_plan must set
    parse_failed=True instead of silently defaulting (using envelope as plan)."""
    import json as _json
    from agent_loop.cli import _parse_round_plan

    # round_plan as a list
    raw_list = _json.dumps({"round_plan": ["list", "not", "dict"]})
    result = _parse_round_plan(
        raw_list,
        round_n=2,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
    )
    assert result.get("parse_failed") is True, "list round_plan must set parse_failed=True"
    assert result["worker_model"] == "sonnet"

    # round_plan as null
    raw_null = _json.dumps({"round_plan": None})
    result = _parse_round_plan(
        raw_null,
        round_n=2,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
    )
    assert result.get("parse_failed") is True, "null round_plan must set parse_failed=True"

    # round_plan as a string
    raw_str = _json.dumps({"round_plan": "oops"})
    result = _parse_round_plan(
        raw_str,
        round_n=2,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
    )
    assert result.get("parse_failed") is True, "string round_plan must set parse_failed=True"


def test_review_round_surfaces_parse_failure_flag(tmp_repo: Path, codex_stub) -> None:
    """B1: When plan-round has parse_failed=True, review-round must include
    'round_plan_parse_failed' in safety_flags."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    plan = run_dir / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    # plan-round with invalid JSON
    env_plan = _codex_stub_sequence(tmp_repo, [
        "not json at all -- triggers parse_failed",
    ])
    r_plan = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env_plan)
    assert r_plan.returncode == 0, r_plan.stderr

    # Verify parse_failed is set
    rp = run_dir / "rounds" / "01" / "round_plan.json"
    rp_data = json.loads(rp.read_text(encoding="utf-8"))
    assert rp_data.get("parse_failed") is True

    _run(["mark-dispatched", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    _run(["mark-worker-done", "--run", run_id, "--round", "1"], cwd=tmp_repo)

    # Capture baseline and record-diff so review-round has all artifacts
    r_base = _run(["capture-baseline"], cwd=tmp_repo)
    baseline = json.loads(r_base.stdout)["baseline"]
    _run(["record-diff", "--run", run_id, "--round", "1", "--baseline", baseline], cwd=tmp_repo)

    # Run review-round
    review_body = (
        "# Codex Review -- Round 1\n\n## Decision\nSTOP_FOR_USER\n\n"
        "## Goal Alignment\nParse failed.\n\n## Findings\n- none\n\n"
        "## Verification\n- Tests: pass\n\n## Risks\n- none\n\n"
        "## Carry-Forward For Next Round\n- retry\n"
    )
    env_review = codex_stub(review_body)
    r_review = _run(["review-round", "--run", run_id, "--round", "1"],
                    cwd=tmp_repo, env_overrides=env_review)
    assert r_review.returncode == 0, r_review.stderr

    review_out = json.loads(r_review.stdout)
    assert "round_plan_parse_failed" in review_out.get("safety_flags", []), \
        f"Expected 'round_plan_parse_failed' in safety_flags but got: {review_out.get('safety_flags')}"


def test_normalize_subtask_opus_empty_description_downgrade() -> None:
    """B2: A subtask with model='opus' and empty description must be downgraded
    to the default model, and normalized_notes must record the downgrade."""
    from agent_loop.cli import _normalize_subtask

    result = _normalize_subtask(
        {"id": "r1-i1", "role": "implementation", "model": "opus",
         "reasoning_effort": "high", "description": "",  # empty!
         "deliverable": "", "required_reading": [], "out_of_scope": [], "depends_on": []},
        idx=0,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
        allowed_efforts=["low", "medium", "high"],
        default_effort="medium",
    )
    assert result["model"] == "sonnet", f"Expected downgrade to sonnet but got {result['model']}"
    assert "opus_downgraded_no_description" in result["normalized_notes"]


def test_normalize_subtask_opus_blank_description_nonempty_deliverable() -> None:
    """B2 regression: A subtask with model='opus', blank description, but non-empty
    deliverable must still be downgraded to the default model.

    Before the fix, description was filled from deliverable BEFORE the downgrade
    check, causing the downgrade to be skipped when deliverable was non-empty.
    """
    from agent_loop.cli import _normalize_subtask

    result = _normalize_subtask(
        {"id": "r1-i1", "role": "implementation", "model": "opus",
         "reasoning_effort": "high", "description": "",  # blank raw description
         "deliverable": "Append findings to shared/knowledge.md",  # non-empty deliverable
         "required_reading": [], "out_of_scope": [], "depends_on": []},
        idx=0,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
        allowed_efforts=["low", "medium", "high"],
        default_effort="medium",
    )
    assert result["model"] == "sonnet", (
        f"Expected downgrade to sonnet but got {result['model']!r} — "
        "opus with blank raw description must be downgraded even if deliverable is non-empty"
    )
    assert "opus_downgraded_no_description" in result["normalized_notes"], (
        f"normalized_notes should record the downgrade, got: {result['normalized_notes']}"
    )


def test_normalize_subtask_default_description_uses_id() -> None:
    """B2: When no description or deliverable is supplied, the fallback
    description must be '<id> (no description supplied)', NOT 'complete the assigned task'."""
    from agent_loop.cli import _normalize_subtask

    result = _normalize_subtask(
        {"id": "r1-x1", "role": "implementation", "model": "sonnet",
         "reasoning_effort": "medium", "description": "", "deliverable": "",
         "required_reading": [], "out_of_scope": [], "depends_on": []},
        idx=0,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
        allowed_efforts=["low", "medium", "high"],
        default_effort="medium",
    )
    assert result["description"] == "r1-x1 (no description supplied)"
    assert "complete the assigned task" not in result["description"]


def test_normalize_subtasks_drops_reverse_edges() -> None:
    """B2: A verification subtask that depends_on a later verification subtask
    is a reverse-direction edge and must be dropped (with a normalized_notes record)."""
    from agent_loop.cli import _normalize_subtasks

    raw = [
        {"id": "r1-i1", "role": "implementation", "model": "sonnet",
         "reasoning_effort": "medium", "description": "do work",
         "required_reading": [], "out_of_scope": [], "depends_on": [],
         "deliverable": "write code"},
        {"id": "r1-v1", "role": "verification", "model": "haiku",
         "reasoning_effort": "low", "description": "run tests",
         "required_reading": [], "out_of_scope": [],
         "depends_on": ["r1-v2"],  # reverse: v1 depending on v2 (which comes after)
         "deliverable": "report pass/fail"},
        {"id": "r1-v2", "role": "verification", "model": "haiku",
         "reasoning_effort": "low", "description": "run more tests",
         "required_reading": [], "out_of_scope": [],
         "depends_on": ["r1-v1"],
         "deliverable": "report pass/fail"},
    ]
    result = _normalize_subtasks(
        raw,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
        allowed_efforts=["low", "medium", "high"],
        default_effort="medium",
    )
    v1 = next(st for st in result if st["id"] == "r1-v1")
    v2 = next(st for st in result if st["id"] == "r1-v2")
    all_notes = v1["normalized_notes"] + v2["normalized_notes"]
    # Cycle must be broken: both cannot simultaneously depend on each other
    assert not (("r1-v2" in v1["depends_on"]) and ("r1-v1" in v2["depends_on"])), \
        "Cycle not broken: both subtasks still depend on each other"
    # normalized_notes must record the drop
    assert any("dropped_cycle_edge" in note or "dropped_reverse_edge" in note for note in all_notes), \
        f"Expected dropped edge note but got v1={v1['normalized_notes']} v2={v2['normalized_notes']}"


def test_normalize_subtasks_drops_cyclic_edges() -> None:
    """B2: A cycle (A depends_on B which depends_on A) must have the offending
    edge dropped, with a normalized_notes record."""
    from agent_loop.cli import _normalize_subtasks

    raw = [
        {"id": "r1-i1", "role": "implementation", "model": "sonnet",
         "reasoning_effort": "medium", "description": "impl A",
         "required_reading": [], "out_of_scope": [],
         "depends_on": ["r1-i2"],  # cycle: i1 depends on i2, i2 depends on i1
         "deliverable": "code A"},
        {"id": "r1-i2", "role": "implementation", "model": "sonnet",
         "reasoning_effort": "medium", "description": "impl B",
         "required_reading": [], "out_of_scope": [],
         "depends_on": ["r1-i1"],  # cycle
         "deliverable": "code B"},
    ]
    result = _normalize_subtasks(
        raw,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
        allowed_efforts=["low", "medium", "high"],
        default_effort="medium",
    )
    # At least one of the cycle edges must be dropped
    i1 = next(st for st in result if st["id"] == "r1-i1")
    i2 = next(st for st in result if st["id"] == "r1-i2")
    all_notes = i1["normalized_notes"] + i2["normalized_notes"]
    assert any("dropped_cycle_edge" in note for note in all_notes), \
        f"Expected dropped_cycle_edge note but got i1={i1['normalized_notes']} i2={i2['normalized_notes']}"
    # Cycle must be broken: both cannot simultaneously depend on each other
    assert not (("r1-i2" in i1["depends_on"]) and ("r1-i1" in i2["depends_on"])), \
        "Cycle not broken: both subtasks still depend on each other"


def test_build_review_payload_includes_verification_outcomes(tmp_path: Path) -> None:
    """B3: build_review_payload must include verification_outcomes in the payload
    when provided, and emit an empty list when not provided."""
    from agent_loop.diff_capture import DiffStats
    from agent_loop.payload import build_review_payload
    from agent_loop.shared_io import SharedDelta

    out = tmp_path / "review-payload.json"
    outcomes = [
        {"subtask_id": "r1-v1", "status": "pass", "note": ""},
        {"subtask_id": "r1-v2", "status": "fail", "note": "pytest failed in test_auth.py"},
    ]
    payload = build_review_payload(
        out_path=out,
        round_n=1,
        goal_summary="test goal",
        stats=DiffStats(files_changed=0, insertions=0, deletions=0),
        shared_delta=SharedDelta(),
        artifact_paths={},
        safety_flags=[],
        verification_outcomes=outcomes,
    )
    assert "verification_outcomes" in payload
    assert len(payload["verification_outcomes"]) == 2
    assert payload["verification_outcomes"][0]["subtask_id"] == "r1-v1"
    assert payload["verification_outcomes"][0]["status"] == "pass"
    assert payload["verification_outcomes"][1]["subtask_id"] == "r1-v2"
    assert payload["verification_outcomes"][1]["status"] == "fail"
    assert "pytest failed" in payload["verification_outcomes"][1]["note"]

    on_disk = json.loads(out.read_text())
    assert on_disk["verification_outcomes"] == outcomes

    # Empty list when not provided
    out2 = tmp_path / "review-payload2.json"
    payload2 = build_review_payload(
        out_path=out2,
        round_n=1,
        goal_summary="g",
        stats=DiffStats(files_changed=0, insertions=0, deletions=0),
        shared_delta=SharedDelta(),
        artifact_paths={},
        safety_flags=[],
    )
    assert payload2["verification_outcomes"] == []


def test_scan_verification_outcomes_from_progress_md(tmp_path: Path) -> None:
    """B3: _scan_verification_outcomes reads progress.md and extracts
    verification lines."""
    from agent_loop.cli import _scan_verification_outcomes

    progress = tmp_path / "progress.md"
    progress.write_text(
        "[done] r1-v1 verification: pass\n"
        "[done] r1-v2 verification: fail — pytest failed in X\n"
        "[done] r1-i1 implementation: finished code\n"  # NOT a verification line
        "[doing] r1-v3 verification: pass\n",  # NOT [done]
        encoding="utf-8",
    )
    outcomes = _scan_verification_outcomes(progress)
    assert len(outcomes) == 2
    ids = [o["subtask_id"] for o in outcomes]
    assert "r1-v1" in ids
    assert "r1-v2" in ids
    v1 = next(o for o in outcomes if o["subtask_id"] == "r1-v1")
    v2 = next(o for o in outcomes if o["subtask_id"] == "r1-v2")
    assert v1["status"] == "pass"
    assert v2["status"] == "fail"
    assert "pytest failed" in v2["note"]

    # Empty list for absent file
    assert _scan_verification_outcomes(tmp_path / "nonexistent.md") == []

    # Empty list when no matching lines
    progress2 = tmp_path / "progress2.md"
    progress2.write_text("[done] r1-i1 implementation: done\n", encoding="utf-8")
    assert _scan_verification_outcomes(progress2) == []


def test_no_scope_key_in_round_plan_json(tmp_repo: Path) -> None:
    """C1a: 'scope' must not appear in round_plan.json under any circumstances."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    env = _codex_stub_sequence(tmp_repo, [
        _merged_envelope(round_n=1, worker_model="sonnet", reason="test",
                         reasoning_effort="medium", task_description="Do A"),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    raw = rp.read_text(encoding="utf-8")
    # Check raw text does not contain "scope" as a JSON key
    import re
    assert not re.search(r'"scope"\s*:', raw), \
        f"'scope' key found in round_plan.json: {raw[:500]}"



def test_no_scope_in_subtasks_block() -> None:
    """C1a: _render_subtasks_block must not include a 'scope' column."""
    from agent_loop.cli import _render_subtasks_block

    subtasks = [
        {"id": "r1-i1", "role": "implementation", "model": "haiku",
         "reasoning_effort": "low", "description": "implement",
         "deliverable": "code", "depends_on": []},
    ]
    block = _render_subtasks_block(subtasks)
    # The table header should not contain "scope"
    lines = block.split("\n")
    header_line = next((l for l in lines if "| id |" in l), "")
    assert "scope" not in header_line.lower(), \
        f"'scope' found in table header: {header_line}"


def test_parse_round_plan_merged_envelope_both_fields() -> None:
    """A1: _parse_round_plan must correctly extract both round_plan routing fields
    AND prompt-content fields from a merged envelope in a single call."""
    from agent_loop.cli import _parse_round_plan

    raw = json.dumps({
        "round_plan": {
            "round": 2,
            "worker_model": "opus",
            "worker_model_reason": "architecture refactor",
            "reasoning_effort": "high",
            "subtasks": [
                {"id": "r2-i1", "role": "implementation", "model": "haiku",
                 "reasoning_effort": "low", "description": "implement refactor",
                 "required_reading": ["file.py"], "out_of_scope": [],
                 "depends_on": [], "deliverable": "refactored code"},
            ],
        },
        "task_description": "Refactor the auth module",
        "execution_plan_bullets": ["Step 1: read code", "Step 2: refactor"],
        "acceptance_criteria": ["Tests pass", "No regressions"],
        "carry_forward": "Auth module has been identified",
    })

    result = _parse_round_plan(
        raw,
        round_n=2,
        allowed_models=["haiku", "sonnet", "opus"],
        default_model="sonnet",
    )

    # Routing fields
    assert result["worker_model"] == "opus"
    assert result["reasoning_effort"] == "high"
    assert len(result["subtasks"]) == 1
    assert result["subtasks"][0]["id"] == "r2-i1"

    # Prompt-content fields
    assert result["task_description"] == "Refactor the auth module"
    assert result["execution_plan_bullets"] == ["Step 1: read code", "Step 2: refactor"]
    assert result["acceptance_criteria"] == ["Tests pass", "No regressions"]
    assert result["carry_forward"] == "Auth module has been identified"

    # No complexity or scope
    assert "complexity" not in result
    assert "scope" not in result

    # Not a parse failure
    assert result.get("parse_failed") is False


def test_plan_round_emits_phase_fields(tmp_repo: Path) -> None:
    """plan-round JSON output must include current_phase and total_phases fields."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    env = _codex_stub_sequence(tmp_repo, [
        _merged_envelope(
            round_n=1, worker_model="haiku", reason="mechanical",
            reasoning_effort="low", task_description="Implement A",
        ),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert "current_phase" in js, f"current_phase missing from plan-round output: {js}"
    assert "total_phases" in js, f"total_phases missing from plan-round output: {js}"
    assert js["current_phase"] == 1
    assert js["total_phases"] == 1


# ---------------------------------------------------------------------------
# consecutive_needs_changes unit tests
# ---------------------------------------------------------------------------

def test_plan_round_consecutive_needs_changes_no_history(tmp_repo: Path) -> None:
    """No history -> consecutive_needs_changes == 0 in plan-round output."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    env = _codex_stub_sequence(tmp_repo, [
        _merged_envelope(
            round_n=1, worker_model="haiku", reason="mechanical",
            reasoning_effort="low", task_description="Implement A",
        ),
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert "consecutive_needs_changes" in js, (
        f"consecutive_needs_changes missing from plan-round output: {js}"
    )
    assert js["consecutive_needs_changes"] == 0


def test_plan_round_consecutive_needs_changes_counter() -> None:
    """_count_consecutive_needs_changes returns N when the last N rounds are NEEDS_CHANGES."""
    from agent_loop.cli import _count_consecutive_needs_changes
    from agent_loop.run_state import RunState, RoundEntry

    rs = RunState(run_id="r", goal_path="g", plan_path="p", rounds=[
        RoundEntry(n=1, decision="NEEDS_CHANGES"),
        RoundEntry(n=2, decision="NEEDS_CHANGES"),
        RoundEntry(n=3, decision="NEEDS_CHANGES"),
    ])
    assert _count_consecutive_needs_changes(rs) == 3

    rs2 = RunState(run_id="r", goal_path="g", plan_path="p", rounds=[
        RoundEntry(n=1, decision="APPROVE"),
        RoundEntry(n=2, decision="NEEDS_CHANGES"),
    ])
    assert _count_consecutive_needs_changes(rs2) == 1


def test_plan_round_consecutive_needs_changes_phase_boundary() -> None:
    """PHASE_COMPLETE resets the count: only NEEDS_CHANGES in the new phase are counted."""
    from agent_loop.cli import _count_consecutive_needs_changes
    from agent_loop.run_state import RunState, RoundEntry

    rs = RunState(run_id="r", goal_path="g", plan_path="p", rounds=[
        RoundEntry(n=1, decision="NEEDS_CHANGES"),
        RoundEntry(n=2, decision="NEEDS_CHANGES"),
        RoundEntry(n=3, decision="PHASE_COMPLETE"),   # phase boundary
        RoundEntry(n=4, decision="NEEDS_CHANGES"),
        RoundEntry(n=5, decision="NEEDS_CHANGES"),
    ])
    # Only rounds 4 and 5 are in the new phase tail; PHASE_COMPLETE stops scan
    assert _count_consecutive_needs_changes(rs) == 2


def test_plan_round_consecutive_needs_changes_none_decision_skipped() -> None:
    """None (in-progress) decisions are skipped; do not break the consecutive count."""
    from agent_loop.cli import _count_consecutive_needs_changes
    from agent_loop.run_state import RunState, RoundEntry

    rs = RunState(run_id="r", goal_path="g", plan_path="p", rounds=[
        RoundEntry(n=1, decision="NEEDS_CHANGES"),
        RoundEntry(n=2, decision=None),   # in-progress, skip
        RoundEntry(n=3, decision=None),   # in-progress, skip
    ])
    # None decisions are skipped; round 1 is NEEDS_CHANGES -> count == 1
    assert _count_consecutive_needs_changes(rs) == 1

    rs2 = RunState(run_id="r", goal_path="g", plan_path="p", rounds=[
        RoundEntry(n=1, decision=None),
        RoundEntry(n=2, decision=None),
    ])
    # All None -> count == 0
    assert _count_consecutive_needs_changes(rs2) == 0


def test_plan_round_emits_phase_complete_signal_true(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    _run(["plan-init", "--run", run_id], cwd=tmp_repo,
         env_overrides=_codex_stub_sequence(tmp_repo, [
             json.dumps({"phases": [{"phase_n": 1, "title": "T", "objective": "O", "content": "C"}]}),
         ]))

    envelope = {
        "round_plan": {
            "round": 1, "worker_model": "haiku", "worker_model_reason": "simple",
            "reasoning_effort": "low", "phase_complete_signal": True, "subtasks": [],
        },
        "task_description": "do x", "execution_plan_bullets": [], "acceptance_criteria": [], "carry_forward": "",
    }
    env = codex_stub(json.dumps(envelope))
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["phase_complete_signal"] is True


def test_plan_round_phase_complete_signal_defaults_false(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    _run(["plan-init", "--run", run_id], cwd=tmp_repo,
         env_overrides=_codex_stub_sequence(tmp_repo, [
             json.dumps({"phases": [{"phase_n": 1, "title": "T", "objective": "O", "content": "C"}]}),
         ]))

    # Codex returns envelope without phase_complete_signal
    envelope = {
        "round_plan": {
            "round": 1, "worker_model": "haiku", "worker_model_reason": "simple",
            "reasoning_effort": "low", "subtasks": [],
        },
        "task_description": "do x", "execution_plan_bullets": [], "acceptance_criteria": [], "carry_forward": "",
    }
    env = codex_stub(json.dumps(envelope))
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["phase_complete_signal"] is False
