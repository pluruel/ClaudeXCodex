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


@pytest.fixture
def codex_stub(tmp_repo: Path):
    """Factory that yields an env-var dict overriding the codex binary.

    Usage:
        env = codex_stub("# Plan\\n## Tasks\\n1. [ ] do X")
        subprocess.run([...], env={**os.environ, **env})

    Cross-platform: spawns the current Python with a stub script that prints
    a single `{"type": "assistant_message", "content": <content>}` JSON line.
    """
    import sys

    def _make(content: str) -> dict:
        stub_path = tmp_repo / "codex_stub.py"
        stub_path.write_text(
            "import json, sys\n"
            f"print(json.dumps({{'type': 'assistant_message', 'content': {content!r}}}))\n",
            encoding="utf-8",
        )
        py = sys.executable.replace("\\", "/")
        stub_posix = stub_path.as_posix()
        return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_posix}"'}

    return _make
