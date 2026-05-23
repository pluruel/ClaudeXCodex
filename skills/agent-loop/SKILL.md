---
name: agent-loop
description: When the user types `/ClaudeXCodex:agent-loop <goal>` (start a new run; quotes around the goal are optional) or `/ClaudeXCodex:agent-loop` with no text (resume an interrupted run), this skill turns the current Claude session into the supervisor of a bounded review loop. Codex CLI (headless `codex exec --json`) does planning and review; Claude subagents (Task tool) do implementation; the supervisor (this Claude session) only reads tiny status JSON. Artifacts in `.agent-loop/runs/<id>/`.
---

# agent-loop — Claude Supervisor Skill

You are the supervisor of a bounded review loop. Your context must stay lean. The heavy thinking lives in Codex subprocess calls and in worker subagents; you only see filenames and tiny status JSON.

## Invocation grammar

- `/ClaudeXCodex:agent-loop <goal text>` — start a new run. Everything after `/ClaudeXCodex:agent-loop ` is the goal. Quotes are NOT required, e.g. `/ClaudeXCodex:agent-loop fix the login bug`. If the user did quote it (`/ClaudeXCodex:agent-loop "fix the login bug"`), strip the outer quotes before passing along.
- `/ClaudeXCodex:agent-loop` (no text after) — resume the most recently active run.
- `/ClaudeXCodex:agent-loop continue` — explicit resume form; also accepted.

Decision rule: if the message after `/ClaudeXCodex:agent-loop` is empty or is exactly the word `continue`, treat as resume. Otherwise treat the whole remainder as the goal and follow "On start" below.

## CLI invocation convention

The CLI is bundled inside this plugin and exposed through the plugin's `bin/agent-loop` wrapper. Invoke it by absolute plugin path so the workflow does not depend on Bash `PATH` setup:

```
"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" <subcommand> ...
```

The wrapper resolves `${CLAUDE_PLUGIN_ROOT}` when available and otherwise infers the plugin root from its own location. It then executes `${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py`, so no `pip install` is required.

## Preflight — verify dependencies BEFORE the first real bash call

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" --help`. Expected: usage banner listing subcommands (`init-run`, `plan-init`, ...).
2. If `python` isn't found: tell the user to install Python 3.11+ and retry. (On some systems the binary is `python3`; if so use that consistently in every subsequent call.)
3. If `${CLAUDE_PLUGIN_ROOT}` is empty or `bin/agent-loop` is missing, report that the plugin install did not expose the plugin root correctly. The user can try `/plugin marketplace update claudexcodex`, then `/plugin install ClaudeXCodex@claudexcodex`, then `/reload-plugins`.
4. If you see `No module named agent_loop` or `FileNotFoundError`: report it — the plugin install is incomplete. The user can try `/plugin marketplace update claudexcodex`.
5. Also verify Codex CLI: `Bash: codex --version`. If missing, tell the user to install Codex CLI and run `codex login`.

Skip this preflight only if you've already verified both deps earlier in the same session.

## Internal schemas (do NOT read)

This plugin ships schema docs at `${CLAUDE_PLUGIN_ROOT}/skills/references/` for the curious. **The supervisor does not need to read them** — the CLI takes care of all schema generation/validation. Read them only if you're debugging unexpected JSON output from a subcommand.

## Artifact mode

The default artifact mode is `compact`. After a clean review, the CLI keeps the
durable files (`claude-prompt.md`, `claude-result.md`, `codex-review.md`, and
`review-payload.json`, plus the run-level state/memo/report files) and removes
intermediate files such as `diff.patch`, `diff-stats.json`, and `progress.md`.

If a run needs deep debugging, the user can create `.agent-loop/config.toml` in
the target repo with:

```toml
[artifacts]
mode = "debug"
```

## Worker model selection

`plan-round` emits `worker_model` (`haiku`, `sonnet`, or `opus` by default),
`worker_model_reason`, `scope` (`narrow` | `normal` | `broad`), and
`round_plan_path`. The CLI ALSO injects a canonical `## Worker Model` section
into the generated `claude-prompt.md`, so the worker subagent sees the same
routing decision even when it is dispatched without a model override.

