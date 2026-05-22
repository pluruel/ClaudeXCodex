"""Read/append helpers for `.agent-loop/runs/<id>/shared/` files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_HEADERS = {
    "knowledge.md": "# Shared Knowledge\n\nAppend-only facts about the target repo.\n",
    "decisions.md": "# Decisions\n\nAppend-only design decisions across rounds.\n",
    "open-questions.md": "# Open Questions\n\nAppend-only questions; add resolutions inline.\n",
}


def _ensure(shared: Path, filename: str) -> Path:
    shared.mkdir(parents=True, exist_ok=True)
    p = shared / filename
    if not p.exists():
        p.write_text(_HEADERS[filename], encoding="utf-8")
    return p


def append_knowledge(shared: Path, fact: str) -> None:
    p = _ensure(shared, "knowledge.md")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"\n- {fact}\n")


def append_decision(shared: Path, decision: str, *, source: str) -> None:
    p = _ensure(shared, "decisions.md")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"\n- [{source}] {decision}\n")


def append_open_question(shared: Path, question: str) -> None:
    p = _ensure(shared, "open-questions.md")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"\n- {question}\n")


@dataclass
class SharedSnapshot:
    knowledge: int = 0
    decisions: int = 0
    open_questions: int = 0


def snapshot_sizes(shared: Path) -> SharedSnapshot:
    def _sz(name: str) -> int:
        p = shared / name
        return p.stat().st_size if p.exists() else 0

    return SharedSnapshot(
        knowledge=_sz("knowledge.md"),
        decisions=_sz("decisions.md"),
        open_questions=_sz("open-questions.md"),
    )


@dataclass
class SharedDelta:
    knowledge: str = ""
    decisions: str = ""
    open_questions: str = ""


def extract_delta(shared: Path, before: SharedSnapshot) -> SharedDelta:
    def _tail(name: str, prev: int) -> str:
        p = shared / name
        if not p.exists():
            return ""
        with p.open("rb") as f:
            f.seek(prev)
            return f.read().decode("utf-8", errors="replace")

    return SharedDelta(
        knowledge=_tail("knowledge.md", before.knowledge),
        decisions=_tail("decisions.md", before.decisions),
        open_questions=_tail("open-questions.md", before.open_questions),
    )
