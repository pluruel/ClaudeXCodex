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
   - Otherwise, copy the file to `.agent-loop-plan-draft.md` (if it isn't already there),
     then tell the user "Draft loaded from `<path>`. Open `.agent-loop-plan-draft.md`
     in your editor and tell me what to change." Ask one focused question about the most
     uncertain part.

2. If a plain goal text was given:
   - Draft an initial plan in this format:

     ```markdown
     # Plan: <short title>

     ## Goal
     <one paragraph restating the goal in concrete terms>

     ## Architecture
     <2-3 sentences: how the pieces fit together at a high level>

     ## Non-goals
     - <what this plan explicitly does NOT do>

     ## Phases
     1. **<Phase name>** -- <one sentence objective>
     2. ...

     ## Open Questions
     - <anything you're uncertain about>
     ```

   - **Write the draft to a file** (do NOT print the full plan in chat):

     ```bash
     cat > .agent-loop-plan-draft.md << 'EOF'
     <draft plan content -- no authorized frontmatter yet>
     EOF
     ```

   - Tell the user: "Draft saved to `.agent-loop-plan-draft.md`. Open it in your editor and tell me what to change."
   - Ask one focused question about the most uncertain part of the plan.
   - **Do not print the plan body in chat** -- the file is the source of truth from this point on.

## Conversation rules

- **Never pressure the user to decide.** If they want to explore an idea, explore it.
- **Never use AskUserQuestion with forced choices** for plan content -- free text is fine.
- Ask one open question at a time. Don't list five follow-ups.
- **All plan revisions go to the file, not the chat.** When the user requests a change,
  update `.agent-loop-plan-draft.md` with the Edit tool, then confirm in one sentence what changed.
  Never reprint the full plan in chat.
- When the user seems to be converging ("looks good", "let's go", "this is fine"),
  ask: "Ready to authorize and start execution?"
- Keep refining until the user says yes.
- **Always include a Non-goals section** when drafting or revising a plan. Bounding scope
  prevents Codex from over-reaching during execution. Even a one-item list is enough.

## On user confirmation

1. Run the self-review checklist (see **Plan quality rules** below) against the current
   `.agent-loop-plan-draft.md`. Fix any unchecked items before proceeding.

2. Expand the draft into the final plan format, adding required sections that may be
   missing (Tech Stack, Interface Contracts, Example Scenarios, per-phase Testing).
   Compose the full plan markdown:

   ```markdown
   ---
   authorized: CLAUDE_X_CODEX_PLAN
   ---

   # Plan: <title>

   ## Goal
   <confirmed goal -- one concrete sentence>

   ## Architecture
   <2-3 sentences: high-level design, key components and how they interact>

   ## Non-goals
   - <what this plan explicitly does NOT do>
   - <scope boundary that prevents over-reaching>

   ## Tech Stack
   <!-- Required for non-trivial plans only. -->
   - <language/runtime + version>
   - <relevant libraries or frameworks>

   ## Interface Contracts
   <!-- Required for non-trivial plans. Lock public APIs before phases begin. -->
   - `FunctionName(param: Type) -> ReturnType` -- one-line purpose
   - Key type names and property shapes referenced across phases

   ## Phases
   1. **<Phase name>** -- <objective>
      - Target files: `path/to/file.py`, `path/to/other.ts`
      - Before/after: <intent-level description of the change>
      - Testing:
        - What to test: <what behavior or output to verify>
        - How to verify: `<command>` -- expected output / observable effect
      - Acceptance criteria:
        - [ ] <checkable condition>
        - [ ] <checkable condition>
   2. ...
   <!-- Simple phases may use the one-liner form: `1. **Name** -- objective`.
        A one-liner phase implicitly uses "objective achieved" as its criterion
        and is exempt from the expanded acceptance-criteria requirement. -->

   ## Example Scenarios
   <!-- Required for non-trivial plans. Concrete before/after or usage examples. -->
   **Before:** <current behavior or state>
   **After:** <expected behavior or state>

   ## Notes
   <any constraints, risks, or context worth preserving>

   ## Review Checklist
   - [ ] Every phase has a concrete, checkable acceptance criterion (or uses the one-liner exemption)
   - [ ] If the plan is non-trivial, Tech Stack lists actual version numbers or "latest stable" explicitly
   - [ ] If the plan is non-trivial, Interface contracts name actual identifiers (no vague "the function that does Y")
   - [ ] Non-goals section excludes at least one tempting scope expansion
   - [ ] No placeholder language remains (TBD, TODO, etc.)
   - [ ] If the plan is non-trivial, Example Scenarios contains at least one concrete before/after example
   - [ ] Phase Testing sub-sections specify a runnable command or observable result
   ```

   **Required sections** (always): Goal, Architecture, Phases, Non-goals, Review Checklist.

   **Required when the plan is non-trivial** (more than one phase, or phases touch
   multiple files or public APIs): Tech Stack, Interface Contracts, Example Scenarios,
   and detailed Testing sub-sections in each phase.

   **Per-phase Testing sub-section**: Required whenever a phase has acceptance criteria.
   Specify *what* to test (the behavior) and *how to verify it* (a runnable command or
   observable result). Do not import TDD micro-step sequences into the plan -- Codex
   plan-round drives implementation steps; the plan defines the acceptance bar only.

   **Plan documents must be written in English.** Codex interprets English instructions
   more accurately than mixed-language plans, and technical identifiers (file paths,
   function names) are already in English.

3. Write the authorized plan to `.agent-loop-plan.md` (use the Write tool, which replaces
   `.agent-loop-plan-draft.md` as the execution artifact):

   ```
   Write tool → .agent-loop-plan.md
   Content: the full plan markdown from step 2, with authorized: CLAUDE_X_CODEX_PLAN in the frontmatter
   ```

   Tell the user: "Plan authorized and saved to `.agent-loop-plan.md`."

4. Run `init-run` with `--plan-file`:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" init-run \
     --goal "<one-line goal>" \
     --slug "<short-slug>" \
     --plan-file .agent-loop-plan.md
   ```

   -> JSON `{run_id, run_dir}`. Remember `run_id`.

5. Run `plan-init` (phases generation only -- plan.md already exists):

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" plan-init --run <run_id>
   ```

   Expected output: `"plan_source": "pre-existing"` in the JSON.

6. Tell the user: "Plan confirmed. Phases generated. Starting execution..."

7. After plan-init succeeds, proceed directly into the agent-loop round loop (you are already the supervisor for this run). Follow the **Round loop** section of the `skills/agent-loop/SKILL.md` skill -- starting at step 1 (plan-round) -- using the `run_id` obtained in step 4.

## Plan quality rules

Apply these rules when composing the final plan (step 1 above) and during any
mid-conversation draft revision.

### No Placeholders

The following vague terms are **forbidden** in any plan section:

> TBD, TODO, to be determined, implement as needed, similar approach, etc.,
> and so on, various, appropriate, relevant, something like, placeholder

If you are tempted to write one of these, ask the user a clarifying question instead.

### Self-review checklist

Before writing the authorized plan to disk (step 3 of **On user confirmation**), confirm each item:

- [ ] Every phase has a concrete, checkable acceptance criterion (not just "implement X"),
      or uses the one-liner form (which uses "objective achieved" as its implicit criterion).
- [ ] If the plan is non-trivial, Tech Stack lists actual version numbers or "latest stable"
      explicitly, not just library names.
- [ ] If the plan is non-trivial, Interface contracts name actual identifiers (function names,
      type names, file paths) -- no vague "the function that does Y" language.
- [ ] Non-goals section exists and explicitly excludes at least one tempting scope expansion.
- [ ] No placeholder language (see list above) remains in any section.
- [ ] If the plan is non-trivial, Example Scenarios section contains at least one concrete
      before/after or input/output example.
- [ ] Phase Testing sub-sections specify a runnable command or observable result, not just
      "verify it works".

If any item is unchecked, revise the plan before proceeding to step 2.

## Forbidden

- Do not insert `authorized: CLAUDE_X_CODEX_PLAN` before the user confirms.
- Do not run `plan-round` or dispatch workers **before the user confirms**. After confirmation, you continue as supervisor and follow the agent-loop round loop directly.
- Do not commit, push, or delete files.
- **Do not edit any source files, configs, or skills while a planning conversation is in progress.** Keep all changes (even small ones discussed during planning) staged until the user explicitly confirms the plan. "Looks good" or "the proposal is nice" is interest, not a confirmation.
- **Do not invoke superpowers:writing-plans, superpowers:brainstorming, or any other external planning skill while this skill is active.** /ClaudeXCodex:plan is itself the planning process; routing to a superpowers skill creates a nested conflict where structured docs get generated outside the conversation flow.
