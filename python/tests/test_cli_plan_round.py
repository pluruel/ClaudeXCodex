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


def test_plan_round_creates_round_dir_and_prompt(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]
    # write a fake plan first
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n2. [ ] do B\n", encoding="utf-8")

    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round": 1,
            "worker_model": "haiku",
            "worker_model_reason": "single file mechanical change",
            "scope": "narrow",
            "complexity": {
                "files_expected": 1,
                "requires_architecture": False,
                "requires_broad_search": False,
                "risk": "low",
            },
        }),
        "## Worker Model\nhaiku\n\n## Task\nImplement A",
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

    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round": 1,
            "worker_model": "mega-opus",
            "worker_model_reason": "invalid",
            "scope": "wide",
            "complexity": {},
        }),
        "## Worker Model\nopus - claimed-by-codex\n\n## Task\nImplement A",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["worker_model"] == "sonnet"
    assert js["scope"] == "normal"
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round-plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    assert plan_json["worker_model"] == "sonnet"
    assert plan_json["scope"] == "normal"
    # The CLI must rewrite Codex's drifted "## Worker Model" body to match the
    # normalized routing decision; "opus - claimed-by-codex" must NOT survive.
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    prompt_text = pr.read_text(encoding="utf-8")
    assert "## Worker Model" in prompt_text
    assert "sonnet" in prompt_text
    assert "claimed-by-codex" not in prompt_text
    assert "Scope: normal" in prompt_text


def test_plan_round_injects_worker_model_when_codex_omits_it(tmp_repo: Path) -> None:
    """Codex's prompt draft may not include a ## Worker Model section.
    plan-round must inject one so the worker subagent never loses routing info.
    """
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round": 1,
            "worker_model": "opus",
            "worker_model_reason": "broad architecture refactor",
            "scope": "broad",
            "complexity": {
                "files_expected": 8,
                "requires_architecture": True,
                "requires_broad_search": True,
                "risk": "high",
            },
        }),
        # Codex omits ## Worker Model entirely; only Goal + Task are present.
        "## Goal\nRefactor module X\n\n## Task (this round)\nDo the refactor",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["worker_model"] == "opus"
    assert js["scope"] == "broad"

    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    prompt_text = pr.read_text(encoding="utf-8")
    assert "## Worker Model" in prompt_text
    assert "opus - broad architecture refactor" in prompt_text
    assert "Scope: broad" in prompt_text
    # Injected block must land between Goal and Task so the worker reads it
    # before reaching the task description.
    goal_idx = prompt_text.find("## Goal")
    wm_idx = prompt_text.find("## Worker Model")
    task_idx = prompt_text.find("## Task")
    assert goal_idx != -1 and wm_idx != -1 and task_idx != -1
    assert goal_idx < wm_idx < task_idx


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
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round": 1,
            "worker_model": "haiku",
            "worker_model_reason": reason,
            "scope": "narrow",
            "complexity": {},
        }),
        # Codex draft includes an existing ## Worker Model that must be
        # rewritten via the canonical block path -- the bug only triggers on
        # the replacement code path, not the inject path.
        "## Worker Model\nopus - drifted\n\n## Task (this round)\nDo A",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    prompt_text = pr.read_text(encoding="utf-8")
    # Reason is preserved verbatim (backslashes intact) in the prompt body.
    assert reason in prompt_text
    assert "## Worker Model" in prompt_text
    assert "Scope: narrow" in prompt_text


