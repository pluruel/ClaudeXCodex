from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(args, cwd):
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False)


def test_capture_baseline_returns_sha(tmp_repo: Path) -> None:
    r = _run(["capture-baseline"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert len(js["baseline"]) == 40
