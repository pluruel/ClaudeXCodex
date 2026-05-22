"""Claude Agent SDK invocation for one round.

The real Claude session is created via ``claude_agent_sdk.ClaudeSDKClient``.
For tests we accept a ``client_factory`` that returns an async-context
manager exposing ``query()`` and ``receive_response()``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from agent_loop.safety import SafetyConfig, make_pretool_hook


AUTO_MODE_DIRECTIVE = """## Auto Mode Active
Work without stopping for clarifying questions. When you would normally pause
to check, make the reasonable call and keep going. There is no human to ask;
you are being driven by an upstream controller (Codex) that will review your
work after this round. If something is genuinely blocked, document it in
claude-result.md "open_questions" and finish what you can.
"""


WORKER_SYSTEM_PROMPT = """You are the Claude worker inside an agent-loop round.

## Your Constraints

- Read the Reading List in the user prompt **first**. Required items before Suggested. Do NOT read Out of Scope items. Avoid wide Glob/Grep across the repo.
- Append a line to `<round_dir>/progress.md` for each meaningful step. Markers: `[done]` / `[doing]` / `[planned]`. Keep at most one `[doing]` at a time.
- When you discover facts about the target repo that outlast this round (file purpose, conventions, dependencies, gotchas), append to `<shared_dir>/knowledge.md`.
- When you choose between alternatives (architectural or implementation), log the decision + reason to `<shared_dir>/decisions.md`.
- Unresolved questions go to `<shared_dir>/open-questions.md`.
- At the end of the round, write `<round_dir>/claude-result.md` exactly following the schema in your prompt.
- Never run: `git commit`, `git push`, `rm -rf`, `sudo`, DB migrations, destructive shell pipes. A PreToolUse hook will also block these.

## Why This Exists

You will be replaced by a fresh Claude session in the next round. Anything you know that is not on disk in shared/* or the result.md will be lost. Externalize knowledge deliberately.
"""


@dataclass
class RunnerConfig:
    target_repo: Path
    prompt_text: str
    worker_system_prompt: str
    round_dir: Path
    plugins: dict
    safety: SafetyConfig
    client_factory: Optional[Callable[[Any], Any]] = None
    allowed_tools: list[str] = field(
        default_factory=lambda: [
            "Read", "Edit", "Write", "Bash", "Glob", "Grep", "TodoWrite", "Task",
        ]
    )
    max_turns: int = 40


def _build_options(cfg: RunnerConfig) -> dict:
    """Build the kwargs that will be passed to ClaudeAgentOptions."""
    hook = make_pretool_hook(cfg.safety)
    return {
        "cwd": str(cfg.target_repo),
        "system_prompt": cfg.worker_system_prompt + "\n\n" + AUTO_MODE_DIRECTIVE,
        "permission_mode": "bypassPermissions",
        "allowed_tools": cfg.allowed_tools,
        "plugins": cfg.plugins,
        "setting_sources": [],
        "max_turns": cfg.max_turns,
        "hooks": {"PreToolUse": hook},
    }


def _default_factory(options: dict):
    # Real SDK path. Import lazily so tests don't require the package.
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions  # type: ignore
    return ClaudeSDKClient(options=ClaudeAgentOptions(**options))


async def run_round(cfg: RunnerConfig) -> None:
    options = _build_options(cfg)
    factory = cfg.client_factory or _default_factory
    client = factory(options)
    messages_path = cfg.round_dir / "claude-messages.jsonl"
    cfg.round_dir.mkdir(parents=True, exist_ok=True)
    with messages_path.open("a") as sink:
        async with client as session:
            await session.query(cfg.prompt_text)
            async for msg in session.receive_response():
                sink.write(json.dumps(msg) + "\n")
