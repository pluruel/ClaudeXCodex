# python/tests/test_codex_client.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_loop.codex_client import (
    CodexCallError,
    CodexResult,
    call_codex,
)


def _fake_runner_yielding(events: list[dict]):
    """Return a runner that pretends `codex exec --json` emitted these events."""
    def _run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = "\n".join(json.dumps(e) for e in events) + "\n"
            stderr = ""
        return R()
    return _run


def test_call_codex_extracts_final_assistant_message() -> None:
    runner = _fake_runner_yielding([
        {"type": "thinking", "content": "hmm"},
        {"type": "tool_use", "name": "write_file"},
        {"type": "assistant_message", "content": "FINAL OUTPUT BODY"},
    ])
    res = call_codex("hello", runner=runner)
    assert isinstance(res, CodexResult)
    assert res.final_text == "FINAL OUTPUT BODY"
    assert res.events  # raw events preserved
    assert res.exit_code == 0


def test_call_codex_raises_on_nonzero_exit() -> None:
    def _bad_runner(cmd, **kwargs):
        class R:
            returncode = 2
            stdout = ""
            stderr = "auth required"
        return R()
    with pytest.raises(CodexCallError) as exc:
        call_codex("x", runner=_bad_runner)
    assert "auth required" in str(exc.value)


def test_call_codex_handles_no_assistant_message() -> None:
    runner = _fake_runner_yielding([
        {"type": "thinking", "content": "..."},
    ])
    with pytest.raises(CodexCallError) as exc:
        call_codex("x", runner=runner)
    assert "no assistant" in str(exc.value).lower()


def test_call_codex_skips_malformed_lines() -> None:
    def _runner(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = (
                '{"type": "thinking", "content": "ok"}\n'
                "not-json-garbage\n"
                '{"type": "assistant_message", "content": "DONE"}\n'
            )
            stderr = ""
        return R()
    res = call_codex("x", runner=_runner)
    assert res.final_text == "DONE"
