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
        "## Worker Model\nsonnet\n\n## Task\nImplement A",
    ])
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["worker_model"] == "sonnet"
    rp = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "round-plan.json"
    plan_json = json.loads(rp.read_text(encoding="utf-8"))
    assert plan_json["worker_model"] == "sonnet"
    assert plan_json["scope"] == "normal"
