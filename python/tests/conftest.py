"""Shared pytest fixtures."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Initialize an empty git repo in a tmp dir and return its path."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.fixture
def run_root(tmp_repo: Path) -> Path:
    """Return `.agent-loop/runs/<id>/` directory inside tmp_repo."""
    root = tmp_repo / ".agent-loop" / "runs" / "2026-05-22-test-run"
    (root / "rounds").mkdir(parents=True)
    (root / "shared").mkdir()
    return root
