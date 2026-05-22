# agent-loop (Python core)

Python package that powers the agent-loop Codex plugin: Claude SDK invocation, run-state persistence, diff capture, scout signals, safety hooks.

## Development setup

```bash
cd python
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

All test and dev commands assume the project's `.venv`. Do not install into a system Python.

## CLI entry point

After install, `agent-loop` is available as a script. See `agent-loop --help`.

## Module map

- `cli.py` — argparse + subcommand handlers
- `run_state.py` — RunState + phase machine
- `resume.py` — interrupted-run detection
- `scout.py` — file tree + grep signal extractor (Codex-facing JSON)
- `shared_io.py` — shared/ append + delta
- `prompt_render.py` — Claude worker prompt template
- `result_parser.py` — claude-result.md → ClaudeResult
- `progress_parser.py` — progress.md tail analysis
- `diff_capture.py` — git baseline + diff + stats
- `payload.py` — review-payload.json builder
- `safety.py` — bash/path/diff checks + SDK PreToolUse hook
- `sdk_runner.py` — async Claude SDK round runner
