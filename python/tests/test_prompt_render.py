from __future__ import annotations

from agent_loop.prompt_render import ReadingList, RoundContext, render_claude_prompt
from agent_loop.cli import _render_subtasks_block, _inject_subtasks_section


def test_render_includes_all_sections() -> None:
    ctx = RoundContext(
        round_n=1,
        goal="Add JWT auth middleware",
        task="Create src/auth/middleware.py with verify + expiry",
        carry_forward="(none — first round)",
        reading=ReadingList(
            required=[("src/auth/session.py", "existing middleware pattern")],
            suggested=[("tests/auth/", "test patterns")],
            out_of_scope=["src/billing/", "src/admin/"],
            references=["pyjwt docs"],
        ),
        run_dir_rel=".agent-loop/runs/r1",
        shared_dir_rel=".agent-loop/runs/r1/shared",
        round_dir_rel=".agent-loop/runs/r1/rounds/01",
    )
    out = render_claude_prompt(ctx)
    assert "Add JWT auth middleware" in out
    assert "Create src/auth/middleware.py" in out
    assert "src/auth/session.py" in out
    assert "Out of Scope" in out
    assert "progress.md" in out
    assert "shared/knowledge.md" in out


def test_render_handles_empty_reading_sections() -> None:
    ctx = RoundContext(
        round_n=2,
        goal="g",
        task="t",
        carry_forward="cf",
        reading=ReadingList(required=[], suggested=[], out_of_scope=[], references=[]),
        run_dir_rel="r",
        shared_dir_rel="s",
        round_dir_rel="d",
    )
    out = render_claude_prompt(ctx)
    assert "Required Reading" in out
    assert "(none for this round)" in out


def test_render_carry_forward_at_top() -> None:
    ctx = RoundContext(
        round_n=3,
        goal="g",
        task="t",
        carry_forward="Focus on JWT verify + error tests",
        reading=ReadingList(required=[], suggested=[], out_of_scope=[], references=[]),
        run_dir_rel="r",
        shared_dir_rel="s",
        round_dir_rel="d",
    )
    out = render_claude_prompt(ctx)
    cf_idx = out.find("Focus on JWT verify")
    task_idx = out.find("Task")
    assert cf_idx != -1 and cf_idx < task_idx


# --- subtask rendering helpers (from cli.py, injected as post-processing) ---

_SAMPLE_SUBTASKS = [
    {
        "id": "r1-a1",
        "role": "analysis",
        "model": "haiku",
        "description": "Map CLI entry points",
        "deliverable": "Append findings to shared/knowledge.md",
        "reasoning_effort": "low",
        "required_reading": [],
        "out_of_scope": [],
        "depends_on": [],
    },
    {
        "id": "r1-i1",
        "role": "implementation",
        "model": "sonnet",
        "description": "Add subtask block injection to plan-round",
        "deliverable": "Pass tests for subtask normalization",
        "reasoning_effort": "medium",
        "required_reading": [],
        "out_of_scope": [],
        "depends_on": ["r1-a1"],
    },
]


def test_render_subtasks_block_contains_all_columns() -> None:
    block = _render_subtasks_block(_SAMPLE_SUBTASKS)
    assert "### Subtasks (this round)" in block
    assert "r1-a1" in block
    assert "r1-i1" in block
    assert "analysis" in block
    assert "implementation" in block
    assert "haiku" in block
    assert "sonnet" in block
    # Table header columns
    assert "| id |" in block
    assert "role" in block
    assert "model" in block
    assert "effort" in block
    # C1a: scope column must NOT appear
    assert "scope" not in block
    # Per-row effort values must appear
    assert "medium" in block


def test_render_subtasks_block_empty_returns_empty_string() -> None:
    assert _render_subtasks_block([]) == ""


def test_inject_subtasks_section_after_task_before_required_reading() -> None:
    prompt = (
        "## Goal\nDo something\n\n"
        "## Task (this round)\nImplement subtasks\n\n"
        "## Required Reading\n- cli.py\n"
    )
    result = _inject_subtasks_section(prompt, _SAMPLE_SUBTASKS)
    assert "### Subtasks (this round)" in result
    task_idx = result.find("## Task")
    subtasks_idx = result.find("### Subtasks")
    reading_idx = result.find("## Required Reading")
    assert task_idx < subtasks_idx < reading_idx


def test_inject_subtasks_section_no_subtasks_unchanged() -> None:
    prompt = "## Goal\ng\n\n## Task (this round)\nt\n\n## Required Reading\n- f\n"
    result = _inject_subtasks_section(prompt, [])
    assert result == prompt
    assert "### Subtasks" not in result


def test_inject_subtasks_section_idempotent() -> None:
    prompt = (
        "## Goal\ng\n\n"
        "## Task (this round)\nt\n\n"
        "## Required Reading\n- f\n"
    )
    result1 = _inject_subtasks_section(prompt, _SAMPLE_SUBTASKS)
    result2 = _inject_subtasks_section(result1, _SAMPLE_SUBTASKS)
    # Should not duplicate the block
    assert result1.count("### Subtasks (this round)") == 1
    assert result2.count("### Subtasks (this round)") == 1
