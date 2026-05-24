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
- `/ClaudeXCodex:agent-loop --plan <path>` — start execution using an existing plan file. The file must contain `authorized: CLAUDE_X_CODEX_PLAN` in its YAML frontmatter.

Decision rule: if the message after `/ClaudeXCodex:agent-loop` is empty or is exactly the word `continue`, treat as resume. If it starts with `--plan `, treat as `--plan <file>` invocation and follow "On start with `--plan <file>`" below. Otherwise treat the whole remainder as the goal and follow "On start" below.

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
durable files (`claude-prompt.md`, `codex-review.md`, and
`review-payload.json`, plus the run-level state/memo/report files) and removes
intermediate files such as `diff.patch`, `diff-stats.json`, and `progress.md`.

If a run needs deep debugging, the user can create `.agent-loop/config.toml` in
the target repo with:

```toml
[artifacts]
mode = "debug"
```

## Worker model selection

`plan-round` emits round-level metadata: `worker_model` (`haiku`, `sonnet`, or `opus`),
`worker_model_reason`, `reasoning_effort` (`low` | `medium` | `high`, default `medium`),
`subtasks` (list), and `round_plan_path`. The round-level fields are the **dominant
character** of the round — used for the user-facing announce line and as the fallback
model when `subtasks` is missing or invalid. The per-subtask `model` and
`reasoning_effort` fields govern actual dispatch when `subtasks` is present and valid.

### Subtask roles and dispatch rules

When `subtasks` is present and valid, the round is decomposed into typed subtasks:

| role | authority | parallelism | constraint |
|---|---|---|---|
| `analysis` | read code/docs; write to `shared/*` only | all siblings dispatch in parallel (no `depends_on` between them) | must NOT edit source files or tests |
| `implementation` | patch source files, tests, configs | dispatched after all declared `depends_on` analysis ids complete | must NOT write to `shared/*` as scratch; only `decisions.md`, `knowledge.md`, `open-questions.md` |
| `verification` | run named check commands; report pass/fail | dispatched after all implementation subtasks in this round complete | must name an explicit command in its deliverable |

Each subtask carries:
- `id` — unique within the round
- `role` — `analysis | implementation | verification`
- `model` — the worker model alias for this subtask
- `reasoning_effort` — `low | medium | high`
- `required_reading` — list of file paths (max 5; split the subtask if more are needed)
- `out_of_scope` — list of paths/patterns the worker must not read or edit
- `depends_on` — list of same-round subtask ids that must complete first
- `deliverable` — what the subtask must produce before it is considered done

### Per-subtask reasoning_effort

When dispatching a subtask via the Task tool:

1. If the host exposes a native `reasoning_effort` or equivalent thinking-budget
   parameter, set it to the subtask's `reasoning_effort` value. Do not assume a
   specific parameter name — only set it if local Claude Code docs already establish one.
2. If the host does NOT expose a native reasoning parameter, inject the subtask's
   `reasoning_effort` as a visible prompt line:
   ```
   Reasoning effort: <reasoning_effort>   # hint only — native budget not available
   ```
   This is the worker's only knob in that environment; keep it visible.

Typical mappings (trust `plan-round`; do not rewrite):
- `haiku` → `low` effort — mechanical execution, minimal reading
- `sonnet` → `medium` effort — integration, moderate uncertainty
- `opus` → `high` effort — architecture, high-risk, deviations must be justified

`reasoning_effort` and `model` are independent axes. A `haiku` subtask may
use `high` effort if the few changes touch deep architecture; trust whatever the round
plan emitted.

### How to act on the round-level fields

- Use `worker_model`, `worker_model_reason`, and `reasoning_effort` for the announce line (step 3 of round loop).

## Context discipline (mandatory)

