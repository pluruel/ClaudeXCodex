# agent-loop — Claude Code plugin for review loops with Codex

A Claude Code plugin where the interactive Claude session is the supervisor, dispatching worker subagents via the Task tool and using Codex CLI (headless `codex exec --json`) for planning and review. All artifacts go to `.agent-loop/runs/<id>/`.

See `docs/superpowers/plans/2026-05-22-claude-entry-pivot.md` for the architecture pivot details. The original spec (`docs/superpowers/specs/2026-05-22-agent-loop-codex-plugin-design.md`) is superseded.

## Repo layout

- `.claude-plugin/plugin.json` — Claude Code plugin manifest
- `bin/` — plugin executables added to the Bash tool's `PATH` while the plugin is enabled
- `skills/` — plugin skills (`agent-loop/`, `references/`)
- `config/` — packaged plugin defaults (e.g. `defaults.toml`)
- `python/` — Python core (`python -m agent_loop` CLI, codex subprocess wrapper, state, safety)
- `docs/superpowers/` — spec and implementation plans

## Install

### Claude Code plugin (skills)

In Claude Code, run these slash commands in order:

```
/plugin marketplace add pluruel/ClaudeXCodex
/plugin install agent-loop@claudexcodex
/reload-plugins
```

After this, `/agent-loop <goal>` (start a new run; quotes optional) and `/agent-loop continue` (or just `/agent-loop` to resume the most recent run) become available.

#### Updating to the latest version

The local marketplace clone is cached. When upstream changes, refresh it with:

```
/plugin marketplace update claudexcodex
```

If `update` is unavailable or doesn't take effect, remove and re-add:

```
/plugin marketplace remove claudexcodex
/plugin marketplace add pluruel/ClaudeXCodex
/plugin install agent-loop@claudexcodex
```

#### Uninstall

```
/plugin uninstall agent-loop@claudexcodex
/plugin marketplace remove claudexcodex
```

#### Local development install (testing un-pushed changes)

Point the marketplace at your working tree instead of GitHub:

```
/plugin marketplace add c:\path\to\ClaudeXCodex
/plugin install agent-loop@claudexcodex
```

Any edits in your working tree are picked up on the next `/plugin install` or `/plugin marketplace update`.

### Python runtime (only requirement)

You just need Python 3.11+ on PATH. The CLI ships **inside the plugin** as a plain Python module and is exposed by the plugin's `bin/agent-loop` wrapper. Claude Code adds plugin `bin/` directories to the Bash tool's `PATH` while the plugin is enabled, so the skill invokes `agent-loop ...` directly. No `pip install`, manual PATH setup, or separate clone is required.

(If you ARE working on the code locally and want to run the test suite, the optional dev install is:

```bash
git clone https://github.com/pluruel/ClaudeXCodex.git
cd ClaudeXCodex/python
python -m venv .venv
.venv/bin/pip install -e ".[dev]"            # Linux/Mac
.\.venv\Scripts\pip.exe install -e ".[dev]"  # Windows
.venv/bin/pytest -q                           # Linux/Mac
.\.venv\Scripts\pytest.exe -q                 # Windows
```

The editable install registers the `agent_loop` package on the venv's `sys.path`. Tests invoke `python -m agent_loop ...` directly; plugin runtime goes through `bin/agent-loop`.)

### Authentication (both subscription-based; no API keys needed)

```bash
claude login        # if you haven't already
codex login         # subscription headless requires this
```

Do NOT set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` if you want subscription auth.

## Quick usage

In your target repo:

```
$ claude
> /agent-loop <your goal here, quotes optional>
```

The supervisor (this Claude session) will then call `codex exec` for planning/review and dispatch worker subagents (Task tool) for implementation. All artifacts in `.agent-loop/runs/<id>/`.

Resume after interruption (no goal arg → resume most recent run):

```
> /agent-loop
```

## Status

v2 — Claude-entry architecture. The supervisor is Claude; Codex is invoked as a subprocess for planning + review. Both run on subscription (Pro/Max for Claude; ChatGPT Plus for Codex headless).
