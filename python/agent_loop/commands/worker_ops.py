"""Worker hook command handlers: record-diff, capture-baseline, mark-worker-done,
mark-dispatched, append-memo, write-review, memo-note."""
from __future__ import annotations

import datetime as _dt
import json as _json
import re as _re
import sys
from pathlib import Path as _Path

from agent_loop.registry import register
from agent_loop.run_state import RunState


def _run_dir(repo: _Path, run_id: str) -> _Path:
    return repo / ".agent-loop" / "runs" / run_id


def _emit(obj) -> None:
    print(_json.dumps(obj, indent=2))


def _append_memo_idempotent(memo_path: _Path, round_n: int, block: str) -> bool:
    """Append memo block unless this round already appears in memo.md.

    Returns True if appended, False if skipped (already present).
    """
    existing = memo_path.read_text(encoding="utf-8") if memo_path.exists() else ""
    if _re.search(rf"^##\s+Round\s+{round_n}\s+-\s+",
                  existing, _re.MULTILINE):
        return False
    with memo_path.open("a", encoding="utf-8") as f:
        f.write("\n" + block.strip() + "\n")
    return True


@register("record-diff")
def _cmd_record_diff(args) -> int:
    from agent_loop.diff_capture import capture_diff
    repo = _Path(args.repo).resolve()
    rd = _run_dir(repo, args.run) / "rounds" / f"{args.round:02d}"
    rd.mkdir(parents=True, exist_ok=True)
    diff = capture_diff(repo, args.baseline)
    (rd / "diff.patch").write_text(diff, encoding="utf-8")
    _emit({"diff_path": str(rd / "diff.patch"), "size_bytes": len(diff)})
    return 0


@register("capture-baseline")
def _cmd_capture_baseline(args) -> int:
    from agent_loop.diff_capture import capture_baseline
    repo = _Path(args.repo).resolve()
    sha = capture_baseline(repo)
    _emit({"baseline": sha})
    return 0


@register("mark-worker-done")
def _cmd_mark_worker_done(args) -> int:
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    rs.set_round_phase(args.round, "claude_completed")
    rs.save(run_dir / "state.json")
    _emit({"round": args.round, "phase": "claude_completed"})
    return 0


@register("mark-dispatched")
def _cmd_mark_dispatched(args) -> int:
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    rs.set_round_phase(args.round, "dispatched")
    rs.save(run_dir / "state.json")
    _emit({"round": args.round, "phase": "dispatched"})
    return 0


@register("write-review")
def _cmd_write_review(args) -> int:
    repo = _Path(args.repo).resolve()
    rd = _run_dir(repo, args.run) / "rounds" / f"{args.round:02d}"
    body = _Path(args.review_file).read_text(encoding="utf-8")
    (rd / "codex-review.md").write_text(body, encoding="utf-8")
    rs = RunState.load(_run_dir(repo, args.run) / "state.json")
    rs.set_round_decision(args.round, args.decision)
    rs.set_round_phase(args.round, "reviewed")
    rs.save(_run_dir(repo, args.run) / "state.json")
    _emit({"decision": args.decision, "review_path": str(rd / "codex-review.md")})
    return 0


@register("append-memo")
def _cmd_append_memo(args) -> int:
    repo = _Path(args.repo).resolve()
    memo_path = _run_dir(repo, args.run) / "memo.md"
    body = _Path(args.memo_file).read_text(encoding="utf-8")
    with memo_path.open("a", encoding="utf-8") as f:
        f.write("\n" + body.strip() + "\n")
    rs = RunState.load(_run_dir(repo, args.run) / "state.json")
    rs.set_round_phase(args.round, "memo_written")
    rs.save(_run_dir(repo, args.run) / "state.json")
    rs.set_round_phase(args.round, "completed")
    rs._round(args.round).ended_at = _dt.datetime.utcnow().isoformat()
    rs.save(_run_dir(repo, args.run) / "state.json")
    _emit({"memo_path": str(memo_path)})
    return 0


@register("memo-note")
def _cmd_memo_note(args) -> int:
    from agent_loop.diff_capture import compute_stats

    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rd = run_dir / "rounds" / f"{args.round:02d}"

    # memo-note is for supervisor-directed skip; verify round dir exists.
    _gate_path = rd / "round_plan.json"
    if not _gate_path.exists():
        _gate_path = rd / "round-plan.json"
    if not _gate_path.exists():
        print(f"memo-note refused: no round_plan.json or round-plan.json found for round {args.round}", file=sys.stderr)
        return 1

    # Compute diff stats if diff.patch exists
    diff_path = rd / "diff.patch"
    diff_size_str = "(not computed)"
    if diff_path.exists():
        diff = diff_path.read_text(encoding="utf-8")
        stats = compute_stats(diff)
        diff_size_str = f"files={stats.files_changed}, +{stats.insertions}/-{stats.deletions}"

    # Build memo block
    memo_block = "\n".join([
        f"## Round {args.round} - CONTINUE",
        "- Goal progress: worker completed assigned subtasks (round memo written; review deferred)",
        "- Top risks: (none flagged)",
        "- Carry forward: (none)",
        f"- Diff size: {diff_size_str}",
        "",
    ])

    memo_path = run_dir / "memo.md"
    appended = _append_memo_idempotent(memo_path, args.round, memo_block)

    rs = RunState.load(run_dir / "state.json")
    rs.set_round_phase(args.round, "skipped")
    entry = rs._round(args.round)
    entry.ended_at = _dt.datetime.utcnow().isoformat()
    entry.skip_reason = "supervisor-directed skip"
    rs.save(run_dir / "state.json")

    _emit({
        "memo_appended": appended,
        "memo_path": str(memo_path),
        "round": args.round,
        "phase": "skipped",
    })
    return 0
