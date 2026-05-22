---
name: shared-knowledge
description: Read/append discipline for `<run_dir>/shared/` (the cross-round knowledge area). Mostly used by workers; the supervisor reads it only via the `inspect` subcommand if needed.
---

# shared-knowledge

`shared/` lives at `<run_dir>/shared/` and holds three append-only files:

- `knowledge.md` - facts about the target repo
- `decisions.md` - design decisions across rounds
- `open-questions.md` - unresolved questions; resolutions can be appended later

## Who writes

- **Workers (subagents)** append to all three during their rounds.
- **Codex** sees them indirectly: the `plan-round` and `review-round` subcommands may include slices when relevant.
- **You (supervisor)** rarely write. If you do (e.g., recording a strategic call you made yourself), use `Edit` to append a single line; do NOT overwrite.

## When to read

You almost never read these. If reasoning about a stale-looking pattern in a later round, you may run:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" inspect --run <id> --round 1 --file ../../shared/knowledge.md --lines 1-50
```

But default to trusting the round payload + memo.

## Format conventions

- `knowledge.md`: `- <one-line fact>`
- `decisions.md`: `- [<source>] <decision> (<short reason>)` where `<source>` is `round-N` or `codex-round-N` or `supervisor-round-N`.
- `open-questions.md`: `- <question>` (resolutions: indented `  - Resolved (round N): <answer>`).