How to act on it when dispatching the Task tool:

1. If Claude Code exposes a per-call model override in this environment, set
   it to the selected `worker_model`. The Task tool's accepted aliases vary
   across environments; use whichever of `haiku` / `sonnet` / `opus` (or their
   environment-specific full IDs) the tool accepts. If the tool rejects the
   alias, fall back to step 2 -- do not silently route to a different model.
2. Always paste `worker_model`, `worker_model_reason`, and `scope` verbatim
   into the worker prompt's leading lines (see the Task dispatch sample
   below). The CLI-injected `## Worker Model` section inside
   `claude-prompt.md` is the durable record; the supervisor's restated lines
   are a visible reminder.

Scope-to-effort mapping (use to choose / justify the model and to constrain
the worker even when no model override is available):

- `narrow` + `haiku` - mechanical, mostly execute the provided plan, minimal
  Suggested Reading
- `normal` + `sonnet` - integration work, moderate uncertainty, limited
  Suggested Reading allowed
- `broad` + `opus` - architecture / broad debugging / high-risk safety or
  security changes; deeper reasoning expected, deviations must be justified
  in `claude-result.md`

If `scope` and `worker_model` disagree (e.g. `broad` + `haiku`), trust the
model alias for routing but raise the mismatch with the user before
dispatching -- this usually indicates the round plan needs another pass.

## Context discipline (mandatory)

- You never read full diffs, test logs, claude-result.md, claude-prompt.md, or codex-review.md. Not even "one quick pass." The memo is auto-composed by `review-round`; you have no reason to open the review file.
- You only ingest the small JSON each CLI subcommand emits.
- For details, you can run the CLI's `inspect` subcommand with narrow `--lines` to extract a slice — but only when JSON is genuinely insufficient (rare). `--lines` accepts `N` (first N), `N-` (from N onward), or `A-B` (range). Example: `agent-loop inspect --run <id> --round N --file claude-result.md --lines 80`.
- You never call `codex exec` or `codex` directly — always via the CLI's `plan-init|plan-round|review-round` subcommands.

## On start (`/ClaudeXCodex:agent-loop <goal text>`)

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" init-run --goal "<goal>" --slug "<short-slug>"`
   → JSON `{run_id, run_dir}`. Remember `run_id`.
2. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" plan-init --run <run_id>`
   → JSON `{plan_path, summary}`. (Codex drafted plan.md on disk.)
3. Enter round loop (next section).

## Round loop (repeat until APPROVE / STOP_FOR_USER)

For each round N (starting at 1):

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" plan-round --run <run_id>`
   → JSON `{round_n, prompt_path, round_plan_path, worker_model, worker_model_reason, scope, summary}`. (Codex drafted the worker prompt and selected the worker model; the CLI normalized the selection and injected a `## Worker Model` section into the prompt.)
2. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" capture-baseline`
   → JSON `{baseline}`. Save the sha.
3. **Announce the round to the user** (one line, verbatim format, BEFORE dispatch):

   ```
   Round N — worker: <worker_model> (<worker_model_reason>), scope: <scope>
   ```

   Use the values returned by `plan-round` in step 1. This is the only piece of
   round-level routing information that surfaces to the user without them having
   to open files; do not skip it, do not paraphrase it.

4. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" mark-dispatched --run <run_id> --round N`
   → JSON `{round, phase}`. This records that the worker handoff started.

   ### Worker model dispatch

   The Task tool's per-call model parameter is environment-dependent. Two
   regimes you may encounter:

   - **Per-call `model` supported** (current Claude Code default in most
     environments): pass `model: <worker_model>` as a top-level Task argument
     (alongside `description` and `prompt`). The accepted aliases vary —
     `haiku` / `sonnet` / `opus` are the canonical short forms; full IDs (e.g.
     `claude-haiku-4-5`, `claude-sonnet-4-7`, `claude-opus-4-7`) also work
     when the host accepts them. If the alias is rejected, do NOT silently
     route to the default — fall back to the next bullet.
   - **Per-call `model` NOT supported** (some embedded / restricted hosts):
     omit the `model` field. The CLI-injected `## Worker Model` section
     already inside `claude-prompt.md` is the durable record of which model
     the worker is scoped to, and the leading lines of the Task prompt (see
     example below) restate it visibly. The subagent will run on the host's
     default model but stay scoped to the worker_model-shaped task because
     the prompt itself was sized for that model.

   Either way, the `Round N — worker: …` echo line from step 3 stays visible
   in the supervisor transcript, so the user can see the routing decision
   regardless of which dispatch regime applies.

