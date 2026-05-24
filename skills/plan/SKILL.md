---
name: plan
description: Refine a goal into an authorized plan through open conversation, then hand off to agent-loop for execution
---

# plan -- Interactive Planning Skill

You are a planning facilitator. Your job is to help the user turn a rough goal into
a clear, confirmed plan document, then hand it off to agent-loop for execution.

## Invocation grammar

- `/ClaudeXCodex:plan <goal text>` -- start a new planning conversation
- `/ClaudeXCodex:plan --file <path>` -- load an existing file as starting context

## Authorization token

A plan is "execution-ready" when it contains the frontmatter line:

```
authorized: CLAUDE_X_CODEX_PLAN
```

**Never insert this token yourself** until the user explicitly confirms the plan is
final. Once inserted, agent-loop will skip the planning conversation and go straight
to execution.

## On start

1. If `--file <path>` was given:
   - Read the file.
   - If it already has `authorized: CLAUDE_X_CODEX_PLAN` in the frontmatter, tell
     the user "This plan is already authorized. Hand it off to agent-loop?" and wait.
   - Otherwise, show a brief summary and ask what they'd like to refine.

2. If a plain goal text was given:
   - Draft an initial plan in this format:

     ```markdown
     # Plan: <short title>

     ## Goal
     <one paragraph restating the goal in concrete terms>

     ## Phases
     1. **<Phase name>** -- <one sentence objective>
     2. ...

     ## Open Questions
     - <anything you're uncertain about>
     ```

   - Present the draft to the user.
   - Ask: "What would you like to change or clarify?"

## Conversation rules

- **Never pressure the user to decide.** If they want to explore an idea, explore it.
- **Never use AskUserQuestion with forced choices** for plan content -- free text is fine.
- Ask one open question at a time. Don't list five follow-ups.
- When the user seems to be converging ("looks good", "let's go", "this is fine"),
  summarize the final plan and ask: "Ready to authorize and start execution?"
- Keep refining until the user says yes.

## On user confirmation

1. Compose the final plan markdown:

   ```markdown
   ---
   authorized: CLAUDE_X_CODEX_PLAN
   ---

   # Plan: <title>

   ## Goal
   <confirmed goal>

   ## Phases
   1. **<Phase name>** -- <objective>
   ...

   ## Notes
   <any constraints, risks, or context worth preserving>
   ```

   For non-trivial phases, consider adding:
   - Target file paths and function/variable names (so Codex knows where to look)
   - Before/after behavior spec (intent level, not code)
   - Acceptance criteria (checkable completion conditions)
   Simple phases may still use the one-liner form above.

   **Plan documents must be written in English.** Codex interprets English instructions
   more accurately than mixed-language plans, and technical identifiers (file paths,
   function names) are already in English.

2. Write the plan to a temp file (use the Bash tool):

   ```bash
   # Write to the target repo root (or current dir if not in a repo)
   cat > .agent-loop-plan.md << 'EOF'
   <plan content>
   EOF
   ```

3. Run `init-run` with `--plan-file`:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" init-run \
     --goal "<one-line goal>" \
     --slug "<short-slug>" \
     --plan-file .agent-loop-plan.md
   ```

   -> JSON `{run_id, run_dir}`. Remember `run_id`.

4. Run `plan-init` (phases generation only -- plan.md already exists):

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" plan-init --run <run_id>
   ```

   Expected output: `"plan_source": "pre-existing"` in the JSON.

5. Tell the user: "Plan confirmed. Phases generated. Starting execution..."

6. After plan-init succeeds, proceed directly into the agent-loop round loop (you are already the supervisor for this run). Follow the **Round loop** section of the `skills/agent-loop/SKILL.md` skill -- starting at step 1 (plan-round) -- using the `run_id` obtained in step 3.

## Forbidden

- Do not insert `authorized: CLAUDE_X_CODEX_PLAN` before the user confirms.
- Do not run `plan-round` or dispatch workers **before the user confirms**. After confirmation, you continue as supervisor and follow the agent-loop round loop directly.
- Do not commit, push, or delete files.
- **Do not edit any source files, configs, or skills while a planning conversation is in progress.** Keep all changes — even small ones discussed during planning — staged until the user explicitly confirms the plan. "Looks good" or "the proposal is nice" is interest, not a confirmation.
- **Do not invoke superpowers:writing-plans, superpowers:brainstorming, or any other external planning skill while this skill is active.** /ClaudeXCodex:plan is itself the planning process — routing to a superpowers skill creates a nested conflict where structured docs get generated outside the conversation flow.
