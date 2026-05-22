from __future__ import annotations

from pathlib import Path

from agent_loop.result_parser import ClaudeResult, parse_result


SAMPLE = """# Claude Result

## Summary
JWT verify 추가, expiry 케이스 테스트 1건.

## Changed Files
- src/auth/middleware.py
- tests/auth/test_middleware.py

## Commands Run
- pytest tests/auth -x
- ruff check src/auth

## Test Outcome
pass

## Decision Hint
completed

## Open Questions
- refresh token 처리는 다음 라운드?

## Requested Reading
- src/sessions/store.py
- tests/conftest.py

## Requires User
false
"""


def test_parse_complete_result(tmp_path: Path) -> None:
    p = tmp_path / "claude-result.md"
    p.write_text(SAMPLE)
    r = parse_result(p)
    assert isinstance(r, ClaudeResult)
    assert r.summary.startswith("JWT verify")
    assert r.changed_files == ["src/auth/middleware.py", "tests/auth/test_middleware.py"]
    assert r.commands_run == ["pytest tests/auth -x", "ruff check src/auth"]
    assert r.test_outcome == "pass"
    assert r.decision_hint == "completed"
    assert r.open_questions == ["refresh token 처리는 다음 라운드?"]
    assert r.requested_reading == ["src/sessions/store.py", "tests/conftest.py"]
    assert r.requires_user is False


def test_parse_missing_sections_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "claude-result.md"
    p.write_text("# Claude Result\n\n## Summary\nminimal.\n")
    r = parse_result(p)
    assert r.summary == "minimal."
    assert r.changed_files == []
    assert r.test_outcome == "not_run"
    assert r.decision_hint == "incomplete"
    assert r.requires_user is False


def test_parse_requires_user_true(tmp_path: Path) -> None:
    p = tmp_path / "claude-result.md"
    p.write_text(SAMPLE.replace("Requires User\nfalse", "Requires User\ntrue"))
    r = parse_result(p)
    assert r.requires_user is True
