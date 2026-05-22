# agent-loop — Codex plugin for Claude review loops

A Codex CLI plugin where Codex orchestrates Claude Code (via the Claude Agent SDK) as a worker through bounded review rounds. Codex generates each Claude prompt with a curated Reading List, reviews each round, and writes audit-grade artifacts to `.agent-loop/runs/<id>/`.

See `docs/superpowers/specs/2026-05-22-agent-loop-codex-plugin-design.md` for the full spec.

## Repo layout

- `.codex-plugin/plugin.json` — Codex plugin manifest
- `skills/` — Codex plugin skills (`agent-loop/`, `references/`)
- `config/` — packaged plugin defaults (e.g. `defaults.toml`)
- `python/` — Python core (`agent-loop` CLI, Claude SDK runner, state, safety)
- `docs/superpowers/` — spec and implementation plan

## Install

### Codex plugin (skills)

```bash
codex plugin marketplace add pluruel/ClaudeXCodex
```

### Python core (CLI tool, required for the plugin to do real work)

```bash
git clone https://github.com/pluruel/ClaudeXCodex.git
cd ClaudeXCodex/python
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
# Add to PATH:
export PATH="$PWD/.venv/bin:$PATH"
```

### Authentication

Pick **one** for Claude (the worker):

**Option A — Claude Code subscription (Pro / Max, recommended if you have it)**
```bash
claude login                      # one-time, stores OAuth in ~/.claude/
unset ANTHROPIC_API_KEY           # make sure no API key takes precedence
```
The Claude Agent SDK auto-detects the local Claude Code credentials.

**Option B — Anthropic API key (pay-as-you-go)**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Codex CLI itself is separate:
```bash
export OPENAI_API_KEY=sk-...      # required for Codex
```

## Quick usage

In Codex CLI inside your target repo:

```
/agent-loop start "<your goal>"
```

To resume after an interruption:

```
/agent-loop continue
```

## Status

v1 — local CLI + plugin skills. See spec sections 10 & 11 for what's out of scope vs. planned for later.
