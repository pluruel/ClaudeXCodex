from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_agent_loop_skill_has_no_mojibake_markers() -> None:
    text = (REPO_ROOT / "skills" / "agent-loop" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "??" not in text
    assert "→ JSON" in text
    assert "— Claude Supervisor Skill" in text
