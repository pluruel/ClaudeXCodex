"""End-to-end: init-run -> plan-init -> plan-round -> simulate worker
 -> record-diff -> mark-worker-done -> review-round -> finalize."""
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
    data_path = tmp_repo / "codex_stub_sequence.json"
    stub_path = tmp_repo / "codex_stub_sequence.py"
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


def test_e2e_claude_entry_flow(tmp_repo: Path, codex_stub) -> None:
    # 1. init-run
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "smoke"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # 2. plan-init (stub codex -> returns a plan)
    env_plan = codex_stub("# Plan\n\n## Tasks\n1. [ ] thing\n\n## Notes\nshort")
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env_plan)
    assert r2.returncode == 0, r2.stderr
    assert (run_dir / "plan.md").exists()

    # 3. plan-round (stub codex -> returns merged envelope, single call A1)
    env_round = _codex_stub_sequence(tmp_repo, [
        json.dumps({
            "round_plan": {
                "round": 1,
                "worker_model": "haiku",
                "worker_model_reason": "simple smoke task",
                "reasoning_effort": "low",
                "subtasks": [],
            },
            "task_description": "Implement thing",
            "execution_plan_bullets": [],
            "acceptance_criteria": [],
            "carry_forward": "",
        }),
    ])
    r3 = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env_round)
    assert r3.returncode == 0, r3.stderr
    assert (run_dir / "rounds" / "01" / "claude-prompt.md").exists()

    # 4. capture-baseline
    r4 = _run(["capture-baseline"], cwd=tmp_repo)
    assert r4.returncode == 0, r4.stderr
    baseline = json.loads(r4.stdout)["baseline"]
    r4b = _run(["mark-dispatched", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r4b.returncode == 0, r4b.stderr

    # 5. simulate worker doing work + progress entries
    (tmp_repo / "src.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.txt"], cwd=tmp_repo, check=True)
    rd = run_dir / "rounds" / "01"
    (rd / "progress.md").write_text(
        "[done] r1-i1 implementation: added src.txt\n",
        encoding="utf-8",
    )

    # 6. record-diff
    r6 = _run(["record-diff", "--run", run_id, "--round", "1",
               "--baseline", baseline], cwd=tmp_repo)
    assert r6.returncode == 0, r6.stderr

    # 7. mark-worker-done
    r7 = _run(["mark-worker-done", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r7.returncode == 0, r7.stderr

    # 8. review-round (stub codex -> returns APPROVE body)
    review_body = (
        "# Codex Review -- Round 1\n\n## Decision\nAPPROVE\n\n"
        "## Findings\n- none\n"
    )
    env_review = codex_stub(review_body)
    r8 = _run(["review-round", "--run", run_id, "--round", "1"],
              cwd=tmp_repo, env_overrides=env_review)
    assert r8.returncode == 0, r8.stderr
    assert json.loads(r8.stdout)["decision"] == "APPROVE"

    # 9. finalize
    r10 = _run(["finalize", "--run", run_id], cwd=tmp_repo)
    assert r10.returncode == 0, r10.stderr
    assert (run_dir / "final-report.md").exists()

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "completed"
