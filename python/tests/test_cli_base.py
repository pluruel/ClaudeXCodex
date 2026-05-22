from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["agent-loop", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_help(tmp_path: Path) -> None:
    r = _run(["--help"], cwd=tmp_path)
    assert r.returncode == 0
    assert "init-run" in r.stdout
    assert "scout" in r.stdout
    assert "finalize" in r.stdout


def test_unknown_subcommand_errors(tmp_path: Path) -> None:
    r = _run(["nonsense"], cwd=tmp_path)
    assert r.returncode != 0
