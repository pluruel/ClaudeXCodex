"""Wrapper around `codex exec --json` for headless invocation.

Usage:
    from agent_loop.codex_client import call_codex
    result = call_codex("Write a haiku about parsers.")
    print(result.final_text)

The default subprocess runner uses `subprocess.run([codex_bin, "exec", "--json", "-"],
input=prompt)`.
Tests inject a fake runner to avoid the real CLI dependency.

The codex binary defaults to "codex" on PATH. For testing on platforms where
shipping a fake `codex` script is awkward (e.g. Windows), set the env var
``AGENT_LOOP_CODEX_BIN`` to a full command (e.g. ``python /tmp/stub.py``); the
value is shell-split with ``shlex.split``.
"""
from __future__ import annotations

import json
import os
import re
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


# Codex 0.133's sandbox probes look like 4-byte ("blat") files with short
# random alphanumeric names, written ~200 at a time into a transient subdir
# of the spawning process's cwd. We sweep those dirs after every codex call so
# they don't leak into the host repo. The sweep is intentionally conservative:
# a directory is only removed if EVERY entry inside it is a regular file with
# a probe-signature name AND a size at or below ``_PROBE_MAX_BYTES``. Any
# subdir, hidden dotfile, README, or otherwise-named entry aborts the sweep
# for that directory.
_PROBE_DIRNAMES: tuple[str, ...] = (".tmp", ".codex-tmp", ".codex-cleanup")
_PROBE_NAME_RE = re.compile(r"^[A-Za-z0-9_]{6,12}$")
_PROBE_MAX_BYTES = 16


def _looks_like_probe_dir(path: Path) -> bool:
    """Return True iff ``path`` is a dir whose entries all look like codex probes.

    Conservative: any single non-probe entry (subdir, README, dotfile, large
    file, oddly-named file) returns False so the directory is left untouched.
    Returns False if the path doesn't exist, isn't a directory, or any
    ``OSError`` occurs while scanning.
    """
    try:
        if not path.is_dir():
            return False
        entries = list(path.iterdir())
    except OSError:
        return False
    if not entries:
        # Empty dir -- still safe to remove; codex sometimes leaves the dir
        # itself behind after its own cleanup pass.
        return True
    for entry in entries:
        try:
            if not entry.is_file() or entry.is_symlink():
                return False
            if not _PROBE_NAME_RE.match(entry.name):
                return False
            if entry.stat().st_size > _PROBE_MAX_BYTES:
                return False
        except OSError:
            return False
    return True


def _sweep_codex_probe_dirs(cwd: Optional[Path] = None) -> None:
    """Remove codex probe directories from ``cwd`` if they match the signature.

    Never raises. Safe to call when no probe dirs exist. Used as the cleanup
    step in ``call_codex``'s try/finally so production callers don't leak
    ``.tmp/``, ``.codex-tmp/``, or ``.codex-cleanup/`` into the host repo.
    """
    base = cwd if cwd is not None else Path.cwd()
    for name in _PROBE_DIRNAMES:
        target = base / name
        try:
            if _looks_like_probe_dir(target):
                shutil.rmtree(target, ignore_errors=True)
        except OSError:
            # Cleanup is best-effort; never let it bubble up into the codex
            # call result.
            continue


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
    cmd.append("-")

    try:
        try:
            result = (
                run(cmd, timeout=timeout, input=prompt)
                if timeout else
                run(cmd, input=prompt)
            )
        except FileNotFoundError as exc:
            binary = cmd[0] if cmd else "codex"
            raise CodexCallError(
                f"could not execute {binary!r}; install Codex CLI and run `codex login`, "
                "or set AGENT_LOOP_CODEX_BIN to the full command"
            ) from exc
        except OSError as exc:
            binary = cmd[0] if cmd else "codex"
            raise CodexCallError(f"could not execute {binary!r}: {exc}") from exc
    finally:
        # Always sweep codex sandbox probes from cwd, whether codex returned
        # normally, raised, or its subprocess itself errored. The sweep is
        # internally guarded against any OSError and the signature check is
        # conservative -- real user files / dirs that happen to share these
        # names are not touched. See _looks_like_probe_dir.
        try:
            _sweep_codex_probe_dirs()
        except OSError:
            pass
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
