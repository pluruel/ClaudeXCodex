---
name: plan-from-goal
description: Round 1 prompt generation — turn the user goal into a small task plan and the first Claude prompt with a curated Reading List.
---

# plan-from-goal

Invoked on the first round of a new run.

## Inputs (load via Read or Bash before this skill takes over)

- `<run_dir>/goal.md` — the user's goal
- `<run_dir>/shared/knowledge.md` — only if the run inherited prior knowledge
- `Bash: agent-loop scout --goal "<goal>" --keywords <k1> <k2> ...` → scout JSON

Pick 3–6 keywords from the goal. Avoid stopwords. Include language/library hints if obvious.

## Output (two artifacts you must Write)

### 1. `<run_dir>/plan.md`

Format:

```text
# Plan

## Tasks
1. [ ] <small testable task>
2. [ ] <small testable task>
3. [ ] ...

## Notes
<2-4 sentences about strategy / risks>
```

Rules:
- Each task should be doable in one Claude round (≈30 minutes of work)
- Order by dependency
- Aim for 3–7 tasks. If more, the goal is too large — write fewer at the cost of granularity.

### 2. Round 1 prompt body

Use `references/claude-prompt-template.md` as the template. Fill in:

- **Carry-Forward**: "(none — first round)"
- **Goal**: goal.md content
- **Task**: the first item from plan.md
- **Required Reading**: 1–4 files from scout.grep_hits that are most relevant to Task 1, plus `shared/knowledge.md` if non-empty. Each line: `- path — short reason`.
- **Suggested Reading**: 1–3 supporting items (tests dir, related modules)
- **Out of Scope**: 1–4 unrelated top-level dirs from scout.file_tree
- **External References**: leave empty unless the goal explicitly mentions a library

Save the prompt to a temp path and then call `agent-loop init-round`.

## Curation principles (token discipline both sides)

- Codex side: you build the Reading List from scout JSON only — do NOT Read target repo files yourself.
- Claude side: a tight Reading List means Claude doesn't roam. Required ≤ 4. Suggested ≤ 3. Out of Scope wide enough to cover obvious distractor dirs.

## Anti-patterns

- Do not include every file in `scout.grep_hits` — pick top 3–4 most relevant
- Do not put test files in Required unless this round writes tests
- Do not list `node_modules`, `.venv`, `dist`, build outputs as Out of Scope — those are filtered by `git ls-files` anyway