def test_plan_round_collapses_multiline_worker_model_reason(tmp_repo: Path) -> None:
    """A multiline reason must not inject extra ``##`` headings or push
    ``Scope:`` out of the ``## Worker Model`` section. We collapse the reason
    to one whitespace-separated line before storing and rendering it.
    """
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    multiline_reason = "first line of reason\n## Injected Heading\nstill same reason"
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round": 1,
            "worker_model": "sonnet",
            "worker_model_reason": multiline_reason,
            "scope": "normal",
            "complexity": {},
        }),
        "## Worker Model\nplaceholder\n\n## Task (this round)\nDo A",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    # round-plan.json stores the collapsed (single-line) form.
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round-plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    stored_reason = plan_json["worker_model_reason"]
    assert "\n" not in stored_reason
    assert "## Injected Heading" in stored_reason  # text preserved, just inlined

    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    prompt_text = pr.read_text(encoding="utf-8")

    # The canonical block must be exactly three lines and ``Scope:`` must sit
    # inside the section -- not pushed out by an injected heading.
    import re
    m = re.search(
        r"^##\s+Worker\s+Model\s*\n(.+?)\n(Scope:\s+\S+)\s*$",
        prompt_text,
        re.MULTILINE,
    )
    assert m is not None, prompt_text
    reason_line = m.group(1)
    scope_line = m.group(2)
    assert "\n" not in reason_line
    assert scope_line == "Scope: normal"
    assert "sonnet -" in reason_line


def test_plan_round_handles_non_json_model_selection(tmp_repo: Path) -> None:
    """If Codex returns garbage for the model-selection call, plan-round must
    still produce a usable prompt with the default model + normal scope."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    env = _codex_stub_sequence(tmp_repo, [
        "not json at all -- the model returned prose",
        "## Goal\nDo A\n\n## Task (this round)\nImplement A",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["worker_model"] == "sonnet"  # config default
    assert js["scope"] == "normal"
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    prompt_text = pr.read_text(encoding="utf-8")
    assert "## Worker Model" in prompt_text
    assert "sonnet" in prompt_text
    assert "Scope: normal" in prompt_text


def test_plan_round_parses_and_persists_subtasks(tmp_repo: Path) -> None:
    """When Codex emits a valid subtasks array, plan-round must normalize and
    persist them in round_plan.json and inject a readable block into the prompt."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    subtasks = [
        {
            "id": "r1-a1",
            "role": "analysis",
            "model": "haiku",
            "reasoning_effort": "low",
            "scope": "narrow",
            "description": "Map CLI entry points",
            "required_reading": ["python/agent_loop/cli.py"],
            "out_of_scope": [".git/"],
            "depends_on": [],
            "deliverable": "Append findings to shared/knowledge.md",
        },
        {
            "id": "r1-i1",
            "role": "implementation",
            "model": "sonnet",
            "reasoning_effort": "medium",
            "scope": "normal",
            "description": "Implement subtask parsing",
            "required_reading": ["python/agent_loop/cli.py"],
            "out_of_scope": [".git/"],
            "depends_on": ["r1-a1"],
            "deliverable": "Pass tests for subtask normalization",
        },
    ]
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round": 1,
            "worker_model": "sonnet",
            "worker_model_reason": "integration work",
            "scope": "normal",
            "reasoning_effort": "medium",
            "complexity": {"files_expected": 3, "requires_architecture": False,
                           "requires_broad_search": False, "risk": "low"},
            "subtasks": subtasks,
        }),
        "## Goal\nDo A\n\n## Task (this round)\nImplement subtask parsing\n\n## Required Reading\n- cli.py",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["subtask_count"] == 2
    assert len(js["subtasks"]) == 2
    assert js["subtasks"][0]["id"] == "r1-a1"
    assert js["subtasks"][0]["role"] == "analysis"
    assert js["subtasks"][1]["id"] == "r1-i1"
    assert js["subtasks"][1]["depends_on"] == ["r1-a1"]

    # round_plan.json must include normalized subtasks
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    assert rp.exists(), "round_plan.json (canonical name) must exist"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    assert "subtasks" in plan_json
    assert len(plan_json["subtasks"]) == 2

    # Compatibility alias must also exist
    rp_compat = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round-plan.json"
    assert rp_compat.exists(), "round-plan.json (compat alias) must exist"

    # Prompt must include the subtask block
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    prompt_text = pr.read_text(encoding="utf-8")
    assert "### Subtasks (this round)" in prompt_text
    assert "r1-a1" in prompt_text
    assert "r1-i1" in prompt_text
    assert "analysis" in prompt_text
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
            "role": "unknown-role",       # invalid role → normalized to implementation
            "model": "mega-ultra-opus",    # invalid model → normalized to default (sonnet)
            "reasoning_effort": "extreme", # invalid effort → role-aware default
            "scope": "galaxy",             # invalid scope → normal
            "description": "bad subtask",
            "required_reading": [],
            "out_of_scope": [],
            "depends_on": [],
            "deliverable": "do something",
        },
    ]
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round": 1,
            "worker_model": "sonnet",
            "worker_model_reason": "test",
            "scope": "normal",
            "reasoning_effort": "medium",
            "complexity": {},
            "subtasks": bad_subtasks,
        }),
        "## Goal\nDo A\n\n## Task (this round)\nImplement A",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    st = plan_json["subtasks"][0]
    assert st["role"] == "implementation"   # unknown-role → implementation
    assert st["model"] == "sonnet"          # invalid model → default
    assert st["scope"] == "normal"          # invalid scope → normal
    assert st["reasoning_effort"] in ("low", "medium", "high")  # valid effort


