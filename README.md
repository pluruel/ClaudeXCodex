# agent-loop — Claude Code plugin for review loops with Codex

A Claude Code plugin where the interactive Claude session is the supervisor, dispatching worker subagents via the Task tool and using Codex CLI (headless `codex exec --json`) for planning and review. All artifacts go to `.agent-loop/runs/<id>/`.

See `docs/superpowers/plans/2026-05-22-claude-entry-pivot.md` for the architecture pivot details. The original spec (`docs/superpowers/specs/2026-05-22-agent-loop-codex-plugin-design.md`) is superseded.

## Repo layout

- `.claude-plugin/plugin.json` — Claude Code plugin manifest
- `skills/` — plugin skills (`agent-loop/`, `references/`)
- `config/` — packaged plugin defaults (e.g. `defaults.toml`)
- `python/` — Python core (`agent-loop` CLI, codex subprocess wrapper, state, safety)
- `docs/superpowers/` — spec and implementation plans

## Install

### Claude Code plugin (skills)

In Claude Code, run these slash commands in order:

```
/plugin marketplace add pluruel/ClaudeXCodex
/plugin install agent-loop@claudexcodex
/reload-plugins
```

After this, `/agent-loop start "<goal>"` and `/agent-loop continue` become available.

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

### Python core (CLI, required)

```bash
git clone https://github.com/pluruel/ClaudeXCodex.git
cd ClaudeXCodex/python
python -m venv .venv
# Linux/Mac
.venv/bin/pip install -e ".[dev]"
# Windows PowerShell
.\.venv\Scripts\pip.exe install -e ".[dev]"
```

After install, the package is invoked as `python -m agent_loop ...` (no PATH setup required). The skill uses this form throughout.

A bare `agent-loop` shell-script wrapper is also installed in the venv's `Scripts/` (Windows) or `bin/` (Unix) — equivalent, but requires that directory on PATH.

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
> /agent-loop start "<your goal>"
```

The supervisor (this Claude session) will then call `codex exec` for planning/review and dispatch worker subagents (Task tool) for implementation. All artifacts in `.agent-loop/runs/<id>/`.

Resume after interruption:

```
> /agent-loop continue
```

## Status

v2 — Claude-entry architecture. The supervisor is Claude; Codex is invoked as a subprocess for planning + review. Both run on subscription (Pro/Max for Claude; ChatGPT Plus for Codex headless).
