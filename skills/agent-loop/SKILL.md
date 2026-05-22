---
name: agent-loop
description: Codex-driven Claude review loop. When the user types `/agent-loop start "<goal>"`, Codex acts as the orchestrator that dispatches Claude (via the bundled `agent-loop` Python CLI) as a worker, reviews each round, generates the next prompt, and continues until APPROVE or STOP_FOR_USER.
---

# agent-loop — Codex Orchestration Skill

When invoked (`/agent-loop start "<goal>"` or `/agent-loop continue …`), follow this protocol exactly. The skill is rigid — do not deviate.

## Required reading on first invocation per session

- `references/claude-prompt-template.md` — what we hand to Claude
- `references/claude-result-schema.md` — what Claude produces
- `references/review-payload-schema.md` — the small JSON you consume
- `references/shared-knowledge-schema.md` — format of `shared/*` files

You do not need to re-read these in every invocation; trust the schemas.

## Token discipline (mandatory)

- You do not read target repo files directly. Use `agent-loop scout` for signals.
- You do not read raw diffs / test logs / SDK message streams. Use `agent-loop inspect` only when a specific section is necessary.
- Per-round you only ingest: `review-payload.json`, this round's `claude-result.md`, `memo.md`, and `shared_delta` from the payload.

## Loop protocol

### On `start "<goal>"`

1. `Bash: agent-loop init-run --goal "<goal>" --slug "<short-slug>"`
   → JSON `{run_id, run_dir}`. Remember `run_id`.
2. Apply **plan-from-goal** (see `plan-from-goal.md`) →
   produce `plan.md` body and the Round 1 prompt body (with Reading List).
3. Write `plan.md` (via `Write` to `<run_dir>/plan.md`) and the prompt file.
4. `Bash: agent-loop init-round --run <run_id> --prompt-file <path>`
   → JSON `{round_n, prompt_path}`.
5. Enter the round loop (below).

### Round loop (repeat until APPROVE or STOP_FOR_USER)

1. `Bash: agent-loop dispatch --run <run_id> --round <N>`
   → JSON payload summary (result_summary, diff_summary, safety_flags, artifact_paths, shared_delta).
2. Read `<run_dir>/memo.md` (entire).
3. Read `<run_dir>/rounds/NN/claude-result.md` (entire — this round's report).
4. Apply **round-review** (see `round-review.md`) → decide `APPROVE | NEEDS_CHANGES | STOP_FOR_USER`, write `codex-review.md` body.
5. `Bash: agent-loop write-review --run <run_id> --round <N> --decision <X> --review-file <path>`.
6. Apply **round-memo** (see `round-memo.md`) → 5–10 line memo body.
7. `Bash: agent-loop append-memo --run <run_id> --round <N> --memo-file <path>`.
8. Branch:
   - **APPROVE** → `Bash: agent-loop finalize --run <run_id>` → end session.
   - **STOP_FOR_USER** → stop here, wait for user input. Do NOT call dispatch again until user says `/agent-loop continue`.
   - **NEEDS_CHANGES** → apply **plan-from-review** (see `plan-from-review.md`) → next prompt body, then loop step 1 (`init-round` then `dispatch`).

### On `continue`

1. `Bash: agent-loop continue [--run <id>]`
   → JSON `{action, notes, options, run_id, current_round}`.
2. Follow `resume-run.md` to interpret the action.

## STOP_FOR_USER triggers

Treat any of these as STOP_FOR_USER without consulting the user via prompt — just stop and tell the user what happened:

- `safety_flags` is non-empty in the payload
- `result_summary.requires_user` is true (parsed from claude-result.md)
- `claude_decision_hint` is `blocked`

## Forbidden actions

- Never run `git commit`, `git push`, or any destructive command yourself. Final integration is the user's job.
- Never read raw diff/test-log/messages files. Use `inspect` only.
- Never invent the Python CLI's behavior — if a command's JSON doesn't match expectations, stop and tell the user.

## File paths

- Run root: `<target_repo>/.agent-loop/runs/<run_id>/`
- Round dir: `<run_root>/rounds/NN/`
- Shared: `<run_root>/shared/`
