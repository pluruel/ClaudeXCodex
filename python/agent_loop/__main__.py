"""Enable invocation without pip install.

Supports two call styles — there is no ``agent-loop`` shell entry point any
more, on purpose:

1.  ``python -m agent_loop ...``        (when the package is importable)
2.  ``python <repo>/python/agent_loop/__main__.py ...``  (no install — uses
    ``${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py`` from the Claude
    Code plugin install)

For style 2 we have to add the package's parent dir to ``sys.path`` before the
package imports anything from itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_loop.cli import main


if __name__ == "__main__":
    sys.exit(main())
