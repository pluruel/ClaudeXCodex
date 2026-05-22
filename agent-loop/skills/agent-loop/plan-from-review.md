---
name: plan-from-review
description: Round N+1 prompt generation — given prior review + remaining plan + shared, produce the next Claude prompt.
---

# plan-from-review

Invoked when the prior round returned NEEDS_CHANGES.

## Inputs already in your context

- `review-payload.json` (this round just processed)
- `memo.md` (accumulated)
- This round's `codex-review.md` and `claude-result.md`
- `plan.md` (the original task list)
- `shared_delta` (from the payload)

## Optional fresh signal

If the next task targets an area you have no signal for:

`Bash: agent-loop scout --goal "<remaining task>" --keywords <k1> <k2> ...` → JSON

Use sparingly — only when carry-forward + plan don't tell you where to look.

## Output

The next Claude prompt body, using `references/claude-prompt-template.md`.

- **Carry-Forward**: the "Carry forward" lines from the most recent round-memo, verbatim, plus any blockers identified in review.
- **Goal**: same as before (from goal.md).
- **Task**: either the next item in plan.md OR a corrective task spelled out by the review. If correcting, mark "(correction for round N-1 findings)" at the top of the Task body.
- **Required Reading**: items from `review-payload.json.result_summary.requested_reading` (Claude asked for these), plus 1–3 items from the prior round's changed_files if relevant, plus `shared/knowledge.md`/`shared/decisions.md` lines as needed.
- **Suggested Reading**: 0–3 items.
- **Out of Scope**: same shape as before; carry over distractor dirs.
- **External References**: only if review revealed a doc/library needed.

Save to a temp path then `agent-loop init-round` to dispatch it as Round N+1.

## Special cases

- If the review's primary finding is "tests missing", the Task should be specifically to add tests; Required Reading must include the file being tested + an existing similar test as template.
- If `safety_flags` includes `diff_too_many_lines`, do not generate another round — Codex should have already returned STOP_FOR_USER. (Defense in depth: refuse to plan a next round if last payload had any safety_flag.)
- If the same finding has appeared in two consecutive round memos, recommend STOP_FOR_USER in the prior step rather than re-planning.

## Token discipline

- Read only what you must from disk this turn. The payload + memo + result.md are usually sufficient.
- Avoid re-Reading prior `codex-review.md` for older rounds — memo.md compresses them.
