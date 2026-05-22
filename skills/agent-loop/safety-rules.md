---
name: safety-rules
description: Reference for the safety guardrails that the Python core enforces — what Codex should expect and how to react.
---

# safety-rules (informational, Codex side)

Most safety is enforced inside `agent-loop dispatch` (PreToolUse hook + post-dispatch scan). This file documents what triggers them so Codex reacts correctly.

## What the dispatch step blocks (inside Claude's SDK session)

- Bash matching block patterns: `git commit|push|merge|rebase|reset --hard|clean -f`, `rm -rf`, `sudo`, `alembic upgrade`, `prisma migrate (deploy|reset)`, destructive `psql -c` queries, piped `curl | sh|bash`, `npm publish`, `docker push|rmi`.
- Edit/Write to sensitive paths: `.env*`, `secrets/`, `credentials.*`, `migrations/`, `alembic/versions/`, `ci/`, `.github/workflows/`, `Dockerfile*`, `package-lock.json`, `poetry.lock`, `uv.lock`.

When blocked, Claude receives a `block` message from the hook. It will document the block in `claude-result.md`.

## What `agent-loop dispatch` flags in the payload

- `safety_flags: ["diff_has_sensitive"]` — diff includes sensitive paths
- `safety_flags: ["diff_too_many_files"]` — files > config.diff_size.warn_files (default 15)
- `safety_flags: ["diff_too_many_lines"]` — lines > config.diff_size.warn_lines (default 600)
- `safety_flags: ["missing_claude_result"]` — Claude didn't write `claude-result.md`

## Codex reaction matrix

| flag present | decision |
|---|---|
| Any flag | `STOP_FOR_USER` (always — do not auto-continue) |
| No flags + decision_hint == "blocked" | `STOP_FOR_USER` |
| No flags + decision_hint == "completed" + tests pass + goal met | `APPROVE` |
| No flags + decision_hint == "incomplete" | `NEEDS_CHANGES` (default if no STOP trigger) |

## What Codex itself must never do

- Run `git commit` / `git push` from any Bash call
- Edit/Write target repo source files (Codex is the orchestrator, not the worker — Claude does the editing)
- Read the user's source code directly. Use scout + inspect.

## Repo-specific override

If `<target_repo>/.agent-loop/config.toml` exists, the Python core uses its values for the safety patterns. Codex does not need to read this file; just trust the payload's flags.
