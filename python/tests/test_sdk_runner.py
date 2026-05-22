from __future__ import annotations

import asyncio
from pathlib import Path

from agent_loop.safety import SafetyConfig
from agent_loop.sdk_runner import RunnerConfig, run_round


class _FakeClient:
    def __init__(self, options): self.options = options; self.sent = None
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False
    async def query(self, text): self.sent = text
    async def receive_response(self):
        for msg in [{"type": "text", "content": "hello"},
                    {"type": "text", "content": "done"}]:
            yield msg


def _factory(options):
    return _FakeClient(options)


def test_run_round_persists_messages(tmp_path: Path) -> None:
    cfg = RunnerConfig(
        target_repo=tmp_path,
        prompt_text="do the thing",
        worker_system_prompt="you are claude",
        round_dir=tmp_path / "round_01",
        plugins={},
        safety=SafetyConfig(),
        client_factory=_factory,
    )
    cfg.round_dir.mkdir()
    asyncio.run(run_round(cfg))
    msgs = (cfg.round_dir / "claude-messages.jsonl").read_text().strip().splitlines()
    assert len(msgs) == 2
    assert "hello" in msgs[0]


def test_run_round_passes_prompt(tmp_path: Path) -> None:
    captured = {}
    def factory(options):
        c = _FakeClient(options); captured["client"] = c; return c
    cfg = RunnerConfig(
        target_repo=tmp_path,
        prompt_text="PROMPT-X",
        worker_system_prompt="sys",
        round_dir=tmp_path / "r",
        plugins={},
        safety=SafetyConfig(),
        client_factory=factory,
    )
    cfg.round_dir.mkdir()
    asyncio.run(run_round(cfg))
    assert captured["client"].sent == "PROMPT-X"
