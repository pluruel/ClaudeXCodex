# shared-knowledge-schema

Format of files under `<run_dir>/shared/`.

## `knowledge.md`

```text
# Shared Knowledge

Append-only facts about the target repo.

- src/auth/session.py is the existing session middleware
- pyproject pins pyjwt==2.8.0
- test discovery uses pytest from .venv/bin
```

## `decisions.md`

```text
# Decisions

Append-only design decisions across rounds.

- [round-1] Chose JWT over server-side session (reason: stateless deploy)
- [codex-round-2] Stopped for user input on schema migration (reason: legal review needed)
```

The bracketed `[source]` tag is mandatory.

## `open-questions.md`

```text
# Open Questions

Append-only questions; add resolutions inline.

- Should refresh tokens be persisted?
  - Resolved (round 3): yes, store in `auth_refresh` table
- Does the rate limiter apply to internal callers?
```

Resolutions are indented two-space bullets nested under the question they answer.
