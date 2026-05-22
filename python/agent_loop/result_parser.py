"""Parse Claude's claude-result.md output into structured fields."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

TestOutcome = Literal["pass", "fail", "partial", "not_run"]
DecisionHint = Literal["completed", "incomplete", "blocked"]


@dataclass
class ClaudeResult:
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    test_outcome: TestOutcome = "not_run"
    decision_hint: DecisionHint = "incomplete"
    open_questions: list[str] = field(default_factory=list)
    requested_reading: list[str] = field(default_factory=list)
    requires_user: bool = False


_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _sections(text: str) -> dict[str, str]:
    """Split markdown into `{section_title: body_text}` blocks."""
    out: dict[str, str] = {}
    matches = list(_SECTION.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group(1).strip().lower()
        out[title] = text[start:end].strip()
    return out


def _bullets(body: str) -> list[str]:
    items: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("- "):
            items.append(s[2:].strip())
    return items


def _scalar(body: str) -> str:
    return body.strip().splitlines()[0].strip() if body.strip() else ""


def parse_result(path: Path) -> ClaudeResult:
    text = path.read_text()
    sec = _sections(text)
    r = ClaudeResult()
    if "summary" in sec:
        r.summary = sec["summary"].strip()
    if "changed files" in sec:
        r.changed_files = _bullets(sec["changed files"])
    if "commands run" in sec:
        r.commands_run = _bullets(sec["commands run"])
    if "test outcome" in sec:
        val = _scalar(sec["test outcome"]).lower()
        if val in ("pass", "fail", "partial", "not_run"):
            r.test_outcome = val  # type: ignore[assignment]
    if "decision hint" in sec:
        val = _scalar(sec["decision hint"]).lower()
        if val in ("completed", "incomplete", "blocked"):
            r.decision_hint = val  # type: ignore[assignment]
    if "open questions" in sec:
        r.open_questions = _bullets(sec["open questions"])
    if "requested reading" in sec:
        r.requested_reading = _bullets(sec["requested reading"])
    if "requires user" in sec:
        r.requires_user = _scalar(sec["requires user"]).lower() == "true"
    return r
