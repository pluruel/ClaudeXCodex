---
name: shared-knowledge
description: Read-and-append discipline for the shared/ memory area, used by Codex when it needs project-wide context.
---

# shared-knowledge (Codex side)

The `shared/` directory is the project-wide memory. Claude appends to it during dispatch. Codex reads from it during planning and writes to it sparingly during review.

## Files

- `knowledge.md` — repo facts (file purpose, conventions, dependencies). Append-only.
- `decisions.md` — design decisions across rounds. Append-only.
- `open-questions.md` — unresolved questions; resolutions can be appended later.

## When Codex reads shared/

- `plan-from-goal` may read `shared/knowledge.md` if it's non-empty (subsequent runs in same repo).
- `plan-from-review` reads `shared_delta` from payload (Claude's last-round additions). Reading the full file is rarely necessary; use `agent-loop inspect` only if you need older entries.
- `round-review` may consult `shared/decisions.md` to check consistency.

## When Codex writes shared/

Rare. Mostly Claude does it. Codex should write only:

- A `decisions.md` entry when *Codex itself* makes a strategic choice (e.g., "Codex chose to stop and request user input because …"). Tag with `[codex-round-N]`.
- An `open-questions.md` entry when review uncovers something neither Claude's result nor existing knowledge answers.

To append from Codex, use `Edit` or `Write` directly on the file with the file's existing content + new bullet. Do NOT overwrite existing content.

## Append format

- `knowledge.md`: `- <fact in one line>`
- `decisions.md`: `- [<source>] <decision> (<one-line reason>)`
- `open-questions.md`: `- <question>` (resolutions: indent below as `  - Resolved (round N): <answer>`)

## Token discipline

- Do not Read whole shared/ files in every round. Trust `shared_delta` in the payload.
- For older context, use `agent-loop inspect --run <id> --round 1 --file ../../shared/knowledge.md --lines a-b` (note: inspect rooted at round dir, so use `../../shared/...`).
