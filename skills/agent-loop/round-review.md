---
name: round-review
description: Review one Claude round. Produce decision + codex-review.md body using only the small payload + this round's claude-result.md + memo.md.
---

# round-review

## Inputs

- `review-payload.json` (in your context from `agent-loop dispatch`)
- `<run_dir>/rounds/NN/claude-result.md` (Read this file)
- `<run_dir>/memo.md` (Read this file)

## Decision criteria

Pick one of `APPROVE`, `NEEDS_CHANGES`, `STOP_FOR_USER`:

- **APPROVE** — goal fully satisfied per current task scope; tests pass; no safety flags; no critical risks.
- **STOP_FOR_USER** — any of: `safety_flags` non-empty; `result_summary.requires_user` true; same finding appeared in two consecutive memos; diff touches sensitive area not previously flagged; review uncovers ambiguity that needs human judgement.
- **NEEDS_CHANGES** — clear, actionable next step exists; goal not yet met.

## codex-review.md format (write to a file then pass via --review-file)

```text
# Codex Review — Round N

## Decision
APPROVE | NEEDS_CHANGES | STOP_FOR_USER

## Goal Alignment
<1-2 sentences: how close is this to the goal?>

## Findings
- [severity: high|med|low] <file:line if known> — <issue>
- ...

## Verification
- Tests: <pass/fail/missing> — <specifics>
- Coverage: <covered behaviors vs untested ones>

## Risks
- <any unaddressed risks worth recording>

## Carry-Forward For Next Round
- <bullet, ≤3 items, will be quoted verbatim in next prompt>

## Final Notes
<optional, can be empty>
```

## Sourcing claims

- If you cite a file:line, you must have seen it via `inspect`. Do NOT guess line numbers.
- If the diff seems suspicious but you don't want to spend tokens reading it, mark `[severity: med]` with note "needs diff inspection" instead of fabricating a finding.

## When to call `inspect`

- A specific changed file looks risky (e.g., touches auth, db, schema) → `agent-loop inspect --round N --file diff.patch --path <that_file>`
- Test outcome is `partial` or `fail` → `agent-loop inspect --round N --file test-log.txt --lines <last 80>`

Otherwise, do not call inspect. The payload + result.md + memo.md is the default working set.

## Length budget

codex-review.md may be as long as it needs to be (for human readers). Your contribution to memo (next sub-skill) is the compressed form.
