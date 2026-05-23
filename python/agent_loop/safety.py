"""Safety checks and Claude SDK PreToolUse hook factory."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class SafetyConfig:
    bash_block_patterns: list[str] = field(default_factory=list)
    sensitive_path_patterns: list[str] = field(default_factory=list)


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patterns]


def check_bash_command(command: str, cfg: SafetyConfig) -> bool:
    """True if the command matches a blocked pattern."""
    for pat in _compile(cfg.bash_block_patterns):
        if pat.search(command):
            return True
    return False


def check_path_sensitive(path: str, cfg: SafetyConfig) -> bool:
    """True if the path matches a sensitive pattern."""
    for pat in _compile(cfg.sensitive_path_patterns):
        if pat.search(path):
            return True
    return False


PreToolHook = Callable[..., Optional[str]]


def make_pretool_hook(cfg: SafetyConfig) -> PreToolHook:
    """Return a callable suitable for ClaudeAgentOptions PreToolUse hook.

    The callable returns None to allow, or a string reason to block.
    """
    def hook(*, tool_name: str, tool_input: dict) -> Optional[str]:
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            if check_bash_command(cmd, cfg):
                return f"blocked: command matches safety rule ({cmd!r})"
        if tool_name in ("Edit", "Write"):
            path = tool_input.get("file_path", "")
            if check_path_sensitive(path, cfg):
                return f"blocked: sensitive path ({path!r})"
        return None

    return hook
