---
name: agent-loop
description: When the user types `/agent-loop start "<goal>"` (or `/agent-loop continue`), this skill turns the current Claude session into the supervisor of a bounded review loop. Codex CLI (headless `codex exec --json`) does planning and review; Claude subagents (Task tool) do implementation; the supervisor (this Claude session) only reads tiny status JSON. Artifacts in `.agent-loop/runs/<id>/`.
---

# agent-loop — Claude Supervisor Skill

You are the supervisor of a bounded review loop. Your context must stay lean. The heavy thinking lives in Codex subprocess calls and in worker subagents; you only see filenames and tiny status JSON.

## Preflight — verify dependencies BEFORE the first Bash call

The `agent-loop` CLI is NOT bundled inside this plugin. It lives in a separate Python package the user installs with `pip install -e python/`. Verify it's reachable from this session before doing anything else:

1. `Bash: agent-loop --help` (or `agent-loop status`). Expected: a non-zero usage banner.
2. If you get `command not found`: STOP. Tell the user to install the Python core:
   ```bash
   cd <repo>/python && python -m venv .venv && .venv/bin/pip install -e ".[dev]"
   export PATH="$PWD/.venv/bin:$PATH"
   ```
   On Windows PowerShell use `.\.venv\Scripts\Activate.ps1`. Then ask them to restart this session so the new PATH is picked up.
3. Do NOT go hunting for an `agent-loop` binary inside `~/.claude/plugins/...` — the plugin cache contains only markdown skills, never executables.
4. Also verify Codex CLI: `Bash: codex --version`. If missing, tell the user to install Codex CLI and run `codex login`.

Skip this preflight only if you've already verified both CLIs earlier in the same session.

## Required reading on first invocation per session

- `references/claude-prompt-template.md` — what Codex drafts for each round
- `references/claude-result-schema.md` — what the worker writes back
- `references/review-payload-schema.md` — what Codex sees when reviewing

You do NOT need to re-read these every invocation; trust the schemas.

## Context discipline (mandatory)

- You never read full diffs, test logs, claude-result.md, claude-prompt.md, or codex-review.md.
- You only ingest the small JSON each CLI subcommand emits.
- For details, you can run `agent-loop inspect --round N --file X --lines a-b` to extract a slice.
- You never call `codex exec` or `codex` directly — always via `agent-loop plan-init|plan-round|review-round`.

## Loop protocol — On `start "<goal>"`

1. `Bash: agent-loop init-run --goal "<goal>" --slug "<short-slug>"`
   → JSON `{run_id, run_dir}`. Remember `run_id`.
2. `Bash: agent-loop plan-init --run <run_id>`
   → JSON `{plan_path, summary}`. (Codex drafted plan.md on disk.)
3. Enter round loop (next section).

## Round loop (repeat until APPROVE / STOP_FOR_USER)

For each round N (starting at 1):

1. `Bash: agent-loop plan-round --run <run_id>`
   → JSON `{round_n, prompt_path, summary}`. (Codex drafted the worker prompt.)
2. `Bash: agent-loop capture-baseline`
   → JSON `{baseline}`. Save the sha.
3. **Dispatch worker subagent via Task tool.** The subagent prompt:

   ```
   Task tool (general-purpose):
     description: "Worker round N for <run_id>"
     prompt: |
       Read .agent-loop/runs/<run_id>/rounds/NN/claude-prompt.md and implement
       what it specifies. Strict rules:
       - Follow the Required Reading list in that prompt. Do NOT read Out of Scope.
       - Append a line to .agent-loop/runs/<run_id>/rounds/NN/progress.md
         at each meaningful step ([done] / [doing] / [planned]).
       - Append durable facts to .agent-loop/runs/<run_id>/shared/knowledge.md.
       - Append design decisions to .agent-loop/runs/<run_id>/shared/decisions.md.
       - Append open questions to .agent-loop/runs/<run_id>/shared/open-questions.md.
       - At the end, write .agent-loop/runs/<run_id>/rounds/NN/claude-result.md
         following the schema in your prompt.
       - Run: `agent-loop record-diff --run <run_id> --round N --baseline <baseline>`
       - Run: `agent-loop mark-worker-done --run <run_id> --round N`
       - Forbidden: git commit, git push, rm -rf, sudo, db migrations,
         writes to .env / secrets / migrations.
       - Reply to the supervisor with ONE concise paragraph summarizing
         what changed (file count + brief outcome). Do NOT paste the full
         result.md or diff into your reply.
   ```

4. After Task tool returns, run: `Bash: agent-loop review-round --run <run_id> --round N`
   → JSON `{decision, review_path, safety_flags}`. Decision is one of APPROVE / NEEDS_CHANGES / STOP_FOR_USER.
5. `Bash: agent-loop append-memo --run <run_id> --round N --memo-file <path>` — supply a 5-10 line memo derived from the codex-review.md (you may briefly read codex-review.md if needed, but prefer using just the JSON decision and your own brief notes; remember context discipline).
6. Branch on `decision`:
   - `APPROVE` → `Bash: agent-loop finalize --run <run_id>`. Tell the user the run completed; point them at `final-report.md`. END.
   - `STOP_FOR_USER` → Tell the user the loop paused; show `safety_flags` and point at `codex-review.md`. END.
   - `NEEDS_CHANGES` → Loop back to step 1 (next round).

## Loop protocol — On `continue`

1. `Bash: agent-loop continue` (optionally `--run <id>`)
   → JSON `{action, notes, options, run_id, current_round}`.
2. Interpret `action`:
   - `plan_round` → start a fresh round at step 1 of the round loop
   - `claude_completed` (worker done but no review yet) → go straight to step 4 (review-round)
   - `reviewed` → step 5 (append-memo) and then branch
   - `user_confirm` → tell the user the options and wait

## Forbidden actions

- Never run `git commit`, `git push`, or any destructive command yourself.
- Never read full diff/result/log files into your context. Use `inspect` with narrow `--lines` only when the JSON status is insufficient.
- Never invent CLI behavior — if a subcommand's JSON doesn't match what you expected, stop and report to the user.

## File path conventions

- Run root: `<target_repo>/.agent-loop/runs/<run_id>/`
- Round dir: `<run_root>/rounds/NN/`
- Shared memory: `<run_root>/shared/`
