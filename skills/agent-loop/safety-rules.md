---
name: safety-rules
description: Safety guardrails enforced by the `review-round` subcommand (post-dispatch scan) - what triggers them and how the supervisor reacts.
---

# safety-rules (supervisor-side reference)

> CLI is invoked through the plugin wrapper. Use `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop"` exactly; do not call `agent-loop` via `PATH`.

Safety is enforced in two places:

1. **Worker subagent prompt** - the supervisor instructs the subagent NEVER to run `git commit/push`, `rm -rf`, `sudo`, DB migrations, or writes to sensitive paths. (No technical block; trust the subagent.)
2. **Post-dispatch scan** - the `review-round` subcommand reads the diff, computes stats, and emits `safety_flags` in its JSON output.

## Flags that `review-round` can emit

| Flag | Meaning |
|---|---|
| `diff_has_sensitive` | Diff includes paths matching `config/defaults.toml` `[safety.sensitive_paths]` patterns. |
| `missing_claude_result` | Worker didn't write `claude-result.md`. |

(Diff-size thresholds were removed: with subtask-based dispatch a "large" round is normal and the size flag misfired more often than it caught real issues. Real safety here is content-based — sensitive paths or a missing result — not byte count.)

## Supervisor reaction matrix

| Decision (from review-round JSON) | What to do |
|---|---|
| Any `safety_flags` non-empty | Treat as STOP_FOR_USER even if `decision == APPROVE` (defense in depth). |
| `STOP_FOR_USER` | Tell user, point at codex-review.md, end loop. |
| `APPROVE` (no flags) | Call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" finalize`. |
| `NEEDS_CHANGES` (no flags) | Next round. |

## What you (supervisor) must never do

- Run `git commit`, `git push`, or any destructive command yourself.
- Edit target repo source files. That's the worker's job.
- Read the user's full diff/result/test-log into context - use the `inspect` subcommand for narrow slices only.

## Repo-specific override

If `<target_repo>/.agent-loop/config.toml` exists, the Python core uses its values. You don't need to read this file; trust the payload's flags.
