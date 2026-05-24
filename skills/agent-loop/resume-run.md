---
name: resume-run
description: Interpret the JSON from the `continue` subcommand and resume the loop at the right step.
---

# resume-run

Invoked when the user types `/ClaudeXCodex:agent-loop` with no args or `/ClaudeXCodex:agent-loop continue [--run <id>]`.

> CLI is invoked through the plugin wrapper. Use `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop"` exactly; do not call `agent-loop` via `PATH`.

## Step 1 - call the CLI

`Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" continue [--run <id>]`

Output JSON: `{action, notes, options, run_id, current_round}`.

## Step 2 - dispatch on `action`

| action | what to do |
|---|---|
| `plan_round` | Start a fresh round at SKILL.md round-loop step 1. |
| `dispatch` | Phase machine still says `init`. Re-dispatch the worker subagent (round dir + prompt are on disk). |
| `advance_to_review` | Worker finished but no review yet. Jump straight to `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" review-round` (which also auto-appends the memo). |
| `write_review` | Same as `advance_to_review`. |
| `write_memo` | `review-round` was interrupted after writing `codex-review.md` but before appending the memo. Re-run `review-round`; the memo append is idempotent. Do NOT call `append-memo` manually. |
| `branch_decision` | Review and memo are done, just branch (APPROVE / PHASE_COMPLETE / NEEDS_CHANGES). |
| `advance_phase` | Call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase --run <run_id>`. If `is_last_phase` true, finalize. Otherwise loop back to round-loop step 1. |
| `finalize` | Call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" finalize`. |
| `user_confirm` | Show options to the user; act on their choice. |

## `user_confirm` (worker interrupted)

Tell the user:

> Round N's worker did not complete. Pick one:
> - **redispatch** - re-dispatch a fresh worker subagent with the existing prompt
> - **abandon-round** - proceed to review with whatever exists on disk
> - **abort-run** - mark the run aborted

Then:

- `redispatch` - return to SKILL.md round-loop step 2 (capture-baseline), then step 3 (`mark-dispatched`) and step 4 (Task tool dispatch).
- `abandon-round` - call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" review-round` directly (no stub file needed).
- `abort-run` - call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" abort --run <id>` and stop.

## Heartbeat

If the JSON from `continue` warns of a recent `last_heartbeat`, another session may be running. Ask the user before doing anything.
