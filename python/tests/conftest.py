"""Shared pytest fixtures."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


# Repo layout:
#   <repo>/python/tests/conftest.py   <-- this file
#   <repo>/python/                    <-- pytest's typical cwd (parent of tests/)
#
# Codex CLI 0.133.x writes ~200 four-byte "blat" probe files into a `.codex-tmp/`
# subdir of the spawning process's cwd whenever `codex exec` runs in sandbox
# mode. Several integration tests (e.g. test_integration_smoke_v2) spawn codex
# via subprocess; those invocations pollute `python/.codex-tmp/` and the
# directory accumulates across pytest runs (it is gitignored but still
# clutters local trees). We sweep it at session-finish.
_CODEX_TMP_CWD = Path(__file__).resolve().parent.parent / ".codex-tmp"


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """Remove Codex CLI sandbox probe directory left in the python/ dir.

    Safe to call when the dir doesn't exist. Errors are intentionally
    swallowed: the test session's success/failure should not depend on
    cleanup of probe artifacts.
    """
    try:
        if _CODEX_TMP_CWD.is_dir():
            shutil.rmtree(_CODEX_TMP_CWD, ignore_errors=True)
    except OSError:
        pass


# Invocation prefix used by every CLI test. Going through ``python -m agent_loop``
# keeps the tests independent of the optional ``agent-loop`` entry-point script
# being on PATH; as long as the package is importable (which the editable install
# in CI guarantees), this works the same on every platform.
AGENT_LOOP_CMD: list[str] = [sys.executable, "-m", "agent_loop"]


def run_cli(
    args: list[str],
    cwd: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Invoke the agent-loop CLI as a Python module and return the result."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [*AGENT_LOOP_CMD, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.fixture
def cli():
    """Function fixture that invokes the agent-loop CLI via ``python -m agent_loop``."""
    return run_cli


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
