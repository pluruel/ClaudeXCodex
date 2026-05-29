"""Handler registry for agent-loop CLI commands.

This module owns the ``_HANDLERS`` dict and the ``@register`` decorator so that
command submodules (in ``agent_loop.commands``) can import from here without
creating a circular dependency with ``agent_loop.cli``.

Usage in a command submodule::

    from agent_loop.registry import register

    @register("my-command")
    def _cmd_my_command(args) -> int:
        ...
"""
from __future__ import annotations

_HANDLERS: dict = {}


def register(name: str):
    """Decorator that maps a subcommand name to its handler function."""
    def deco(fn):
        _HANDLERS[name] = fn
        return fn
    return deco
