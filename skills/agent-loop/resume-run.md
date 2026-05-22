---
name: resume-run
description: Interpret the JSON from the `continue` subcommand and resume the loop at the right step.
---

# resume-run

Invoked when the user types `/agent-loop` (no args) or `/agent-loop continue [--run <id>]`.

> CLI is invoked via Python — see SKILL.md "CLI invocation convention". All `$AL` shorthand below stands for `python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py"`; expand it when actually calling Bash.

## Step 1 — call the CLI

`Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" continue [--run <id>]`

Output JSON: `{action, notes, options, run_id, current_round}`.

## Step 2 — dispatch on `action`

| action | what to do |
|---|---|
| `plan_round` | Start a fresh round at SKILL.md round-loop step 1. |
| `dispatch` | Phase machine still says `init`. Re-dispatch the worker subagent (round dir + prompt are on disk). |
| `advance_to_review` | Worker finished but no review yet. Jump straight to `$AL review-round`. |
| `write_review` | Same as `advance_to_review`. |
| `write_memo` | Review is on disk but memo not appended. Compose memo, call `$AL append-memo`. |
| `branch_decision` | Decision recorded, just branch (APPROVE / STOP_FOR_USER / NEEDS_CHANGES). |
| `finalize` | Call `$AL finalize`. |
| `user_confirm` | Show options to the user; act on their choice. |

## `user_confirm` (worker interrupted)

Tell the user:

> "Round N's worker did not complete. Pick one:
> - **redispatch** — re-dispatch a fresh worker subagent with the existing prompt
> - **abandon-round** — proceed to review with whatever exists on disk
> - **abort-run** — mark the run aborted"

Then:
- `redispatch` → return to SKILL.md round-loop step 2 (capture-baseline) then step 3 (Task tool dispatch)
- `abandon-round` → write a stub claude-result.md if missing, then `$AL review-round`
- `abort-run` → `$AL abort --run <id>` and stop

## Heartbeat

If the JSON from `$AL continue` warns of a recent `last_heartbeat`, another session may be running. Ask the user before doing anything.
