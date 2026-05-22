---
name: resume-run
description: Interpret the JSON returned by `agent-loop continue` and resume the loop at the right point.
---

# resume-run

Invoked when the user runs `/agent-loop continue [--run <id>]`.

## Step 1 — call the CLI

`Bash: agent-loop continue [--run <id>]`

Output JSON: `{action, notes, options, run_id, current_round}`.

## Step 2 — dispatch on `action`

| action | what to do |
|---|---|
| `plan_round` | Apply `plan-from-goal` (round 1) or `plan-from-review` (round > 1), then `init-round`, then `dispatch`. |
| `dispatch` | Call `agent-loop dispatch --run <id> --round <current_round>` directly. |
| `advance_to_review` | Skip dispatch. Go straight to `round-review` for the current round (result.md already exists on disk). |
| `write_review` | Same as `advance_to_review`. |
| `write_memo` | Apply `round-memo` and call `append-memo`. |
| `branch_decision` | Read the recorded decision in state.json (Codex did this previously); branch as in the main loop. |
| `finalize` | Call `agent-loop finalize`. |
| `user_confirm` | Present `options` to the user, get their pick, act accordingly (see below). |

## `user_confirm` (dispatch interrupted)

Tell the user, in plain language:

> "Round N's dispatch did not complete. Pick one:
> - **redispatch** — re-run Claude with the same prompt (work may be partially duplicated)
> - **abandon-round** — proceed to review with whatever exists on disk
> - **abort-run** — mark the run aborted"

Wait for the user's choice. Then:

- `redispatch` → `agent-loop dispatch --run <id> --round <current_round>` (the round dir is reused; messages.jsonl is appended)
- `abandon-round` → write a stub claude-result.md if missing (saying "(interrupted; no result)") and proceed to `round-review`
- `abort-run` → `agent-loop abort --run <id>` and stop

## Heartbeat warning

If `agent-loop continue` complains about a recent `last_heartbeat` (< 30s old), it means another session may still be running. Ask the user to confirm before doing anything.
