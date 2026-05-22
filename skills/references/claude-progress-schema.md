# claude-progress-schema

What Claude appends to `<round_dir>/progress.md` during execution.

```text
- [done] 2026-05-22T10:15:03 — read src/auth/
- [done] 2026-05-22T10:16:42 — appended shared/knowledge.md
- [doing] 2026-05-22T10:17:10 — writing middleware.py
- [planned] add tests
- [planned] run pytest
```

Rules enforced by the worker system_prompt:

- One marker per line: `[done]` / `[doing]` / `[planned]`
- Optional ISO-8601 timestamp after the marker (recommended for `[done]`/`[doing]`)
- Free-text description after `—`
- At most one `[doing]` at any time (transition by promoting it to `[done]` and appending a new `[doing]`)

Parsed by `progress_parser.py` for resume decisions. Not consumed by Codex during normal flow.
