---
name: round-memo
description: Write the 5–10 line compressed memo for this round, appended to memo.md.
---

# round-memo

Invoked after `write-review`. The output is appended to `<run_dir>/memo.md` by `agent-loop append-memo`.

## Format (hard limits)

```text
## Round N — <DECISION>
- Goal progress: <single line, what % done in spirit>
- Top risks: <≤3 bullets, very short>
- Carry forward: <≤3 bullets, will be quoted in next prompt verbatim>
- Sensitive: <"none" or 1 line describing what tripped>
- Diff size: <files=N, +X/-Y>
```

## Rules

- Total ≤ 10 lines including heading and bullets
- Each bullet ≤ 80 chars
- "Carry forward" is the *only* connection between rounds in the worker prompt — make every word count
- Do NOT quote findings verbatim from `codex-review.md` — compress them

## Why this matters

`memo.md` is the *only* full-history artifact you re-read in later rounds (besides shared/). Its compression is what makes Approach B (Codex in-session loop) token-flat across rounds. If you let memo bloat, the whole token discipline collapses.

## Quality gate

Before writing the memo, ask: if I had to plan round N+1 from this memo alone (no review, no result.md), would I know what to do? If yes, the memo is sufficient. If no, tighten the Carry forward bullets.

## Save destination

Write to a temp file (e.g., `<run_dir>/.tmp-memo.md`) then:

`Bash: agent-loop append-memo --run <run_id> --round N --memo-file <tmp_path>`

Delete the temp file after success.
