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

The CLI is always invoked through Python — `pyproject.toml` deliberately defines **no** `[project.scripts]` entry point, so `pip install` never creates an `agent-loop` shell wrapper on PATH:

```bash
python -m agent_loop --help
# or, from the plugin install (no pip install needed):
python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" --help
```

The skill files and the test suite both invoke the module via `python -m agent_loop`, so behavior is identical regardless of install state or platform.

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
