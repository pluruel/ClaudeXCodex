from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_loop", *args],
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


def test_handler_registry_complete() -> None:
    """All expected command names must be present in _HANDLERS after import.

    This test guards r4-i2/r4-i3's handler moves: if a move drops a @register
    decorator the name disappears from the registry and this test fails before
    any integration test is needed.
    """
    import agent_loop.cli  # noqa: F401 — triggers command registration
    from agent_loop.registry import _HANDLERS

    expected = {
        "init-run",
        "init-round",
        "plan-init",
        "plan-round",
        "review-round",
        "advance-phase",
        "record-diff",
        "capture-baseline",
        "mark-worker-done",
        "mark-dispatched",
        "scout",
        "status",
        "progress",
        "finalize",
        "abort",
        "inspect",
        "write-review",
        "append-memo",
        "continue",
        "memo-note",
        "phase-commit",
        "phase-review",
    }
    missing = expected - set(_HANDLERS.keys())
    assert not missing, f"handlers missing from registry: {sorted(missing)}"
