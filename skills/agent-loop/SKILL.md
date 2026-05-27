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
durable files (`claude-prompt.md`, `phases/phase-NN-review.md`, `phases/phase-NN-diff.patch`,
plus the run-level state/memo/report files) and removes
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
Note: phase-review is called after phase commit (step 9), not per-round.

### Subtask roles and dispatch rules

When `subtasks` is present and valid, the round is decomposed into typed subtasks:

| role | authority | parallelism | constraint |
|---|---|---|---|
| `implementation` | patch source files, tests, configs | dispatched sequentially in depends_on order | must NOT write to `shared/*` as scratch; only `decisions.md`, `knowledge.md`, `open-questions.md` |
| `verification` | run named test commands, lint commands, and `git status`/`git diff --stat`; report pass/fail | dispatched after all implementation subtasks in this round complete | must name an explicit command in its deliverable |

Each subtask carries:
- `id` — unique within the round
- `role` — `implementation | verification`
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

- You never read full diffs, test logs, claude-prompt.md, or phase review files. Not even "one quick pass." The memo is auto-composed by `phase-review`; do not call `memo-note` redundantly after `phase-review`.
- You only ingest the small JSON each CLI subcommand emits.
- For details, you can run the CLI's `inspect` subcommand with narrow `--lines` to extract a slice — but only when JSON is genuinely insufficient (rare). `--lines` accepts `N` (first N), `N-` (from N onward), or `A-B` (range). Example: `agent-loop inspect --run <id> --round N --file codex-review.md --lines 80`.
- You never call `codex exec` or `codex` directly — always via the CLI's `plan-init|plan-round|phase-review|memo-note` subcommands.

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
4b. Read `<run_dir>/plan.md` into context. This is an allowed exception to the lean-context rule — plan.md is small and gives the supervisor routing context for verification failure judgment throughout the run.
5. Enter the normal round loop.

## On start (`/ClaudeXCodex:agent-loop <goal text>`)

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" init-run --goal "<goal>" --slug "<short-slug>"`
   → JSON `{run_id, run_dir}`. Remember `run_id`.
2. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" plan-init --run <run_id>`
   → JSON `{plan_path, phases, summary}`. (Codex drafted plan.md and phase docs on disk.)
2b. Read `<run_dir>/plan.md` into context. This is an allowed exception to the lean-context rule — plan.md is small and gives the supervisor routing context for verification failure judgment throughout the run.
3. Enter round loop (next section).

## Round loop (repeat until phase-review APPROVE / run complete)

For each round N (starting at 1):

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" plan-round --run <run_id>`
   → JSON `{round_n, current_phase, total_phases, prompt_path, round_plan_path, worker_model, worker_model_reason, reasoning_effort, phase_complete_signal, subtasks, summary}`. (Codex drafted the worker prompt and selected the worker model; the CLI normalized the selection and injected a `## Worker Model` section into the prompt.)
2. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" capture-baseline`
   → JSON `{baseline}`. Save the sha.
3. **Announce the round to the user** (one line, verbatim format, BEFORE dispatch):

   ```
   Phase <current_phase>/<total_phases> · Round N — worker (dominant): <worker_model> (<worker_model_reason>), effort: <reasoning_effort> — subtasks: <count> (implementation×<i>, verification×<v>)
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
   - **r2-i1** → `sonnet` *(medium)* — apply source fixes for phase 2
   - **r2-i2** → `sonnet` *(medium)* — add test coverage for edge cases
   - **r2-v1** → `haiku` *(low)* — run pytest
   ```

   Emit bullets as a contiguous list before the corresponding Task calls. The bullets are plain user-facing markdown —
   not tool calls, not stored in any file — emitted purely so the user can
   see at a glance which model is handling which slice as the transcript
   scrolls.

   **Phase 1 — Implementation (sequential, depends_on order):**
   Collect all subtasks with `role: implementation`. Dispatch implementation subtasks
   one at a time in depends_on order. When plan-round emits multiple implementation
   subtasks, they MUST be chained sequentially (each depends_on the previous).
   Dispatch the next only after the current returns OK. Per-subtask prompt:

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

   Wait for ALL implementation Task tool calls to return before Phase 2.

   **Phase 2 — Verification:**
   Collect all subtasks with `role: verification`. Each verification subtask must
   name explicit commands in its `deliverable`. Per-subtask prompt:

   ```
   Task tool (general-purpose):
     description: "Round N / <subtask_id> (verification) for <run_id>"
     model: <subtask.model>   # drop if host rejects per-call model
     prompt: |
       You are subtask <subtask.id> (role=verification, model=<subtask.model>,
       reasoning_effort=<subtask.reasoning_effort>)
       inside agent-loop run <run_id>, round N.

       Strict role rules:
       - You are a VERIFICATION subtask. You MUST NOT edit source files. Run ONLY
         the commands specified in your deliverable: test commands, lint commands
         (e.g. eslint, ruff, mypy, tsc --noEmit), and `git status`/`git diff --stat`.
         Do NOT run grep, file searches, or read arbitrary source files. Report
         pass/fail and captured output.
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

6. **Check verification outcome.**
   Check the CURRENT ROUND's `rounds/NN/progress.md` for any `[done] <id> verification: fail` line.

   - **Any verification FAIL found** → Do NOT proceed to phase judgment. Read failure summary from `shared/test-results.md` (first 30 lines). Dispatch a fix worker (next round). Loop back to step 1.

   - **All verification PASS (or no verification subtask)** → proceed to step 7.

7. **Supervisor phase-complete judgment.**

   Declare phase complete when BOTH hold:
   - All verification subtasks PASS (step 6 above).
   - `phase_complete_signal: true` in the round plan, OR all `acceptance_criteria` from the round plan (emitted in the `plan-round` JSON) are satisfied per test results in `shared/test-results.md`.

   If a hard round cap is needed: after 8 consecutive rounds in a phase without declaring completion, escalate to the user.

   - **Phase NOT complete** → loop back to step 1 (next round).
   - **Phase complete** → proceed to step 8.

8. **Phase commit.**

   ```bash
   git add -- . ":(exclude).agent-loop"
   git commit -m "phase <current_phase>: <phase title from phases.json>"
   ```

   Show the commit hash to the user.

9. **Phase review.**

   `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" phase-review --run <run_id> --phase <current_phase>`
   → JSON `{decision, phase, review_path, severity_counts, carry_forward, consecutive_needs_changes}`.

