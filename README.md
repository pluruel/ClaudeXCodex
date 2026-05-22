# agent-loop — Codex plugin for Claude review loops

A Codex CLI plugin where Codex orchestrates Claude Code (via the Claude Agent SDK) as a worker through bounded review rounds. Codex generates each Claude prompt with a curated Reading List, reviews each round, and writes audit-grade artifacts to `.agent-loop/runs/<id>/`.

See `docs/superpowers/specs/2026-05-22-agent-loop-codex-plugin-design.md` for the full spec.

## Repo layout

- `agent-loop/` — Codex plugin (skills, references, config)
- `python/` — Python core (`agent-loop` CLI, Claude SDK runner, state, safety)
- `docs/superpowers/` — spec and implementation plan

## Install (local dev)

```bash
cd python
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Then point your Codex CLI at the `agent-loop/` directory as a plugin (consult Codex docs for the exact install path).

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
