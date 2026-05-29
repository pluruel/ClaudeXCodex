"""Phase transition command handlers: advance-phase, phase-commit."""
from __future__ import annotations

import json as _json
import sys
from pathlib import Path as _Path

from agent_loop.registry import register
from agent_loop.run_state import RunState


def _run_dir(repo: _Path, run_id: str) -> _Path:
    return repo / ".agent-loop" / "runs" / run_id


def _emit(obj) -> None:
    print(_json.dumps(obj, indent=2))


@register("advance-phase")
def _cmd_advance_phase(args) -> int:
    from agent_loop.codex_client import call_codex, CodexCallError
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    current_phase = rs.current_phase

    # If already on the last phase, emit sentinel without invoking Codex.
    if current_phase >= rs.total_phases:
        rs.phase_advance_pending = False
        rs.save(run_dir / "state.json")
        _emit({
            "previous_phase": current_phase,
            "current_phase": current_phase,
            "is_last_phase": True,
        })
        return 0

    # Load phases index.
    phases_json_path = run_dir / "phases.json"
    if not phases_json_path.exists():
        print("phases.json not found", file=sys.stderr)
        return 1
    try:
        phases = _json.loads(phases_json_path.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as e:
        print(f"phases.json parse error: {e}", file=sys.stderr)
        return 1
    if not isinstance(phases, list):
        print("phases.json must be a JSON array", file=sys.stderr)
        return 1

    next_phase_n = current_phase + 1
    next_entry = next(
        (p for p in phases if isinstance(p, dict) and p.get("phase_n") == next_phase_n),
        None,
    )
    if next_entry is None:
        print(f"no phases.json entry for phase {next_phase_n}", file=sys.stderr)
        return 1

    # Gather update context.
    def _read_safe(path: _Path, cap: int = 0) -> str:
        if not path.exists():
            return "(none)"
        text = path.read_text(encoding="utf-8").strip()
        if cap and len(text) > cap:
            return text[:cap]
        return text

    knowledge = _read_safe(run_dir / "shared" / "knowledge.md")
    decisions = _read_safe(run_dir / "shared" / "decisions.md")
    last_review = "(none)"
    if rs.rounds:
        last_review = _read_safe(
            run_dir / "rounds" / f"{rs.rounds[-1].n:02d}" / "codex-review.md",
            cap=1500,
        )

    doc_path = run_dir / next_entry.get(
        "doc_path", f"phases/phase-{next_phase_n:02d}.md",
    )
    original_doc = _read_safe(doc_path)

    update_prompt = (
        f"You are updating the strategic context document for Phase {next_phase_n} "
        "of an ongoing implementation.\n\n"
        "The previous phase is complete. Update the phase document to reflect what "
        "was actually accomplished and what this next phase should focus on.\n\n"
        "Output ONLY the updated markdown content (no JSON, no explanation, just the "
        "markdown document).\n\n"
        f"## Phase {next_phase_n} Original Document\n{original_doc}\n\n"
        f"## Accumulated Knowledge\n{knowledge}\n\n"
        f"## Accumulated Decisions\n{decisions}\n\n"
        f"## Last Codex Review\n{last_review}\n"
    )
    try:
        res = call_codex(update_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1

    doc_path.write_text(res.final_text.strip() + "\n", encoding="utf-8")

    rs.advance_current_phase()
    rs.save(run_dir / "state.json")

    _emit({
        "previous_phase": current_phase,
        "current_phase": rs.current_phase,
        "updated_doc": str(doc_path.relative_to(repo)),
        "is_last_phase": False,
    })
    return 0


@register("phase-commit")
def _cmd_phase_commit(args) -> int:
    import subprocess as _sp

    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)

    # Look up phase title from phases.json
    title = f"Phase {args.phase}"
    phases_json_path = run_dir / "phases.json"
    if phases_json_path.exists():
        try:
            phases = _json.loads(phases_json_path.read_text(encoding="utf-8"))
            entry = next((p for p in phases if isinstance(p, dict) and p.get("phase_n") == args.phase), None)
            if entry and entry.get("title"):
                title = entry["title"]
        except (_json.JSONDecodeError, OSError):
            pass

    # Stage changes, then unstage the .agent-loop artifact dir.
    # Naming an ignored path directly to `git add` (e.g. via :(exclude).agent-loop)
    # makes git exit non-zero with an "ignored files" advisory. Staging `.` skips
    # ignored paths silently; the follow-up reset drops .agent-loop when a user has
    # not gitignored it.
    stage_r = _sp.run(
        ["git", "add", "--", "."],
        cwd=repo, capture_output=True, text=True,
    )
    if stage_r.returncode != 0:
        print(stage_r.stderr, file=sys.stderr)
        return 1
    _sp.run(
        ["git", "reset", "-q", "--", ".agent-loop"],
        cwd=repo, capture_output=True, text=True,
    )

    # Check if anything is staged
    diff_r = _sp.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo, capture_output=True,
    )
    if diff_r.returncode == 0:
        # Exit code 0 means no diff — nothing staged
        print("phase-commit: nothing staged to commit", file=sys.stderr)
        return 1

    # Create the commit
    message = f"phase {args.phase}: {title}"
    commit_r = _sp.run(
        ["git", "commit", "-m", message],
        cwd=repo, capture_output=True, text=True,
    )
    if commit_r.returncode != 0:
        print(commit_r.stderr, file=sys.stderr)
        return 1

    # Get commit sha
    sha_r = _sp.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, capture_output=True, text=True,
    )
    commit_sha = sha_r.stdout.strip() if sha_r.returncode == 0 else ""

    # Record in state
    rs = RunState.load(run_dir / "state.json")
    rs.record_phase_commit(args.phase, commit_sha)
    rs.save(run_dir / "state.json")

    _emit({"phase": args.phase, "commit_sha": commit_sha, "message": message})
    return 0
