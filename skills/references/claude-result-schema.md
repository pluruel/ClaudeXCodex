# claude-result-schema

What Claude writes at `<round_dir>/claude-result.md`. The Python `result_parser` consumes this format.

```text
# Claude Result

## Summary
<1-3 sentences>

## Changed Files
- path1
- path2

## Commands Run
- cmd1

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

Section order does not matter for parsing, but Claude is instructed to use this order. Missing sections default to empty values. The parser is forgiving — extra text outside sections is ignored.
