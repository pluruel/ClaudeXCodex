# review-payload-schema

The JSON that `agent-loop dispatch` writes to `<round_dir>/review-payload.json` and that Codex consumes in `round-review`.

```json
{
  "round": 2,
  "goal_summary": "Add JWT auth middleware with token expiry handling",
  "claude_decision_hint": "completed",
  "result_summary": {
    "changed_files": ["src/auth/middleware.py"],
    "commands_run": ["pytest tests/auth -x"],
    "test_outcome": "pass",
    "claude_notes": "JWT verify added",
    "open_questions": ["refresh token?"],
    "requested_reading": ["src/sessions/store.py"],
    "requires_user": false
  },
  "diff_summary": {
    "files_changed": 1,
    "insertions": 62,
    "deletions": 4,
    "by_file": [{"path": "src/auth/middleware.py", "ins": 62, "del": 4, "sensitive": false}],
    "sensitive_hits": []
  },
  "safety_flags": [],
  "artifact_paths": {
    "result": ".agent-loop/runs/<id>/rounds/02/claude-result.md",
    "diff": ".agent-loop/runs/<id>/rounds/02/diff.patch",
    "test_log": ".agent-loop/runs/<id>/rounds/02/test-log.txt",
    "messages": ".agent-loop/runs/<id>/rounds/02/claude-messages.jsonl"
  },
  "shared_delta": {
    "knowledge": "- new fact appended this round\n",
    "decisions": "",
    "open_questions": ""
  }
}
```

Target size: < 2KB.

`shared_delta` contains *only* the bytes appended to each shared file during this round, not the full file content.
