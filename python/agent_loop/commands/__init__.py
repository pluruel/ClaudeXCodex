"""Command submodules package.

Importing this package ensures all command submodules are loaded so their
``@register`` decorators fire and populate ``agent_loop.registry._HANDLERS``.
"""
from agent_loop.commands import lifecycle  # noqa: F401
from agent_loop.commands import status  # noqa: F401
from agent_loop.commands import worker_ops  # noqa: F401
from agent_loop.commands import inspect  # noqa: F401
from agent_loop.commands import planning  # noqa: F401
from agent_loop.commands import review  # noqa: F401
from agent_loop.commands import phases_cmd  # noqa: F401
