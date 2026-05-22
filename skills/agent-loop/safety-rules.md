---
name: safety-rules
description: Safety guardrails enforced by the `review-round` subcommand (post-dispatch scan) — what triggers them and how the supervisor reacts.
---

# safety-rules (supervisor-side reference)

> CLI is invoked via Python — see SKILL.md "CLI invocation convention". All `python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py"` calls below are abbreviated `$AL` for readability; substitute the full Python form when running.

Safety is enforced in two places:

1. **Worker subagent prompt** — the supervisor instructs the subagent NEVER to run `git commit/push`, `rm -rf`, `sudo`, DB migrations, or writes to sensitive paths. (No technical block; trust the subagent.)
2. **Post-dispatch scan** — `$AL review-round` reads the diff, computes stats, and emits `safety_flags` in its JSON output.

## Flags that `review-round` can emit

| Flag | Meaning |
|---|---|
| `diff_has_sensitive` | Diff includes paths matching `config/defaults.toml` `[safety.sensitive_paths]` patterns. |
| `diff_too_many_files` | Files changed > `safety.diff_size.warn_files` (default 15). |
| `diff_too_many_lines` | Lines changed > `safety.diff_size.warn_lines` (default 600). |
| `missing_claude_result` | Worker didn't write `claude-result.md`. |

## Supervisor reaction matrix

| Decision (from review-round JSON) | What to do |
|---|---|
| Any `safety_flags` non-empty | Treat as STOP_FOR_USER even if `decision == APPROVE` (defense in depth). |
| `STOP_FOR_USER` | Tell user, point at codex-review.md, end loop. |
| `APPROVE` (no flags) | `$AL finalize`. |
| `NEEDS_CHANGES` (no flags) | Next round. |

## What you (supervisor) must never do

- Run `git commit`, `git push`, or any destructive command yourself.
- Edit target repo source files. That's the worker's job.
- Read the user's full diff/result/test-log into context — use `$AL inspect` for narrow slices only.

## Repo-specific override

If `<target_repo>/.agent-loop/config.toml` exists, the Python core uses its values. You don't need to read this file; trust the payload's flags.
