from __future__ import annotations

from pathlib import Path

from agent_loop.shared_io import (
    SharedDelta,
    append_decision,
    append_knowledge,
    append_open_question,
    extract_delta,
    snapshot_sizes,
)


def test_append_creates_file(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    append_knowledge(shared, "auth uses session middleware in src/auth/session.py")
    body = (shared / "knowledge.md").read_text()
    assert "auth uses session middleware" in body
    assert body.startswith("# Shared Knowledge")


def test_append_decision_includes_marker(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    append_decision(shared, "Chose JWT over session", source="round-1")
    body = (shared / "decisions.md").read_text()
    assert "round-1" in body
    assert "Chose JWT over session" in body


def test_append_open_question(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    append_open_question(shared, "Should refresh tokens be persisted?")
    body = (shared / "open-questions.md").read_text()
    assert "Should refresh tokens" in body


def test_extract_delta_returns_new_content(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    append_knowledge(shared, "fact A")
    before = snapshot_sizes(shared)
    append_knowledge(shared, "fact B")
    append_decision(shared, "decision X", source="r2")
    delta = extract_delta(shared, before)
    assert isinstance(delta, SharedDelta)
    assert "fact B" in delta.knowledge
    assert "fact A" not in delta.knowledge
    assert "decision X" in delta.decisions
    assert delta.open_questions == ""


def test_extract_delta_empty_when_no_change(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    append_knowledge(shared, "x")
    snap = snapshot_sizes(shared)
    delta = extract_delta(shared, snap)
    assert delta.knowledge == ""
    assert delta.decisions == ""
    assert delta.open_questions == ""
