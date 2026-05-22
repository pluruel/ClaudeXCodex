from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_windows_wrapper_help() -> None:
    r = subprocess.run(
        [str(REPO_ROOT / "bin" / "agent-loop.cmd"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "mark-dispatched" in r.stdout


def test_posix_wrapper_help_when_sh_available() -> None:
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("sh is not available")
    r = subprocess.run(
        [sh, str(REPO_ROOT / "bin" / "agent-loop"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "mark-dispatched" in r.stdout
