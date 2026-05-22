"""Enable `python -m agent_loop ...` invocation without depending on the
`agent-loop` entry-point script being on PATH."""
from __future__ import annotations

import sys

from agent_loop.cli import main


if __name__ == "__main__":
    sys.exit(main())
