"""Git baseline capture, diff extraction, and stats computation."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def capture_baseline(repo: Path) -> str:
    """Return the current HEAD commit SHA."""
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


def capture_diff(repo: Path, baseline_sha: str) -> str:
    """Return unified diff from baseline to current working tree (incl. staged)."""
    r = subprocess.run(
        ["git", "diff", baseline_sha, "--", "."],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return r.stdout


@dataclass
class DiffStats:
    files_changed: int
    insertions: int
    deletions: int
    by_file: list[dict] = field(default_factory=list)
    sensitive_hits: list[str] = field(default_factory=list)


_FILE_HDR = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_HUNK = re.compile(r"^@@ ")


def compute_stats(patch: str, sensitive_patterns: list[str] | None = None) -> DiffStats:
    sensitive_patterns = sensitive_patterns or []
    compiled = [re.compile(p) for p in sensitive_patterns]

    by_file: list[dict] = []
    current: dict | None = None
    insertions = deletions = 0

    for line in patch.splitlines():
        m = _FILE_HDR.match(line)
        if m:
            if current:
                by_file.append(current)
            path = m.group(2)
            current = {"path": path, "ins": 0, "del": 0, "sensitive": False}
            continue
        if current is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            current["ins"] += 1
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            current["del"] += 1
            deletions += 1

    if current:
        by_file.append(current)

    sensitive_hits: list[str] = []
    for f in by_file:
        for pat in compiled:
            if pat.search(f["path"]):
                f["sensitive"] = True
                sensitive_hits.append(f["path"])
                break

    return DiffStats(
        files_changed=len(by_file),
        insertions=insertions,
        deletions=deletions,
        by_file=by_file,
        sensitive_hits=sensitive_hits,
    )