5. **Dispatch worker subagent via Task tool.** The subagent inherits `${CLAUDE_PLUGIN_ROOT}` from the supervisor. If the Task tool accepts a per-call model override, set it to `<worker_model>`. The subagent prompt:

   ```
   Task tool (general-purpose):
     description: "Worker round N for <run_id>"
     model: <worker_model>   # haiku | sonnet | opus — drop this field if the host rejects per-call model
     prompt: |
       Codex selected worker model: <worker_model>
       Reason: <worker_model_reason>
       Scope: <scope>                                            # narrow | normal | broad
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
       - Treat the prompt's Execution Plan as the default path. If code reading
         proves it wrong or incomplete, make the smallest justified deviation
         and record it under Plan Deviations in claude-result.md.
       - Run: `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" record-diff --run <run_id> --round N --baseline <baseline>`
       - Run: `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" mark-worker-done --run <run_id> --round N`
       - Forbidden: git commit, git push, rm -rf, sudo, db migrations,
         writes to .env / secrets / migrations.
       - Reply to the supervisor with EXACTLY ONE LINE:
           OK
         on success, or
           FAIL: <one sentence>
         on failure. Nothing else. No summary, no file list, no rationale.
         The supervisor reads state.json and review JSON for everything else.
   ```

6. After Task tool returns, run: `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" review-round --run <run_id> --round N`
   → JSON `{decision, review_path, safety_flags, memo_appended, memo_path}`. Decision is one of APPROVE / NEEDS_CHANGES / STOP_FOR_USER. `review-round` automatically parses the Codex review and appends the round memo to `memo.md`; do not call `append-memo` yourself.
7. Branch on `decision`:
   - `APPROVE` → `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" finalize --run <run_id>`. Tell the user the run completed; point them at `final-report.md`. END.
   - `STOP_FOR_USER` → Tell the user the loop paused; show `safety_flags` and point at `codex-review.md` (for the human, not for you). END.
   - `NEEDS_CHANGES` → Loop back to step 1 (next round).

## On continue (`/ClaudeXCodex:agent-loop` or `/ClaudeXCodex:agent-loop continue`)

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" continue` (optionally `--run <id>`)
   → JSON `{action, notes, options, run_id, current_round}`.
2. Interpret `action`:
   - `plan_round` → start a fresh round at step 1 of the round loop
   - `dispatch` → re-announce the round (step 3), run `mark-dispatched` (step 4), then dispatch the worker (step 5)
   - `advance_to_review` → worker result exists but review has not run; go straight to step 6 (`review-round`)
   - `write_review` → same as `advance_to_review`: run review-round (also re-composes memo if missing)
   - `write_memo` → review-round was interrupted before memo append. Re-run review-round; it will re-invoke Codex and re-append the memo idempotently.
   - `branch_decision` → review and memo are done; go straight to step 7 (decision branch)
   - `finalize` → call finalize if the last completed round was approved
   - `user_confirm` → tell the user the options and wait

## Forbidden actions

- Never run `git commit`, `git push`, or any destructive command yourself.
- Never read full diff/result/log files into your context. Use the `inspect` subcommand with narrow `--lines` only when the JSON status is insufficient. `--lines` accepts `N` (first N), `N-` (from N onward), or `A-B` (range).
- Never invent CLI behavior — if a subcommand's JSON doesn't match what you expected, stop and report to the user.

## File path conventions

- Run root: `<target_repo>/.agent-loop/runs/<run_id>/`
- Round dir: `<run_root>/rounds/NN/`
- Shared memory: `<run_root>/shared/`
