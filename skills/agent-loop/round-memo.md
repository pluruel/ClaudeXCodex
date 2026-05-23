---
name: round-memo
description: Schema reference for the per-round memo that `review-round` auto-appends to memo.md. Supervisor does NOT compose this manually.
---

# round-memo

> The supervisor does not write memos. `review-round` parses Codex's review markdown and appends the memo block automatically. This document exists so you understand what's being written on your behalf, not as a workflow you execute.

## Auto-memo flow

`review-round` does, in order:

1. Invokes Codex to produce `codex-review.md`.
2. Parses these sections from that file:
   - `## Goal Alignment` → `Goal progress` line
   - `## Risks` bullets (up to 3) → `Top risks`
   - `## Carry-Forward For Next Round` bullets (up to 3) → `Carry forward`
3. Derives `Sensitive` from `safety_flags` (yes if `diff_has_sensitive`, else none).
4. Derives `Diff size` from the in-memory diff stats (`files=N, +X/-Y`). In debug mode those stats are also written to `diff-stats.json`.
5. Composes the block below and appends to `<run_dir>/memo.md` idempotently (skips append if a `## Round N -` heading for the same round is already present).
6. Advances state to `memo_written` → `completed`.

The next round's `plan-round` reads `memo.md` and folds the latest `Carry forward` bullets into the new claude-prompt verbatim.

## Schema (auto-written; for your reference)

```text
## Round N - <DECISION>
- Goal progress: <single line>
- Top risks: <up to 3 items, joined by "; ">
- Carry forward: <up to 3 items, joined by "; ">
- Sensitive: <"none" or "yes -- diff touched sensitive paths">
- Diff size: <files=N, +X/-Y>
```

## When NOT to call `append-memo` manually

Never, in the normal flow. `append-memo` remains in the CLI for manual override (e.g., editing a memo for an old run by hand), but the supervisor's SKILL.md does not invoke it.

## Crash recovery

If `review-round` was interrupted after writing `codex-review.md` but before the memo append, re-run `review-round` for the same round. It will re-invoke Codex, but the idempotent append guarantees memo.md does not get duplicated.
