from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_loop", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_init_run_creates_layout(tmp_repo: Path) -> None:
    r = _run(["init-run", "--goal", "add auth", "--slug", "add-auth"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    run_dir = tmp_repo / ".agent-loop" / "runs" / js["run_id"]
    assert (run_dir / "goal.md").read_text().strip() == "add auth"
    assert (run_dir / "state.json").exists()
    assert (run_dir / "shared").is_dir()
    assert (run_dir / "rounds").is_dir()


def test_init_run_uses_unique_id_for_same_slug(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "first", "--slug", "same"], cwd=tmp_repo)
    r2 = _run(["init-run", "--goal", "second", "--slug", "same"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    first = json.loads(r1.stdout)["run_id"]
    second = json.loads(r2.stdout)["run_id"]
    assert second == f"{first}-2"
    runs = tmp_repo / ".agent-loop" / "runs"
    assert (runs / first / "goal.md").read_text().strip() == "first"
    assert (runs / second / "goal.md").read_text().strip() == "second"


def test_init_round_renders_prompt(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    prompt = tmp_repo / "prompt.md"
    prompt.write_text("PROMPT BODY")
    r2 = _run(
        ["init-round", "--run", run_id, "--prompt-file", str(prompt)],
        cwd=tmp_repo,
    )
    assert r2.returncode == 0, r2.stderr
    js = json.loads(r2.stdout)
    assert js["round_n"] == 1
    rounds_01 = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    assert (rounds_01 / "claude-prompt.md").read_text() == "PROMPT BODY"


def test_mark_dispatched_sets_phase(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    prompt = tmp_repo / "prompt.md"
    prompt.write_text("PROMPT BODY")
    _run(["init-round", "--run", run_id, "--prompt-file", str(prompt)], cwd=tmp_repo)
    r2 = _run(["mark-dispatched", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r2.returncode == 0, r2.stderr
    state_path = tmp_repo / ".agent-loop" / "runs" / run_id / "state.json"
    state = json.loads(state_path.read_text())
    assert state["rounds"][0]["phase"] == "dispatched"


def test_scout_emits_json(tmp_repo: Path) -> None:
    (tmp_repo / "src").mkdir()
    (tmp_repo / "src" / "auth.py").write_text("def jwt_login(): pass\n")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add"], cwd=tmp_repo, check=True)
    r = _run(["scout", "--goal", "jwt", "--keywords", "jwt"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert any("src/auth.py" in f for f in js["file_tree"])
    assert any(h["path"] == "src/auth.py" for h in js["grep_hits"])


def test_status_shows_state(tmp_repo: Path) -> None:
    _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    r = _run(["status"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["state"]["status"] == "in_progress"


def test_finalize_writes_report_and_completes(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    r2 = _run(["finalize", "--run", run_id], cwd=tmp_repo)
    assert r2.returncode == 0, r2.stderr
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    assert (run_dir / "final-report.md").exists()
    state = json.loads((run_dir / "state.json").read_text())
    assert state["status"] == "completed"


def test_abort_marks_run(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    r2 = _run(["abort", "--run", run_id], cwd=tmp_repo)
    assert r2.returncode == 0
    state_path = tmp_repo / ".agent-loop" / "runs" / run_id / "state.json"
    state = json.loads(state_path.read_text())
    assert state["status"] == "aborted"


def test_inspect_lines_slice(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    rdir = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rdir.mkdir(parents=True)
    (rdir / "diff.patch").write_text("\n".join(f"line {i}" for i in range(1, 20)))
    r2 = _run(
        ["inspect", "--run", run_id, "--round", "1",
         "--file", "diff.patch", "--lines", "5-7"],
        cwd=tmp_repo,
    )
    assert r2.returncode == 0
    assert r2.stdout.strip().splitlines() == ["line 5", "line 6", "line 7"]


def test_inspect_refuses_paths_outside_run_dir(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    rdir = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rdir.mkdir(parents=True)
    r2 = _run(
        ["inspect", "--run", run_id, "--round", "1",
         "--file", "../../../../README.md"],
        cwd=tmp_repo,
    )
    assert r2.returncode == 1
    assert "outside run directory" in r2.stdout


def _seed_inspect_file(tmp_repo: Path, n: int = 100) -> str:
    """Create a 1..n-line diff.patch under round 01 and return the run_id."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    rdir = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rdir.mkdir(parents=True)
    (rdir / "diff.patch").write_text(
        "\n".join(f"line {i}" for i in range(1, n + 1)),
        encoding="utf-8",
    )
    return run_id


def test_inspect_lines_first_n(tmp_repo: Path) -> None:
    """``--lines 80`` returns the first 80 lines without crashing.

    Round 1's implementation split on ``-`` and unpacked the result into
    ``a, b``; a single int crashed with ``ValueError: not enough values to
    unpack``. The fix interprets ``N`` as ``(1, N)``.
    """
    run_id = _seed_inspect_file(tmp_repo, n=100)
    r = _run(
        ["inspect", "--run", run_id, "--round", "1",
         "--file", "diff.patch", "--lines", "80"],
        cwd=tmp_repo,
    )
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "line 1"
    assert lines[-1] == "line 80"
    assert len(lines) == 80


def test_inspect_lines_from_n_onward(tmp_repo: Path) -> None:
    """``--lines 50-`` (open right bound) reads from line N through EOF."""
    run_id = _seed_inspect_file(tmp_repo, n=100)
    r = _run(
        ["inspect", "--run", run_id, "--round", "1",
         "--file", "diff.patch", "--lines", "50-"],
        cwd=tmp_repo,
    )
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "line 50"
    assert lines[-1] == "line 100"
    assert len(lines) == 51


def test_inspect_lines_range(tmp_repo: Path) -> None:
    """``--lines 10-30`` continues to behave as an inclusive range."""
    run_id = _seed_inspect_file(tmp_repo, n=100)
    r = _run(
        ["inspect", "--run", run_id, "--round", "1",
         "--file", "diff.patch", "--lines", "10-30"],
        cwd=tmp_repo,
    )
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "line 10"
    assert lines[-1] == "line 30"
    assert len(lines) == 21


def test_inspect_lines_invalid_spec_reports_clear_error(tmp_repo: Path) -> None:
    """Malformed ``--lines`` exits non-zero with an error JSON, not a crash."""
    run_id = _seed_inspect_file(tmp_repo, n=20)
    r = _run(
        ["inspect", "--run", run_id, "--round", "1",
         "--file", "diff.patch", "--lines", "abc"],
        cwd=tmp_repo,
    )
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    assert "--lines" in r.stdout