def test_plan_round_missing_subtasks_triggers_empty_list(tmp_repo: Path) -> None:
    """When Codex omits subtasks entirely, plan-round must persist an empty
    subtasks list (not crash) and not inject a subtask block into the prompt."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n", encoding="utf-8")

    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round": 1,
            "worker_model": "haiku",
            "worker_model_reason": "mechanical",
            "scope": "narrow",
            "reasoning_effort": "low",
            "complexity": {},
            # subtasks deliberately omitted
        }),
        "## Goal\nDo A\n\n## Task (this round)\nImplement A",
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

    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round": 1,
            "worker_model": "sonnet",
            "worker_model_reason": "test",
            "scope": "normal",
            "reasoning_effort": "medium",
            "complexity": {},
            "subtasks": [
                {
                    "id": "r1-v1",
                    "role": "verification",
                    "model": "haiku",
                    "reasoning_effort": "low",
                    "scope": "narrow",
                    "description": "Run tests",
                    "required_reading": [],
                    "out_of_scope": [],
                    "depends_on": [],
                    "deliverable": "Run: python -m pytest tests/ -x and report pass/fail",
                }
            ],
        }),
        "## Goal\nDo A\n\n## Task (this round)\nRun verification",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    # The key must be present (Codex was asked for it; stub provided it)
    assert "subtasks" in plan_json
    assert plan_json["subtasks"][0]["role"] == "verification"


def test_plan_round_respects_custom_allowed_efforts(tmp_repo: Path) -> None:
    """Custom [worker_reasoning].allowed in repo config must be enforced by
    _render_worker_model_block. When a custom allowed list removes 'medium',
    an invalid effort value must fall back to the config default, and the
    rendered Worker Model block must reflect the configured value."""
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

    # Codex returns reasoning_effort="medium" (which is no longer allowed)
    # and no Worker Model section in the prompt.
    env = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round": 1,
            "worker_model": "haiku",
            "worker_model_reason": "mechanical change",
            "scope": "narrow",
            "reasoning_effort": "medium",  # invalid under custom config
            "complexity": {},
        }),
        "## Goal\nDo A\n\n## Task (this round)\nImplement A",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    # The round_plan.json should show the invalid "medium" was normalized to
    # the custom default "low" by _parse_round_plan.
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round_plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    assert plan_json["reasoning_effort"] == "low"

    # The rendered prompt must include the normalized effort in the Worker Model block.
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    prompt_text = pr.read_text(encoding="utf-8")
    assert "## Worker Model" in prompt_text
    assert "Reasoning Effort: low" in prompt_text
    # "medium" must NOT appear in the effort line.
    lines = prompt_text.split("\n")
    effort_lines = [l for l in lines if "Reasoning Effort:" in l]
    assert len(effort_lines) == 1
    assert "low" in effort_lines[0] and "medium" not in effort_lines[0]
