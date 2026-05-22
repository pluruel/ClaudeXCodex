from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(args, cwd):
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False)


def test_record_diff_captures_and_writes(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    rd = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rd.mkdir(parents=True)

    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_repo,
        capture_output=True, text=True,
    ).stdout.strip()
    (tmp_repo / "added.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)

    r = _run(["record-diff", "--run", run_id, "--round", "1",
              "--baseline", baseline], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    diff = (rd / "diff.patch").read_text(encoding="utf-8")
    assert "added.txt" in diff
