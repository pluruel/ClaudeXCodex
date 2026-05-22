from __future__ import annotations

import subprocess
from pathlib import Path

from agent_loop.diff_capture import (
    DiffStats,
    capture_baseline,
    capture_diff,
    compute_stats,
)


def test_capture_baseline_returns_commit_hash(tmp_repo: Path) -> None:
    sha = capture_baseline(tmp_repo)
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_capture_diff_after_change(tmp_repo: Path) -> None:
    baseline = capture_baseline(tmp_repo)
    (tmp_repo / "foo.py").write_text("print('hi')\n")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    patch = capture_diff(tmp_repo, baseline)
    assert "foo.py" in patch
    assert "+print('hi')" in patch


def test_compute_stats_counts_lines(tmp_repo: Path) -> None:
    baseline = capture_baseline(tmp_repo)
    (tmp_repo / "a.py").write_text("x = 1\ny = 2\nz = 3\n")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    patch = capture_diff(tmp_repo, baseline)
    stats = compute_stats(patch)
    assert stats.files_changed == 1
    assert stats.insertions == 3
    assert stats.deletions == 0
    assert stats.by_file[0]["path"] == "a.py"
    assert stats.by_file[0]["ins"] == 3
    assert stats.by_file[0]["del"] == 0


def test_compute_stats_marks_sensitive(tmp_repo: Path) -> None:
    baseline = capture_baseline(tmp_repo)
    (tmp_repo / ".env").write_text("SECRET=1\n")
    subprocess.run(["git", "add", "-f", ".env"], cwd=tmp_repo, check=True)
    patch = capture_diff(tmp_repo, baseline)
    stats = compute_stats(patch, sensitive_patterns=[r"\.env(\..+)?$"])
    assert stats.by_file[0]["sensitive"] is True
    assert stats.sensitive_hits == [".env"]
