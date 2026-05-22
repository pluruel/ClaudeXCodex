from __future__ import annotations

from agent_loop.prompt_render import ReadingList, RoundContext, render_claude_prompt


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
