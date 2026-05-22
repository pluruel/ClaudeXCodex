"""Wrapper around `codex exec --json` for headless invocation.

Usage:
    from agent_loop.codex_client import call_codex
    result = call_codex("Write a haiku about parsers.")
    print(result.final_text)

The default subprocess runner uses `subprocess.run([codex_bin, "exec", "--json", prompt])`.
Tests inject a fake runner to avoid the real CLI dependency.

The codex binary defaults to "codex" on PATH. For testing on platforms where
shipping a fake `codex` script is awkward (e.g. Windows), set the env var
``AGENT_LOOP_CODEX_BIN`` to a full command (e.g. ``python /tmp/stub.py``); the
value is shell-split with ``shlex.split``.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class CodexCallError(RuntimeError):
    """Raised when `codex exec` fails or returns unusable output."""


@dataclass
class CodexResult:
    final_text: str
    events: list[dict[str, Any]] = field(default_factory=list)
    exit_code: int = 0
    stderr: str = ""


SubprocessRunner = Callable[..., Any]


def _default_runner(cmd: list[str], **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _resolve_codex_bin() -> list[str]:
    override = os.environ.get("AGENT_LOOP_CODEX_BIN")
    if override:
        return shlex.split(override)
    return ["codex"]


def call_codex(
    prompt: str,
    *,
    timeout: Optional[float] = None,
    extra_args: Optional[list[str]] = None,
    runner: Optional[SubprocessRunner] = None,
) -> CodexResult:
    """Invoke `codex exec --json` headless and return the final assistant message.

    Args:
        prompt: Prompt text to send to Codex.
        timeout: Optional subprocess timeout (seconds).
        extra_args: Extra args appended after `--json` (e.g., ``["--sandbox", "read-only"]``).
        runner: Override for the subprocess.run callable (used in tests).

    Returns:
        CodexResult with the final assistant text + raw events.

    Raises:
        CodexCallError: if the process exits non-zero or no assistant message is emitted.
    """
    run = runner or _default_runner
    cmd = [*_resolve_codex_bin(), "exec", "--json"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(prompt)

    try:
        result = run(cmd, timeout=timeout) if timeout else run(cmd)
    except FileNotFoundError as exc:
        binary = cmd[0] if cmd else "codex"
        raise CodexCallError(
            f"could not execute {binary!r}; install Codex CLI and run `codex login`, "
            "or set AGENT_LOOP_CODEX_BIN to the full command"
        ) from exc
    except OSError as exc:
        binary = cmd[0] if cmd else "codex"
        raise CodexCallError(f"could not execute {binary!r}: {exc}") from exc
    exit_code = getattr(result, "returncode", 0)
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""

    if exit_code != 0:
        raise CodexCallError(
            f"codex exec exited {exit_code}: {stderr.strip() or '<no stderr>'}"
        )

    events: list[dict[str, Any]] = []
    final_text: Optional[str] = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue  # tolerate stray non-JSON lines
        events.append(evt)
        if evt.get("type") == "assistant_message":
            content = evt.get("content", "")
            if isinstance(content, str):
                final_text = content

    if final_text is None:
        raise CodexCallError(
            "codex exec produced no assistant message; "
            f"saw {len(events)} events."
        )

    return CodexResult(
        final_text=final_text,
        events=events,
        exit_code=exit_code,
        stderr=stderr,
    )