- You never read full diffs, test logs, claude-prompt.md, or codex-review.md. Not even "one quick pass." The memo is auto-composed by `review-round`; you have no reason to open the review file.
- You only ingest the small JSON each CLI subcommand emits.
- For details, you can run the CLI's `inspect` subcommand with narrow `--lines` to extract a slice — but only when JSON is genuinely insufficient (rare). `--lines` accepts `N` (first N), `N-` (from N onward), or `A-B` (range). Example: `agent-loop inspect --run <id> --round N --file codex-review.md --lines 80`.
- You never call `codex exec` or `codex` directly — always via the CLI's `plan-init|plan-round|review-round` subcommands.

## On start with `--plan <file>`

1. Read the first 10 lines of `<file>` to check for `authorized: CLAUDE_X_CODEX_PLAN` in YAML frontmatter (between `---` delimiters at the top).

2. **Token absent** → Tell the user:
   > "This file doesn't have the `authorized: CLAUDE_X_CODEX_PLAN` token. Run `/ClaudeXCodex:plan --file <path>` to review and authorize it first."
   END.

3. **Token present** → Run:
   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" init-run \
     --goal "<extract Goal section from file, or use filename as fallback>" \
     --slug "<short-slug from filename>" \
     --plan-file "<path>"
   ```
   → JSON `{run_id, run_dir}`. Remember `run_id`.

4. Run `plan-init --run <run_id>`. Verify `"plan_source": "pre-existing"` in output.

5. Enter the normal round loop.

## On start (`/ClaudeXCodex:agent-loop <goal text>`)

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" init-run --goal "<goal>" --slug "<short-slug>"`
   → JSON `{run_id, run_dir}`. Remember `run_id`.
2. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" plan-init --run <run_id>`
   → JSON `{plan_path, phases, summary}`. (Codex drafted plan.md and phase docs on disk.)
3. Enter round loop (next section).

## Round loop (repeat until APPROVE / PHASE_COMPLETE)

For each round N (starting at 1):

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" plan-round --run <run_id>`
   → JSON `{round_n, current_phase, total_phases, prompt_path, round_plan_path, worker_model, worker_model_reason, reasoning_effort, summary}`. (Codex drafted the worker prompt and selected the worker model; the CLI normalized the selection and injected a `## Worker Model` section into the prompt.)
2. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" capture-baseline`
   → JSON `{baseline}`. Save the sha.
3. **Announce the round to the user** (one line, verbatim format, BEFORE dispatch):

   ```
   Phase <current_phase>/<total_phases> · Round N — worker (dominant): <worker_model> (<worker_model_reason>), effort: <reasoning_effort> — subtasks: <count> (analysis×<a>, implementation×<i>, verification×<v>)
   ```

   Use the values returned by `plan-round` in step 1. Count each role from the
   `subtasks` list. If `subtasks` is absent or invalid, use `subtasks: 1 (fallback)`
   for the count portion. This line is the only round-level routing information that
   surfaces to the user without them opening files; do not skip or paraphrase it.

4. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" mark-dispatched --run <run_id> --round N`
   → JSON `{round, phase}`. Records that worker handoff started.

