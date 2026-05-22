"""Enable invocation without pip install.

Supports two call styles:

1.  ``python -m agent_loop ...``        (when the package is importable)
2.  ``python <repo>/python/agent_loop/__main__.py ...``  (no install — uses
    ``${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py`` via the Claude
    Code plugin's ``bin/agent-loop`` wrapper)

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
