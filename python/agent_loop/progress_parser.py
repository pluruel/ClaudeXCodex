"""Parse rounds/NN/progress.md to estimate where Claude got."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ProgressSnapshot:
    done_count: int = 0
    doing: Optional[str] = None
    planned: list[str] = field(default_factory=list)
    last_done_ts: Optional[str] = None


_LINE = re.compile(
    r"^-\s+\[(done|doing|planned)\]\s*"
    r"(?P<ts>\S+)?\s*(?:—\s*)?(?P<body>.+)$"
)


def parse_progress(path: Path) -> ProgressSnapshot:
    snap = ProgressSnapshot()
    if not path.exists():
        return snap
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        marker = m.group(1)
        ts = m.group("ts")
        body = m.group("body").strip()
        if marker == "done":
            snap.done_count += 1
            if ts and re.match(r"^\d{4}-\d{2}-\d{2}T", ts):
                snap.last_done_ts = ts
        elif marker == "doing":
            snap.doing = body
        elif marker == "planned":
            text = f"{ts} {body}".strip() if ts and not re.match(r"^\d{4}", ts) else body
            snap.planned.append(text)
    return snap
