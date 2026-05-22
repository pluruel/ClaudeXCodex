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
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
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
    # Force UTF-8 decoding so subprocess reader threads don't crash on
    # cp949/locale defaults when Codex emits non-ASCII JSON (Windows default
    # locale is cp949 on Korean systems, which can't decode UTF-8 bytes).
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _resolve_codex_bin() -> list[str]:
    override = os.environ.get("AGENT_LOOP_CODEX_BIN")
    if override:
        parts = shlex.split(override, posix=sys.platform != "win32")
        return [p.strip("\"'") for p in parts]
    resolved = shutil.which("codex.cmd" if sys.platform == "win32" else "codex")
    if resolved:
        return [resolved]
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            npm_codex = Path(appdata) / "npm" / "codex.cmd"
            if npm_codex.exists():
                return [str(npm_codex)]
    return ["codex"]


def _extract_assistant_text(evt: dict[str, Any]) -> Optional[str]:
    """Pull the assistant message text out of a single Codex event.

    Supports both schemas:
      - Pre-0.130 (legacy): ``{"type": "assistant_message", "content": "..."}``
      - 0.133+ (current):   ``{"type": "item.completed",
                              "item": {"type": "agent_message", "text": "..."}}``

    Returns the text string if this event carries the assistant message, else None.
    """
    evt_type = evt.get("type")
    if evt_type == "assistant_message":
        content = evt.get("content")
        return content if isinstance(content, str) else None
    if evt_type == "item.completed":
        item = evt.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            return text if isinstance(text, str) else None
    return None


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
        text = _extract_assistant_text(evt)
        if text is not None:
            final_text = text

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
