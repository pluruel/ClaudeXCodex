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
    """SKILL.md must document implementation dispatch and verification subtasks."""
    text = (REPO_ROOT / "skills" / "agent-loop" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    # Subtask roles are documented
    assert "implementation" in text
    assert "verification" in text
    # Phase dispatch structure
    assert "depends_on" in text  # dependency-ordered implementation
    # Subtask fan-out heading is present
    assert "5b" in text or "Subtask fan-out" in text


def test_agent_loop_skill_plan_routing_order() -> None:
    """SKILL.md Decision rule must list --plan before goal to ensure correct routing order."""
    text = (REPO_ROOT / "skills" / "agent-loop" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    plan_idx = text.find("--plan ")
    goal_idx = text.find("goal", plan_idx) if plan_idx != -1 else -1
    assert plan_idx != -1 and goal_idx != -1, \
        "SKILL.md must contain '--plan ' followed by 'goal' in the Decision rule section"


def test_plan_skill_no_agent_loop_invocation() -> None:
    """skills/plan/SKILL.md must not contain unsupported Skill('ClaudeXCodex:agent-loop') calls."""
    text = (REPO_ROOT / "skills" / "plan" / "SKILL.md").read_text(encoding="utf-8")
    assert 'Skill("ClaudeXCodex:agent-loop"' not in text, \
        "skills/plan/SKILL.md must not invoke Skill('ClaudeXCodex:agent-loop')"


def test_agent_loop_skill_documents_progress_rendering() -> None:
    """SKILL.md must document that the supervisor calls 'agent-loop progress' at round/phase boundaries."""
    text = (REPO_ROOT / "skills" / "agent-loop" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    # The skill must mention invoking the progress subcommand
    assert "agent-loop progress" in text or "agent-loop\" progress" in text, \
        "SKILL.md must document 'agent-loop progress' invocation at round/phase boundaries"
    # The skill must document the --json flag for machine-readable output
    assert "--json" in text, \
        "SKILL.md must document --json flag for machine-readable status output"
    # The skill must document the --ascii flag for legacy terminals
    assert "--ascii" in text, \
        "SKILL.md must document --ascii flag for legacy terminal support"
