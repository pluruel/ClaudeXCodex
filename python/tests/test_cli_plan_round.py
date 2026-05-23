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
    assert pr.exists()
    assert rp.exists()
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
