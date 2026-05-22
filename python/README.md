# agent-loop (Python core)

Python package that powers the agent-loop Claude Code plugin: Codex subprocess wrapper, run-state persistence, diff capture, scout signals, safety hooks.

## Development setup

```bash
cd python
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

All test and dev commands assume the project's `.venv`. Do not install into a system Python.

## CLI invocation

During development, invoke the CLI through Python. `pyproject.toml` deliberately defines **no** `[project.scripts]` entry point, so `pip install` does not create a package-managed `agent-loop` script:

```bash
python -m agent_loop --help
```

At plugin runtime, Claude Code exposes the repository root's `bin/agent-loop` wrapper on the Bash tool's `PATH`. That wrapper dispatches to `${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py`, so the plugin does not require an editable install.

## Module map

- `cli.py` — argparse + subcommand handlers
- `__main__.py` — `python -m agent_loop` entry (also runnable as a bare script)
- `codex_client.py` — headless `codex exec --json` subprocess wrapper
- `run_state.py` — RunState + phase machine
- `resume.py` — interrupted-run detection
- `scout.py` — file tree + grep signal extractor (Codex-facing JSON)
- `shared_io.py` — shared/ append + delta
- `prompt_render.py` — Claude worker prompt template
- `result_parser.py` — claude-result.md → ClaudeResult
- `progress_parser.py` — progress.md tail analysis
- `diff_capture.py` — git baseline + diff + stats
- `payload.py` — review-payload.json builder
- `safety.py` — bash/path/diff checks
