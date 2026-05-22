"""End-to-end: init-run -> plan-init -> plan-round -> simulate worker
 -> record-diff -> mark-worker-done -> review-round -> append-memo -> finalize."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False, env=env)


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

    # 3. plan-round (stub codex -> returns a worker prompt body)
    env_round = codex_stub("## Task (this round)\nImplement thing")
    r3 = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env_round)
    assert r3.returncode == 0, r3.stderr
    assert (run_dir / "rounds" / "01" / "claude-prompt.md").exists()

    # 4. capture-baseline
    r4 = _run(["capture-baseline"], cwd=tmp_repo)
    assert r4.returncode == 0, r4.stderr
    baseline = json.loads(r4.stdout)["baseline"]

    # 5. simulate worker doing work + claude-result.md
    (tmp_repo / "src.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.txt"], cwd=tmp_repo, check=True)
    rd = run_dir / "rounds" / "01"
    (rd / "claude-result.md").write_text(
        "# Claude Result\n\n## Summary\nadded src.txt\n\n"
        "## Changed Files\n- src.txt\n\n## Test Outcome\npass\n\n"
        "## Decision Hint\ncompleted\n\n## Requires User\nfalse\n",
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

    # 9. append-memo
    memo = tmp_repo / "m.md"
    memo.write_text(
        "## Round 1 -- APPROVE\n- Goal progress: done\n- Top risks: none\n"
        "- Carry forward: n/a\n- Sensitive: none\n- Diff size: 1 file\n",
        encoding="utf-8",
    )
    r9 = _run(["append-memo", "--run", run_id, "--round", "1",
               "--memo-file", str(memo)], cwd=tmp_repo)
    assert r9.returncode == 0, r9.stderr

    # 10. finalize
    r10 = _run(["finalize", "--run", run_id], cwd=tmp_repo)
    assert r10.returncode == 0, r10.stderr
    assert (run_dir / "final-report.md").exists()

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "completed"