10. **Branch on phase-review decision:**

    - **`APPROVE`** →
      `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase --run <run_id>`
      → JSON `{previous_phase, current_phase, is_last_phase}`.
      - If `is_last_phase: true`: call `finalize`. END.
      - Else: announce phase advance and loop back to step 1 for the new phase.

    - **`NEEDS_CHANGES`** →
      **Auto-promote check** (treat as APPROVE if ALL hold):
      1. `severity_counts.high == 0`
      2. Every item in `carry_forward` contains only minor-signal words: "style", "nit", "minor", "optional", "cosmetic", "formatting"

      If all hold → treat as APPROVE (step above).

      **Supervisor judgment override**: may treat as APPROVE when: phase objective is met, flagged items are not blockers, tests pass. Before overriding, append rationale to `shared/knowledge.md` under `## Supervisor override — Phase <N> NEEDS_CHANGES → APPROVE (<date>)`.

      **User escalation** when either:
      - `consecutive_needs_changes >= 3`, OR
      - Supervisor cannot construct a defensible rationale.

      Otherwise: dispatch fix round(s). After implementation + verification pass:
      ```bash
      git add -- . ":(exclude).agent-loop"
      git commit -m "phase <current_phase>: fix <one-line summary>"
      ```
      Re-run `phase-review`. Repeat from step 9.

## On continue (`/ClaudeXCodex:agent-loop` or `/ClaudeXCodex:agent-loop continue`)

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" continue` (optionally `--run <id>`)
   → JSON `{action, notes, options, run_id, current_round}`.
2. Interpret `action`:
   - `plan_round` → start a fresh round at step 1 of the round loop
   - `dispatch` → re-announce the round (step 3), run `mark-dispatched` (step 4), then dispatch the worker (step 5)
   - `advance_to_review` → worker result exists but phase judgment has not run; check the current round's `rounds/NN/progress.md` for any `[done] <id> verification: fail` line — if found, treat as verification FAIL and dispatch a fix worker instead. Otherwise → proceed to supervisor phase-complete judgment (step 7).
   - `write_review` → same as `advance_to_review`: check verification, then supervisor judgment.
   - `write_memo` → phase-review was interrupted before memo append. Re-run `phase-review`; it will re-invoke Codex and re-append the memo idempotently.
   - `phase_review_pending` → a phase commit was made but `phase-review` has not run yet.
     Check that `git log --oneline -1` shows a phase commit. Then:
     `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" phase-review --run <run_id> --phase <current_phase>`
     Branch on decision (step 10 of round loop).
   - `skip_review` → verification passed; proceed to supervisor phase-complete judgment (step 7).
   - `branch_decision` → phase-review is done; go straight to step 10 (decision branch).
   - `advance_phase` → phase transition pending. Call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase --run <run_id>`; if `is_last_phase` true, finalize; else loop back to round-loop step 1.
   - `finalize` → call finalize if the last completed phase was approved
   - `user_confirm` → tell the user the options and wait

## Forbidden actions

- Never run `git push` or any destructive command yourself.
- `git commit` is allowed only in step 8 (phase commit) and step 10 (fix round re-commit).
- Never read full diff/result/log files into your context. Use the `inspect` subcommand with narrow `--lines` only when the JSON status is insufficient. `--lines` accepts `N` (first N), `N-` (from N onward), or `A-B` (range).
- Never invent CLI behavior — if a subcommand's JSON doesn't match what you expected, stop and report to the user.

## File path conventions

- Run root: `<target_repo>/.agent-loop/runs/<run_id>/`
- Round dir: `<run_root>/rounds/NN/`
- Shared memory: `<run_root>/shared/`
