from __future__ import annotations

from pathlib import Path

from agent_loop.progress_parser import ProgressSnapshot, parse_progress
from agent_loop.progress_view import render_progress


def test_parse_empty(tmp_path: Path) -> None:
    p = tmp_path / "progress.md"
    p.write_text("")
    snap = parse_progress(p)
    assert snap.done_count == 0
    assert snap.doing is None
    assert snap.planned == []


def test_parse_mixed(tmp_path: Path) -> None:
    p = tmp_path / "progress.md"
    p.write_text(
        "- [done] 2026-05-22T10:15:03 — read src/auth/\n"
        "- [done] 2026-05-22T10:16:42 — append shared/knowledge.md\n"
        "- [doing] 2026-05-22T10:17:10 — write middleware.py\n"
        "- [planned] add tests\n"
        "- [planned] run pytest\n",
        encoding="utf-8",
    )
    snap = parse_progress(p)
    assert snap.done_count == 2
    assert snap.doing == "write middleware.py"
    assert snap.planned == ["add tests", "run pytest"]
    assert snap.last_done_ts == "2026-05-22T10:16:42"


def test_parse_done_only(tmp_path: Path) -> None:
    p = tmp_path / "progress.md"
    p.write_text(
        "- [done] 2026-05-22T10:00:00 — step 1\n"
        "- [done] 2026-05-22T10:05:00 — step 2\n",
        encoding="utf-8",
    )
    snap = parse_progress(p)
    assert snap.doing is None
    assert snap.done_count == 2


def test_parse_missing_file(tmp_path: Path) -> None:
    snap = parse_progress(tmp_path / "nope.md")
    assert snap.done_count == 0
    assert snap.doing is None


# ---------------------------------------------------------------------------
# render_progress tests
# ---------------------------------------------------------------------------

_SAMPLE_STATE = {
    "run_id": "2026-05-29-test-run",
    "status": "in_progress",
    "current_phase": 2,
    "total_phases": 3,
    "current_round": 4,
}

_SAMPLE_PHASES = [
    {"phase_n": 1, "title": "Setup"},
    {"phase_n": 2, "title": "Implementation"},
    {"phase_n": 3, "title": "Review"},
]

_SAMPLE_PROGRESS = ProgressSnapshot(
    done_count=3,
    doing="write tests",
    planned=["run pytest", "update docs"],
    last_done_ts="2026-05-29T10:00:00",
)


def test_render_unicode_contains_phase_titles() -> None:
    out = render_progress(_SAMPLE_STATE, _SAMPLE_PHASES, _SAMPLE_PROGRESS)
    assert "Setup" in out
    assert "Implementation" in out
    assert "Review" in out


def test_render_unicode_active_phase_glyph() -> None:
    out = render_progress(_SAMPLE_STATE, _SAMPLE_PHASES, _SAMPLE_PROGRESS)
    # active phase (phase 2) should use unicode active glyph
    assert "▶" in out
    # done phase (phase 1) should use unicode done glyph
    assert "✓" in out
    # pending phase (phase 3) should use unicode pending glyph
    assert "·" in out


def test_render_unicode_progress_info() -> None:
    out = render_progress(_SAMPLE_STATE, _SAMPLE_PHASES, _SAMPLE_PROGRESS)
    assert "done: 3" in out
    assert "write tests" in out
    assert "run pytest" in out
    assert "update docs" in out


def test_render_unicode_header() -> None:
    out = render_progress(_SAMPLE_STATE, _SAMPLE_PHASES, _SAMPLE_PROGRESS)
    assert "2026-05-29-test-run" in out
    assert "in_progress" in out
    assert "2/3" in out


def test_render_ascii_mode_contains_phase_titles() -> None:
    out = render_progress(_SAMPLE_STATE, _SAMPLE_PHASES, _SAMPLE_PROGRESS, ascii=True)
    assert "Setup" in out
    assert "Implementation" in out
    assert "Review" in out


def test_render_ascii_mode_uses_ascii_glyphs() -> None:
    out = render_progress(_SAMPLE_STATE, _SAMPLE_PHASES, _SAMPLE_PROGRESS, ascii=True)
    assert "[>]" in out   # active phase
    assert "[x]" in out   # done phase
    assert "[ ]" in out   # pending phase


def test_render_ascii_mode_no_box_drawing_chars() -> None:
    out = render_progress(_SAMPLE_STATE, _SAMPLE_PHASES, _SAMPLE_PROGRESS, ascii=True)
    box_drawing_chars = ["✓", "▶", "·", "├", "└", "─"]
    for ch in box_drawing_chars:
        assert ch not in out, f"ASCII mode should not contain box-drawing char {ch!r}"


def test_render_tolerates_empty_state() -> None:
    snap = ProgressSnapshot()
    out = render_progress({}, [], snap)
    assert "unknown" in out


def test_render_tolerates_empty_phases() -> None:
    snap = ProgressSnapshot(done_count=1)
    out = render_progress(_SAMPLE_STATE, [], snap)
    assert "2026-05-29-test-run" in out
    assert "done: 1" in out


def test_render_tolerates_no_progress() -> None:
    snap = ProgressSnapshot()
    out = render_progress(_SAMPLE_STATE, _SAMPLE_PHASES, snap)
    assert "no progress recorded" in out


def test_render_completed_run_marks_all_done() -> None:
    state = {**_SAMPLE_STATE, "status": "completed", "current_phase": 3}
    snap = ProgressSnapshot(done_count=5)
    out = render_progress(state, _SAMPLE_PHASES, snap)
    # All phases should be marked done, no active glyph
    assert "▶" not in out
    # All three done markers should appear (one per phase)
    assert out.count("✓") == 3