5. **Dispatch worker subagent(s) via Task tool.**

   ### 5a — Check for valid subtasks

   Inspect the `subtasks` field from the `plan-round` JSON (step 1). If it is present,
   non-empty, and each entry has at minimum `id`, `role`, `model`, `reasoning_effort`,
   and `deliverable`, proceed to **5b (subtask fan-out)**.

   ### 5b — Subtask fan-out (default path)

   The subagent inherits `${CLAUDE_PLUGIN_ROOT}` from the supervisor.

   **Per-subtask announce (mandatory, BEFORE every Task tool call in this round):**

   The Task tool's terminal rendering does NOT display the per-call `model`
   parameter — the user sees only `Agent(description)` while a subtask runs.
   To make routing visible without forcing the user to open files, the
   supervisor MUST emit one markdown bullet immediately before each Task
   call. Use this EXACT format (bold id, backticked model, italicized
   reasoning_effort) so the line stands out in the terminal:

   ```
   - **<subtask.id>** → `<subtask.model>` *(<subtask.reasoning_effort>)* — <one-sentence goal>
   ```

   Example block (rendered by the chat client as a real bulleted list):

   ```
   - **r2-a1** → `sonnet` *(high)* — audit [worker_reasoning] wiring end-to-end
   - **r2-a2** → `sonnet` *(high)* — audit round_plan.json / depends_on consistency
   - **r2-i1** → `sonnet` *(medium)* — apply targeted fixes from r2-a1 / r2-a2
   - **r2-v1** → `haiku` *(low)* — run pytest sweep + invariant grep
   ```

   When multiple subtasks fan out in parallel (analysis phase), emit the
   bullets as one contiguous list, then send the parallel Task calls together
   in the SAME assistant turn. The bullets are plain user-facing markdown —
   not tool calls, not stored in any file — emitted purely so the user can
   see at a glance which model is handling which slice as the transcript
   scrolls.

   **Phase 1 — Analysis (parallel):**
   Collect all subtasks with `role: analysis`. Dispatch them simultaneously as
   independent Task tool calls (no `depends_on` between siblings). Per-subtask prompt:

   ```
   Task tool (general-purpose):
     description: "Round N / <subtask_id> (analysis) for <run_id>"
     model: <subtask.model>   # drop if host rejects per-call model
     prompt: |
       You are subtask <subtask.id> (role=analysis, model=<subtask.model>,
       reasoning_effort=<subtask.reasoning_effort>)
       inside agent-loop run <run_id>, round N.

       Strict role rules:
       - You are an ANALYSIS subtask. You MUST NOT modify any source code, config,
         or docs. No Edit, no Write outside .agent-loop/runs/<run_id>/shared/ and
         .../rounds/NN/progress.md.
       - Do NOT run record-diff or mark-worker-done.

       Reasoning effort: <subtask.reasoning_effort>

       Required Reading (in order):
       <subtask.required_reading — one path per line>

       Out of Scope (do not read or edit):
       <subtask.out_of_scope — one path per line>

       Deliverable: <subtask.deliverable>

       When finished, APPEND to .agent-loop/runs/<run_id>/shared/decisions.md
       (heading: ## Round N / <subtask.id> — <one-phrase summary>) and append
       a line to .../rounds/NN/progress.md:
         [done] <subtask.id> <deliverable summary>

       Reply with EXACTLY ONE LINE:
         OK
       on success, or
         FAIL: <one sentence>
       on failure. No other output.
   ```

   Wait for ALL analysis Task tool calls to return before Phase 2.

   **Phase 2 — Implementation (dependency-ordered):**
   Collect all subtasks with `role: implementation`. Sort by `depends_on` so that
   a subtask is dispatched only after every id in its `depends_on` list has returned
   OK. If multiple implementation subtasks share no dependencies between each other,
   dispatch them in parallel. Per-subtask prompt:

   ```
   Task tool (general-purpose):
     description: "Round N / <subtask_id> (implementation) for <run_id>"
     model: <subtask.model>   # drop if host rejects per-call model
     prompt: |
       You are subtask <subtask.id> (role=implementation, model=<subtask.model>,
       reasoning_effort=<subtask.reasoning_effort>)
       inside agent-loop run <run_id>, round N.

       Strict role rules:
       - You are an IMPLEMENTATION subtask. You MAY edit source files, tests,
         and configs within the scope of your deliverable.
       - Do NOT run record-diff or mark-worker-done (the supervisor calls these
         once after all subtasks complete).
       - Append progress to .../rounds/NN/progress.md.
       - Append durable facts to .../shared/knowledge.md.
       - Append design decisions to .../shared/decisions.md.
       - Append open questions to .../shared/open-questions.md.

       Reasoning effort: <subtask.reasoning_effort>

       Context from analysis phase: see .agent-loop/runs/<run_id>/shared/

       Required Reading (in order):
       <subtask.required_reading — one path per line>

       Out of Scope (do not read or edit):
       <subtask.out_of_scope — one path per line>

       Depends on (already complete): <subtask.depends_on — comma-separated ids>

       Deliverable: <subtask.deliverable>

       Forbidden: git commit, git push, rm -rf, sudo, db migrations,
       writes to .env / secrets / migrations.

       Reply with EXACTLY ONE LINE:
         OK
       on success, or
         FAIL: <one sentence>
       on failure. No other output.
   ```

   Wait for ALL implementation Task tool calls to return before Phase 3.

   **Phase 3 — Verification (sequential or parallel as declared):**
   Collect all subtasks with `role: verification`. Each verification subtask must
   name an explicit check command in its `deliverable`. Dispatch them (in parallel
   if they have no mutual dependencies). Per-subtask prompt:

   ```
   Task tool (general-purpose):
     description: "Round N / <subtask_id> (verification) for <run_id>"
     model: <subtask.model>   # drop if host rejects per-call model
     prompt: |
       You are subtask <subtask.id> (role=verification, model=<subtask.model>,
       reasoning_effort=<subtask.reasoning_effort>)
       inside agent-loop run <run_id>, round N.

       Strict role rules:
       - You are a VERIFICATION subtask. You MUST NOT edit source files.
       - Run the exact command(s) specified in your deliverable. Report pass/fail
         and captured output.
       - Append progress to .../rounds/NN/progress.md.

       Deliverable (includes named check command): <subtask.deliverable>

       After all commands finish:
       1. APPEND to `shared/test-results.md` under heading `## <subtask.id>`:
          Status: PASS|FAIL
          <failure details if FAIL>
          (Sequential depends_on ensures no parallel write conflicts.)
       2. Write ONE LINE to .../rounds/NN/progress.md:
          [done] <subtask.id> verification: <pass|fail>

       Reply with EXACTLY ONE LINE:
         OK
       on success (all checks passed), or
         FAIL: <one sentence describing which check failed>
       on failure. No other output.
   ```

   **After all phases complete:**
   Run: `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" record-diff --run <run_id> --round N --baseline <baseline>`
   Run: `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" mark-worker-done --run <run_id> --round N`

