"""Extract lightweight target-repo signals (file tree, keyword grep, headers).

Output is small JSON for Codex consumption — Codex never reads target repo
files directly.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScoutReport:
    file_tree: list[str] = field(default_factory=list)
    grep_hits: list[dict] = field(default_factory=list)
    headers: list[dict] = field(default_factory=list)


def _git_ls_files(repo: Path) -> list[str]:
    r = subprocess.run(
        ["git", "ls-files"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ln for ln in r.stdout.splitlines() if ln]


def _grep(repo: Path, keyword: str, max_per_kw: int = 20) -> list[dict]:
    try:
        r = subprocess.run(
            ["git", "grep", "-n", "-I", "--", keyword],
            cwd=repo,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    out: list[dict] = []
    for line in r.stdout.splitlines()[:max_per_kw]:
        # format: path:line:content
        parts = line.split(":", 2)
        if len(parts) == 3:
            out.append({"path": parts[0], "line": int(parts[1]), "snippet": parts[2][:160]})
    return out


_HEADER_PATTERNS = {
    ".py": re.compile(r"^(?:def|class)\s+\w+"),
    ".ts": re.compile(r"^(?:export\s+)?(?:function|class|interface|type)\s+\w+"),
    ".js": re.compile(r"^(?:export\s+)?(?:function|class)\s+\w+"),
    ".md": re.compile(r"^#+\s+"),
}


def _headers(repo: Path, paths: list[str], max_files: int = 10) -> list[dict]:
    out: list[dict] = []
    for p in paths[:max_files]:
        suffix = Path(p).suffix
        pat = _HEADER_PATTERNS.get(suffix)
        if pat is None:
            continue
        try:
            text = (repo / p).read_text(errors="replace")
        except OSError:
            continue
        first = [
            ln.strip()[:120]
            for ln in text.splitlines()[:200]
            if pat.search(ln)
        ][:8]
        if first:
            out.append({"path": p, "headers": first})
    return out


def scout(
    repo: Path,
    *,
    goal: str,
    keywords: list[str],
    max_files: int = 200,
) -> ScoutReport:
    files = _git_ls_files(repo)[:max_files]
    hits: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for kw in keywords:
        for h in _grep(repo, kw):
            key = (h["path"], h["line"])
            if key in seen:
                continue
            seen.add(key)
            hits.append(h)
    hit_paths = list({h["path"] for h in hits})
    headers = _headers(repo, hit_paths)
    return ScoutReport(file_tree=files, grep_hits=hits, headers=headers)
