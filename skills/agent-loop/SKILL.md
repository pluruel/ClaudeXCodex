---
name: agent-loop
description: When the user types `/agent-loop "<goal>"` (start a new run) or `/agent-loop` with no goal (resume an interrupted run), this skill turns the current Claude session into the supervisor of a bounded review loop. Codex CLI (headless `codex exec --json`) does planning and review; Claude subagents (Task tool) do implementation; the supervisor (this Claude session) only reads tiny status JSON. Artifacts in `.agent-loop/runs/<id>/`.
---

# agent-loop — Claude Supervisor Skill

You are the supervisor of a bounded review loop. Your context must stay lean. The heavy thinking lives in Codex subprocess calls and in worker subagents; you only see filenames and tiny status JSON.

## Invocation grammar

- `/agent-loop "<goal>"` — start a new run with the given goal.
- `/agent-loop` (no quoted arg) — resume the most recently active run (equivalent to the old `/agent-loop continue`).
- `/agent-loop continue` — explicit form of resume; also accepted.

Pick the right path based on what the user typed. If they passed a goal in quotes, follow "On start" below. Otherwise follow "On continue".

## CLI invocation convention

The Python CLI is bundled inside this plugin. Claude Code exposes its path via `${CLAUDE_PLUGIN_ROOT}`. Invoke the CLI as a plain Python script — **no `pip install` step is required**:

```
python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" <subcommand> ...
```

Bind it to a shell variable once and reuse:

```
AL="python \"${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py\""
$AL init-run --goal "..." --slug "..."
```

(Shell state does not persist between Claude Code Bash tool calls, so you'll re-export `AL` at the top of each Bash call or just paste the full path. The full-path form is fine and shown literally throughout this skill.)

Power-user shortcut: if the user has manually run `pip install -e python/` and added the venv's `Scripts/`/`bin/` to PATH, plain `agent-loop ...` also works. Do NOT rely on that; default to the `${CLAUDE_PLUGIN_ROOT}` form.

## Preflight — verify dependencies BEFORE the first real bash call

1. `Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" --help`. Expected: usage banner listing subcommands (`init-run`, `plan-init`, ...).
2. If `python` isn't found: tell the user to install Python 3.11+ and retry.
3. If you see `No module named agent_loop` or `FileNotFoundError`: report it — the plugin install is incomplete. The user can try `/plugin marketplace update claudexcodex`.
4. Do NOT hunt for an `agent-loop` binary anywhere — the only thing that matters is `${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py` being executable by Python.
5. Also verify Codex CLI: `Bash: codex --version`. If missing, tell the user to install Codex CLI and run `codex login`.

Skip this preflight only if you've already verified both deps earlier in the same session.

## Internal schemas (do NOT read)

This plugin ships schema docs at `${CLAUDE_PLUGIN_ROOT}/skills/references/` for the curious. **The supervisor does not need to read them** — the CLI takes care of all schema generation/validation. Read them only if you're debugging unexpected JSON output from a subcommand.

## Context discipline (mandatory)

- You never read full diffs, test logs, claude-result.md, claude-prompt.md, or codex-review.md.
- You only ingest the small JSON each CLI subcommand emits.
- For details, you can run the CLI's `inspect` subcommand with narrow `--lines` to extract a slice.
- You never call `codex exec` or `codex` directly — always via the CLI's `plan-init|plan-round|review-round` subcommands.

## On start (`/agent-loop "<goal>"`)

1. `Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" init-run --goal "<goal>" --slug "<short-slug>"`
   → JSON `{run_id, run_dir}`. Remember `run_id`.
2. `Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" plan-init --run <run_id>`
   → JSON `{plan_path, summary}`. (Codex drafted plan.md on disk.)
3. Enter round loop (next section).

## Round loop (repeat until APPROVE / STOP_FOR_USER)

For each round N (starting at 1):

1. `Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" plan-round --run <run_id>`
   → JSON `{round_n, prompt_path, summary}`. (Codex drafted the worker prompt.)
2. `Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" capture-baseline`
   → JSON `{baseline}`. Save the sha.
3. **Dispatch worker subagent via Task tool.** The subagent inherits `${CLAUDE_PLUGIN_ROOT}` from the supervisor. The subagent prompt:

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
       - Run: `python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" record-diff --run <run_id> --round N --baseline <baseline>`
       - Run: `python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" mark-worker-done --run <run_id> --round N`
       - Forbidden: git commit, git push, rm -rf, sudo, db migrations,
         writes to .env / secrets / migrations.
       - Reply to the supervisor with ONE concise paragraph summarizing
         what changed (file count + brief outcome). Do NOT paste the full
         result.md or diff into your reply.
   ```

4. After Task tool returns, run: `Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" review-round --run <run_id> --round N`
   → JSON `{decision, review_path, safety_flags}`. Decision is one of APPROVE / NEEDS_CHANGES / STOP_FOR_USER.
5. `Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" append-memo --run <run_id> --round N --memo-file <path>` — supply a 5-10 line memo derived from the codex-review.md (you may briefly read codex-review.md if needed, but prefer using just the JSON decision and your own brief notes; remember context discipline).
6. Branch on `decision`:
   - `APPROVE` → `Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" finalize --run <run_id>`. Tell the user the run completed; point them at `final-report.md`. END.
   - `STOP_FOR_USER` → Tell the user the loop paused; show `safety_flags` and point at `codex-review.md`. END.
   - `NEEDS_CHANGES` → Loop back to step 1 (next round).

## On continue (`/agent-loop` or `/agent-loop continue`)

1. `Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" continue` (optionally `--run <id>`)
   → JSON `{action, notes, options, run_id, current_round}`.
2. Interpret `action`:
   - `plan_round` → start a fresh round at step 1 of the round loop
   - `claude_completed` (worker done but no review yet) → go straight to step 4 (review-round)
   - `reviewed` → step 5 (append-memo) and then branch
   - `user_confirm` → tell the user the options and wait

## Forbidden actions

- Never run `git commit`, `git push`, or any destructive command yourself.
- Never read full diff/result/log files into your context. Use the `inspect` subcommand with narrow `--lines` only when the JSON status is insufficient.
- Never invent CLI behavior — if a subcommand's JSON doesn't match what you expected, stop and report to the user.

## File path conventions

- Run root: `<target_repo>/.agent-loop/runs/<run_id>/`
- Round dir: `<run_root>/rounds/NN/`
- Shared memory: `<run_root>/shared/`
