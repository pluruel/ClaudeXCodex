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


def test_agent_loop_skill_describes_subtask_dispatch() -> None:
    """SKILL.md must document parallel analysis dispatch, dependency-aware
    implementation dispatch, verification subtasks, and the single-worker
    fallback path."""
    text = (REPO_ROOT / "skills" / "agent-loop" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    # Subtask roles are documented
    assert "analysis" in text
    assert "implementation" in text
    assert "verification" in text
    # Phase dispatch structure
    assert "Phase 1" in text or "5b" in text  # parallel analysis phase
    assert "Phase 2" in text or "depends_on" in text  # dependency-ordered implementation
    assert "Phase 3" in text  # verification phase
    # Single-worker fallback must be explicitly called out
    assert "fallback" in text.lower()
    # Subtask fan-out heading is present
    assert "5b" in text or "Subtask fan-out" in text
