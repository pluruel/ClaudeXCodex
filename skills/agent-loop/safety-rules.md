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

(Diff-size thresholds were removed: with subtask-based dispatch a "large" round is normal and the size flag misfired more often than it caught real issues. Real safety here is content-based — sensitive paths — not byte count.)

## Supervisor reaction matrix

| Decision (from review-round JSON) | What to do |
|---|---|
| `APPROVE` | Call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" finalize`. |
| `PHASE_COMPLETE` | Call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase`. If `is_last_phase` true, then finalize. |
| `NEEDS_CHANGES` | Next round. |

`safety_flags` (if any) are passed to Codex in the review payload as informational context. Codex decides the outcome autonomously based on this context — the supervisor does not override the decision based on flags.

## What you (supervisor) must never do

- Run `git commit`, `git push`, or any destructive command yourself.
- Edit target repo source files. That's the worker's job.
- Read the user's full diff/result/test-log into context - use the `inspect` subcommand for narrow slices only.

## Repo-specific override

If `<target_repo>/.agent-loop/config.toml` exists, the Python core uses its values. You don't need to read this file; trust the payload's flags.
