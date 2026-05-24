"""Tests for _load_current_phase_section: missing phases.json -> empty string, valid -> injected."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_loop.cli import _load_current_phase_section


def _make_phases_json(run_dir: Path, phases: list[dict]) -> None:
    """Write phases.json and individual phase doc files."""
    phases_dir = run_dir / "phases"
    phases_dir.mkdir(exist_ok=True)
    index = []
    for ph in phases:
        n = ph["phase_n"]
        doc_path = phases_dir / f"phase-{n:02d}.md"
        doc_path.write_text(ph["content"], encoding="utf-8")
        index.append({
            "phase_n": n,
            "title": ph["title"],
            "objective": ph.get("objective", ""),
            "doc_path": f"phases/phase-{n:02d}.md",
        })
    (run_dir / "phases.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def test_load_current_phase_section_missing_phases_json(tmp_path: Path) -> None:
    """Returns empty string when phases.json is absent (backward compat / legacy run)."""
    result = _load_current_phase_section(tmp_path, 1)
    assert result == ""


def test_load_current_phase_section_valid_returns_injected_content(tmp_path: Path) -> None:
    """Returns formatted section string when phases.json and phase doc both exist."""
    _make_phases_json(tmp_path, [
        {
            "phase_n": 1,
            "title": "Title1",
            "objective": "Objective 1",
            "content": "# Phase 1\n\nSome context.\n",
        }
    ])
    result = _load_current_phase_section(tmp_path, 1)
    assert "Current Phase" in result
    assert "Title1" in result
    assert "Phase 1" in result
    assert "Some context." in result


def test_load_current_phase_section_returns_correct_phase(tmp_path: Path) -> None:
    """Returns content matching the requested phase number, not first entry."""
    _make_phases_json(tmp_path, [
        {
            "phase_n": 1,
            "title": "Title1",
            "objective": "First phase",
            "content": "# Phase 1\n\nFirst phase content.\n",
        },
        {
            "phase_n": 2,
            "title": "Title2",
            "objective": "Second phase",
            "content": "# Phase 2\n\nSecond phase content.\n",
        },
    ])
    result = _load_current_phase_section(tmp_path, 2)
    assert "Title2" in result
    assert "Title1" not in result
    assert "Second phase content." in result


def test_load_current_phase_section_missing_doc_file_returns_empty(tmp_path: Path) -> None:
    """Returns empty string when phases.json exists but phase doc file is missing."""
    index = [{"phase_n": 1, "title": "T", "objective": "O", "doc_path": "phases/phase-01.md"}]
    (tmp_path / "phases.json").write_text(json.dumps(index) + "\n", encoding="utf-8")
    # Do NOT write the actual phase doc file.
    result = _load_current_phase_section(tmp_path, 1)
    assert result == ""


def test_load_current_phase_section_no_matching_phase_returns_empty(tmp_path: Path) -> None:
    """Returns empty string when phases.json has no entry for requested phase_n."""
    _make_phases_json(tmp_path, [
        {
            "phase_n": 1,
            "title": "Only Phase",
            "objective": "O",
            "content": "# Phase 1\n",
        }
    ])
    result = _load_current_phase_section(tmp_path, 99)
    assert result == ""


def test_load_current_phase_section_malformed_phases_json_returns_empty(tmp_path: Path) -> None:
    """Returns empty string when phases.json is not valid JSON."""
    (tmp_path / "phases.json").write_text("not json {{{", encoding="utf-8")
    result = _load_current_phase_section(tmp_path, 1)
    assert result == ""
