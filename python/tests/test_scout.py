from __future__ import annotations

import subprocess
from pathlib import Path

from agent_loop.scout import ScoutReport, scout


def _seed(repo: Path) -> None:
    (repo / "src").mkdir()
    (repo / "src" / "auth.py").write_text(
        "def login(token):\n    return verify_jwt(token)\n"
    )
    (repo / "src" / "billing.py").write_text("def charge(): pass\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_auth.py").write_text(
        "def test_login(): assert True\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)


def test_scout_file_tree_listed(tmp_repo: Path) -> None:
    _seed(tmp_repo)
    rep = scout(tmp_repo, goal="add JWT auth", keywords=["jwt", "auth"])
    assert isinstance(rep, ScoutReport)
    assert "src/auth.py" in rep.file_tree
    assert "src/billing.py" in rep.file_tree


def test_scout_grep_hits_filtered_by_keywords(tmp_repo: Path) -> None:
    _seed(tmp_repo)
    rep = scout(tmp_repo, goal="add JWT auth", keywords=["jwt"])
    hit_paths = {h["path"] for h in rep.grep_hits}
    assert "src/auth.py" in hit_paths
    assert "src/billing.py" not in hit_paths


def test_scout_caps_results(tmp_repo: Path) -> None:
    for i in range(50):
        (tmp_repo / f"f{i}.py").write_text(f"x = {i}\n")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "many"], cwd=tmp_repo, check=True)
    rep = scout(tmp_repo, goal="x", keywords=["x"], max_files=20)
    assert len(rep.file_tree) <= 20
