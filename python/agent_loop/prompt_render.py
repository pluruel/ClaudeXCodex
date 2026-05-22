"""Render the Claude worker prompt for one round."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReadingList:
    required: list[tuple[str, str]] = field(default_factory=list)
    suggested: list[tuple[str, str]] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


@dataclass
class RoundContext:
    round_n: int
    goal: str
    task: str
    carry_forward: str
    reading: ReadingList
    run_dir_rel: str
    shared_dir_rel: str
    round_dir_rel: str


def _fmt_pairs(items: list[tuple[str, str]]) -> str:
    if not items:
        return "(none for this round)"
    return "\n".join(f"- {path} — {note}" if note else f"- {path}"
                     for path, note in items)


def _fmt_list(items: list[str]) -> str:
    if not items:
        return "(none for this round)"
    return "\n".join(f"- {x}" for x in items)


def render_claude_prompt(ctx: RoundContext) -> str:
    return f"""# Round {ctx.round_n} — Claude Worker Prompt

## Carry-Forward From Previous Round
{ctx.carry_forward}

## Goal
{ctx.goal}

## Task (this round)
{ctx.task}

## Required Reading (read these first, in order)
{_fmt_pairs(ctx.reading.required)}

## Suggested Reading (only if needed)
{_fmt_pairs(ctx.reading.suggested)}

## Out of Scope (do not Read/Edit/Write)
{_fmt_list(ctx.reading.out_of_scope)}

## External References
{_fmt_list(ctx.reading.references)}

## Mandatory Outputs

1. **progress.md** — Append a line at every meaningful step to
   `{ctx.round_dir_rel}/progress.md`. Markers: `[done]` / `[doing]` / `[planned]`.
   Keep at most one `[doing]`.
2. **claude-result.md** — At the end, write
   `{ctx.round_dir_rel}/claude-result.md` following the schema below.
3. **shared/knowledge.md** — When you discover facts about the repo that
   outlast this round (file purpose, conventions, dependencies), append to
   `{ctx.shared_dir_rel}/knowledge.md`.
4. **shared/decisions.md** — When you choose between alternatives, log
   the decision and reason to `{ctx.shared_dir_rel}/decisions.md`.
5. **shared/open-questions.md** — Unanswered questions go here; later
   rounds may resolve them.

## Reading List Discipline (token frugality)

- Read Required items first. Read Suggested only if needed.
- DO NOT read Out of Scope.
- Avoid wide Glob/Grep across the whole repo. Operate inside the
  Reading List paths.
- If you truly need more, do NOT read it; record it in
  `claude-result.md` under "Requested Reading" so the controller can
  add it next round.

## Forbidden Actions

- git commit / push / merge / rebase / reset --hard
- rm -rf, sudo, destructive shell pipes
- DB migrations (alembic, prisma, knex…)
- Writes to sensitive paths (.env, secrets/, credentials.*, migrations/, …)

(These are also enforced by a PreToolUse hook; you will get a block
message if attempted.)

## claude-result.md schema

```
# Claude Result

## Summary
<1-3 sentences>

## Changed Files
- path1
- path2

## Commands Run
- cmd1
- cmd2

## Test Outcome
pass | fail | partial | not_run

## Decision Hint
completed | incomplete | blocked

## Open Questions
- ...

## Requested Reading
- ...

## Requires User
true | false
```
"""