6. **Check verification outcome before calling review-round.**
   Check the CURRENT ROUND's `rounds/NN/progress.md` for any `[done] <id> verification: fail` line (where NN is the current round number).

   - **Any verification FAIL found** → Do NOT call `review-round`. Read failure details from `shared/test-results.md` for context. Dispatch a fix worker (next round) by default. Escalate to user only for planning-level issues (not fixable by code changes).

   - **All verification PASS, or no verification subtask** → Call:
     `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" review-round --run <run_id> --round N`
     → JSON `{decision, current_phase, review_path, safety_flags, severity_counts, carry_forward, memo_appended, memo_path}`.
     Decision is one of APPROVE / NEEDS_CHANGES / PHASE_COMPLETE.
     `review-round` automatically parses the Codex review and appends the round memo to `memo.md`;
     do not call `append-memo` yourself.
7. Branch on `decision`:
   - `APPROVE` →
     1. If `commit_on_approve` is `true` (from `plan-round` step 1 JSON): `Bash: git add -A && git commit -m "<commit_message>"`. Show the commit hash to the user.
     2. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" finalize --run <run_id>`. Tell the user the run completed; point them at `final-report.md`. END.
   - `PHASE_COMPLETE` →
     1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase --run <run_id>`
        → JSON `{previous_phase, current_phase, updated_doc, is_last_phase}`.
     2. If `is_last_phase` is `true`: call finalize (step above). END.
     3. Announce: `Phase <previous_phase> complete -> advancing to Phase <current_phase>: "<title from phases.json>"`.
     4. Loop back to step 1 (next round in new phase).
   - `NEEDS_CHANGES` →
     **Step A — Automatic promote check** (treat as PHASE_COMPLETE if ALL hold):
     1. `safety_flags` is empty
     2. `severity_counts.high == 0`
     3. Every item in `carry_forward` contains only minor-signal words: "style", "nit", "minor", "optional", "cosmetic", "formatting"

     If all three hold → treat as PHASE_COMPLETE: call `advance-phase` (or `finalize` if last phase).

     **Step B — Supervisor judgment override** (when Step A does not apply):
     The supervisor may override the reviewer's NEEDS_CHANGES decision and proceed as PHASE_COMPLETE when a defensible rationale exists: the phase objective is fully met, the flagged items are not blockers for forward progress (e.g., dead code, doc nits, environment-specific test failures unrelated to logic), and tests pass.

     Before proceeding with a judgment override:
     1. APPEND to `shared/knowledge.md` under heading `## Supervisor override — Round N NEEDS_CHANGES → PHASE_COMPLETE (<date>)` a prose rationale covering: (a) why the phase objective is met, (b) each reviewer flag with its severity, (c) why each flag is not a blocker, (d) supporting evidence (test counts, clean state, etc.).
     2. Then call `advance-phase` (or `finalize` if last phase).

     **Step C — User escalation** (when supervisor cannot make a defensible decision):
     Escalate to the user — present continue / revise plan / abort choices — when EITHER:
     - `consecutive_needs_changes >= 3` (the loop is not converging and needs human direction), OR
     - The supervisor cannot construct a defensible rationale (e.g., `safety_flags` non-empty with plausible real risks, high-severity issues that may indicate a design problem, or reviewer flags whose validity the supervisor cannot assess).

     Otherwise (Steps A and B both inapplicable, Step C not triggered) → loop back to step 1 (next round).

