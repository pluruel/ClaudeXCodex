---
name: resume-run
description: Interpret the JSON from `agent-loop continue` and resume the loop at the right step.
---

# resume-run

Invoked when the user types `/agent-loop continue [--run <id>]`.

## Step 1 — call the CLI

`Bash: agent-loop continue [--run <id>]`

Output JSON: `{action, notes, options, run_id, current_round}`.

## Step 2 — dispatch on `action`

| action | what to do |
|---|---|
| `plan_round` | Start a fresh round at SKILL.md round-loop step 1. |
| `dispatch` | Phase machine still says `init`. Re-dispatch the worker subagent (round dir + prompt are on disk). |
| `advance_to_review` | Worker finished but no review yet. Jump straight to `agent-loop review-round`. |
| `write_review` | Same as `advance_to_review`. |
| `write_memo` | Review is on disk but memo not appended. Compose memo, call `append-memo`. |
| `branch_decision` | Decision recorded, just branch (APPROVE / STOP_FOR_USER / NEEDS_CHANGES). |
| `finalize` | Call `agent-loop finalize`. |
| `user_confirm` | Show options to the user; act on their choice. |

## `user_confirm` (worker interrupted)

Tell the user:

> "Round N's worker did not complete. Pick one:
> - **redispatch** — re-dispatch a fresh worker subagent with the existing prompt
> - **abandon-round** — proceed to review with whatever exists on disk
> - **abort-run** — mark the run aborted"

Then:
- `redispatch` → return to SKILL.md round-loop step 2 (capture-baseline) then step 3 (Task tool dispatch)
- `abandon-round` → write a stub claude-result.md if missing, then `agent-loop review-round`
- `abort-run` → `agent-loop abort --run <id>` and stop

## Heartbeat

If `agent-loop continue` warns of a recent `last_heartbeat`, another session may be running. Ask the user before doing anything.
