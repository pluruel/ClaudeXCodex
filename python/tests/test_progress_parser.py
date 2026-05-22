from __future__ import annotations

from pathlib import Path

from agent_loop.progress_parser import ProgressSnapshot, parse_progress


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
        "- [planned] run pytest\n"
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
        "- [done] 2026-05-22T10:05:00 — step 2\n"
    )
    snap = parse_progress(p)
    assert snap.doing is None
    assert snap.done_count == 2


def test_parse_missing_file(tmp_path: Path) -> None:
    snap = parse_progress(tmp_path / "nope.md")
    assert snap.done_count == 0
    assert snap.doing is None
