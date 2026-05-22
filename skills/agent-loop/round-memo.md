---
name: round-memo
description: Format for the 5-10 line memo the supervisor appends after each round via the `append-memo` subcommand.
---

# round-memo

> CLI is invoked via Python — see SKILL.md "CLI invocation convention". `$AL` below stands for `python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py"`; expand it when actually running Bash.

After `$AL review-round` returns its decision, the supervisor writes a short memo and appends via `$AL append-memo --memo-file <tmp>`.

## Format (hard limits, total <= 10 lines)

```text
## Round N — <DECISION>
- Goal progress: <single line>
- Top risks: <up to 3 short bullets>
- Carry forward: <up to 3 short bullets, will be in next round's prompt>
- Sensitive: <"none" or one line>
- Diff size: <files=N, +X/-Y>
```

## Where to get the content

- Decision: from `$AL review-round` JSON (`decision` key).
- Goal progress / risks / carry forward: you may read `codex-review.md` for ONE quick pass if needed. Avoid re-reading it later — the memo is your compressed handoff.
- Diff size: from the review-round JSON (`safety_flags` mentions size flags; you can also get exact numbers from `$AL status` if needed).

## Rules

- <= 10 lines. <= 80 chars per bullet.
- "Carry forward" matters most: those bullets get quoted verbatim into the next prompt by `plan-round`.
- Do not quote findings verbatim — compress.

## Save destination

Write to a temp file (e.g., `<run_dir>/.tmp-memo.md`), then:

`Bash: python "${CLAUDE_PLUGIN_ROOT}/python/agent_loop/__main__.py" append-memo --run <run_id> --round N --memo-file <tmp_path>`

Delete the temp file after success.
