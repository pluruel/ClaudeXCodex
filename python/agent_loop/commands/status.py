"""Status and progress command handlers."""
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


@register("status")
def _cmd_status(args) -> int:
    from agent_loop.resume import find_active_run
    repo = _Path(args.repo).resolve()
    if args.run:
        run_dir = _run_dir(repo, args.run)
    else:
        run_dir = find_active_run(repo)
        if run_dir is None:
            _emit({"error": "no active run"})
            return 1
    rs = RunState.load(run_dir / "state.json")
    # --json: emit legacy machine-readable output (backward compat)
    if getattr(args, "json", False):
        memo_tail = ""
        memo_path = run_dir / "memo.md"
        if memo_path.exists():
            memo_tail = "\n".join(memo_path.read_text(encoding="utf-8").splitlines()[-30:])
        _emit({
            "state": _json.loads((run_dir / "state.json").read_text(encoding="utf-8")),
            "memo_tail": memo_tail,
        })
        return 0
    # Default: render progress view
    from agent_loop.progress_parser import parse_progress
    from agent_loop.progress_view import render_progress
    state_dict = _json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    phases: list[dict] = []
    phases_path = run_dir / "phases.json"
    if phases_path.exists():
        try:
            phases = _json.loads(phases_path.read_text(encoding="utf-8"))
        except _json.JSONDecodeError:
            phases = []
    if not isinstance(phases, list):
        phases = []
    # Current round: last round in state or 0
    current_round = state_dict.get("current_round", 0)
    progress_path = run_dir / "rounds" / f"{current_round:02d}" / "progress.md" if current_round else _Path("/nonexistent")
    snapshot = parse_progress(progress_path)
    ascii_mode = getattr(args, "ascii", False)
    print(render_progress(state_dict, phases, snapshot, ascii=ascii_mode))
    return 0


@register("progress")
def _cmd_progress(args) -> int:
    from agent_loop.resume import find_active_run
    from agent_loop.progress_parser import parse_progress
    from agent_loop.progress_view import render_progress
    repo = _Path(args.repo).resolve()
    if args.run:
        run_dir = _run_dir(repo, args.run)
    else:
        run_dir = find_active_run(repo)
        if run_dir is None:
            print("error: no active run", file=sys.stderr)
            return 1
    state_dict = _json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    phases: list[dict] = []
    phases_path = run_dir / "phases.json"
    if phases_path.exists():
        try:
            phases = _json.loads(phases_path.read_text(encoding="utf-8"))
        except _json.JSONDecodeError:
            phases = []
    if not isinstance(phases, list):
        phases = []
    # Current round: last round in state or 0
    current_round = state_dict.get("current_round", 0)
    progress_path = run_dir / "rounds" / f"{current_round:02d}" / "progress.md" if current_round else _Path("/nonexistent")
    snapshot = parse_progress(progress_path)
    ascii_mode = getattr(args, "ascii", False)
    print(render_progress(state_dict, phases, snapshot, ascii=ascii_mode))
    return 0
