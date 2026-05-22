# python/tests/test_codex_client.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_loop.codex_client import (
    CodexCallError,
    CodexResult,
    call_codex,
    _resolve_codex_bin,
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
    seen = {}
    def _runner(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["input"] = kwargs.get("input")
        return _fake_runner_yielding([
            {"type": "assistant_message", "content": "FINAL OUTPUT BODY"},
        ])(cmd, **kwargs)

    res = call_codex("hello", runner=_runner)
    assert isinstance(res, CodexResult)
    assert res.final_text == "FINAL OUTPUT BODY"
    assert res.events  # raw events preserved
    assert res.exit_code == 0
    assert seen["cmd"][-1] == "-"
    assert seen["input"] == "hello"


def test_call_codex_extracts_final_assistant_message_from_jsonl() -> None:
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


def test_call_codex_wraps_missing_binary() -> None:
    def _missing_runner(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    with pytest.raises(CodexCallError) as exc:
        call_codex("x", runner=_missing_runner)
    msg = str(exc.value)
    assert "could not execute" in msg
    assert "codex login" in msg


def test_resolve_codex_bin_prefers_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_LOOP_CODEX_BIN", r"C:\Tools\codex.cmd --profile test")
    assert _resolve_codex_bin() == [r"C:\Tools\codex.cmd", "--profile", "test"]


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


def test_call_codex_handles_new_item_completed_schema() -> None:
    """Codex 0.133.0+ emits item.completed events with nested agent_message item."""
    runner = _fake_runner_yielding([
        {"type": "thread.started", "thread_id": "t-1"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "NEW SCHEMA OUTPUT"},
        },
        {"type": "turn.completed"},
    ])
    res = call_codex("hello", runner=runner)
    assert res.final_text == "NEW SCHEMA OUTPUT"


def test_call_codex_handles_new_schema_last_agent_message_wins() -> None:
    """If multiple agent_message items appear, take the final one (matches old behavior)."""
    runner = _fake_runner_yielding([
        {"type": "item.completed", "item": {"type": "agent_message", "text": "first"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "second"}},
    ])
    res = call_codex("x", runner=runner)
    assert res.final_text == "second"


def test_default_runner_decodes_utf8_regardless_of_locale(tmp_path, monkeypatch) -> None:
    """Subprocess output must decode as UTF-8 even on cp949 / non-UTF-8 locales."""
    import subprocess
    import sys

    from agent_loop.codex_client import _default_runner

    script = tmp_path / "emit.py"
    script.write_text(
        "import sys\n"
        "sys.stdout.buffer.write('\\u3131\\u314f\\n'.encode('utf-8'))\n",
        encoding="utf-8",
    )
    result = _default_runner([sys.executable, str(script)])
    assert result.returncode == 0
    assert "ㄱㅏ" in result.stdout