## On continue (`/ClaudeXCodex:agent-loop` or `/ClaudeXCodex:agent-loop continue`)

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" continue` (optionally `--run <id>`)
   → JSON `{action, notes, options, run_id, current_round}`.
2. Interpret `action`:
   - `plan_round` → start a fresh round at step 1 of the round loop
   - `dispatch` → re-announce the round (step 3), run `mark-dispatched` (step 4), then dispatch the worker (step 5)
   - `advance_to_review` → worker result exists but review has not run; first check the current round's `rounds/NN/progress.md` for any `[done] <id> verification: fail` line — if found, treat as verification FAIL and dispatch a fix worker instead of calling review-round. Otherwise go to step 6 (`review-round`).
   - `write_review` → same as `advance_to_review`: first check the current round's `rounds/NN/progress.md` for any `[done] <id> verification: fail` line — if found, treat as verification FAIL and dispatch a fix worker instead of calling review-round. Otherwise run review-round (also re-composes memo if missing).
   - `write_memo` → review-round was interrupted before memo append. Re-run review-round; it will re-invoke Codex and re-append the memo idempotently.
   - `branch_decision` → review and memo are done; go straight to step 7 (decision branch)
   - `advance_phase` → phase transition pending. Call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase --run <run_id>`; if `is_last_phase` true, finalize; else loop back to round-loop step 1.
   - `finalize` → call finalize if the last completed round was approved
   - `user_confirm` → tell the user the options and wait

## Forbidden actions

- Never run `git push` or any destructive command yourself.
- `git commit` is allowed only in the APPROVE branch when `commit_on_approve` is `true`.
- Never read full diff/result/log files into your context. Use the `inspect` subcommand with narrow `--lines` only when the JSON status is insufficient. `--lines` accepts `N` (first N), `N-` (from N onward), or `A-B` (range).
- Never invent CLI behavior — if a subcommand's JSON doesn't match what you expected, stop and report to the user.

## File path conventions

- Run root: `<target_repo>/.agent-loop/runs/<run_id>/`
- Round dir: `<run_root>/rounds/NN/`
- Shared memory: `<run_root>/shared/`
