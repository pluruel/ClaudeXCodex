# claude-prompt-template

The literal template for the Round N worker prompt. The Python core (`prompt_render.py`) renders this; Codex does not write prompts from scratch — Codex provides the fields and they get substituted.

```text
# Round {round_n} — Claude Worker Prompt

## Carry-Forward From Previous Round
{carry_forward}

## Goal
{goal}

## Task (this round)
{task}

## Execution Plan
{concrete ordered steps, likely files, edits, and validation commands}

## Acceptance Criteria
{checkable bullets for this round}

## Required Reading (read these first, in order)
{required_reading}

## Suggested Reading (only if needed)
{suggested_reading}

## Out of Scope (do not Read/Edit/Write)
{out_of_scope}

## External References
{references}

## Mandatory Outputs
… (boilerplate, see prompt_render.py source)

## Reading List Discipline
…

## Forbidden Actions
…

## claude-result.md schema
…
```

The boilerplate sections are static and stable. Codex's job is to supply:
`round_n`, `goal`, `task`, `execution_plan`, `acceptance_criteria`,
`carry_forward`, and the reading lists. The worker is expected to execute the
plan with local judgment and record any justified deviation in
`claude-result.md`.
