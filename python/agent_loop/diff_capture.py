"""Git baseline capture, diff extraction, and stats computation."""
from __future__ import annotations

import difflib
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
    """Return unified diff from baseline to current working tree.

    `git diff <baseline>` includes tracked working tree and staged changes, but
    it does not include untracked files. Workers are not required to stage files,
    so append synthetic "new file" patches for untracked text files.
    """
    r = subprocess.run(
        ["git", "diff", baseline_sha, "--", "."],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked_diff = r.stdout

    u = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    untracked_paths = [
        p.decode("utf-8", errors="replace")
        for p in u.stdout.split(b"\0")
        if p and not p.replace(b"\\", b"/").startswith(b".agent-loop/")
    ]
    untracked_diff = "".join(
        _diff_untracked_text_file(repo, path) for path in untracked_paths
    )
    if tracked_diff and untracked_diff:
        return tracked_diff.rstrip("\n") + "\n" + untracked_diff
    return tracked_diff + untracked_diff


def _diff_untracked_text_file(repo: Path, rel_path: str) -> str:
    path = repo / rel_path
    if not path.is_file():
        return ""
    data = path.read_bytes()
    if b"\0" in data:
        return (
            f"diff --git a/{rel_path} b/{rel_path}\n"
            "new file mode 100644\n"
            "index 0000000..0000000\n"
            "--- /dev/null\n"
            f"+++ b/{rel_path}\n"
            f"Binary files /dev/null and b/{rel_path} differ\n"
        )
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    if text and not text.endswith(("\n", "\r")):
        lines[-1] = lines[-1] + "\n"
    body = "".join(
        difflib.unified_diff(
            [],
            lines,
            fromfile="/dev/null",
            tofile=f"b/{rel_path}",
        )
    )
    if body and not body.endswith("\n"):
        body += "\n"
    return (
        f"diff --git a/{rel_path} b/{rel_path}\n"
        "new file mode 100644\n"
        "index 0000000..0000000\n"
        f"{body}"
    )


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
