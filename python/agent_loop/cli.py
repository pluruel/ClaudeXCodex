"""agent-loop CLI entry point."""
from __future__ import annotations

import argparse
import sys

from agent_loop import __version__


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--repo", default=".",
        help="target repo path (default: cwd)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-loop")
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"agent-loop {__version__}",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # init-run
    p = sub.add_parser("init-run", help="create new run directory")
    _add_common(p)
    p.add_argument("--goal", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--plan-file", default=None,
                   help="path to an already-authorized plan file; copied to plan.md in the run dir")

    # plan-init
    p = sub.add_parser("plan-init", help="ask Codex to draft initial plan.md")
    _add_common(p)
    p.add_argument("--run", required=True)

    # plan-round
    p = sub.add_parser("plan-round", help="ask Codex to draft next round prompt")
    _add_common(p)
    p.add_argument("--run", required=True)

    # review-round
    p = sub.add_parser("review-round", help="ask Codex to review a finished round")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)

    # record-diff
    p = sub.add_parser("record-diff", help="worker hook: capture diff for a round")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--baseline", required=True)

    # capture-baseline
    p = sub.add_parser("capture-baseline", help="emit current HEAD sha for the worker to use later")
    _add_common(p)

    # mark-worker-done
    p = sub.add_parser("mark-worker-done", help="worker hook: flip phase to claude_completed")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)

    # mark-dispatched
    p = sub.add_parser("mark-dispatched", help="supervisor hook: flip phase to dispatched")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)

    # init-round
    p = sub.add_parser("init-round", help="render prompt + create round dir")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--prompt-file", required=True)

    # write-review
    p = sub.add_parser("write-review", help="record Codex review for a round")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--decision", required=True,
                   choices=["APPROVE", "NEEDS_CHANGES", "PHASE_COMPLETE"])
    p.add_argument("--review-file", required=True)

    # append-memo
    p = sub.add_parser("append-memo", help="append round-memo to memo.md")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--memo-file", required=True)

    # finalize
    p = sub.add_parser("finalize", help="write final-report.md and close run")
    _add_common(p)
    p.add_argument("--run", required=True)

    # abort
    p = sub.add_parser("abort", help="mark run as aborted")
    _add_common(p)
    p.add_argument("--run", required=True)

    # status
    p = sub.add_parser("status", help="print state.json + memo tail")
    _add_common(p)
    p.add_argument("--run", default=None)
    p.add_argument("--ascii", action="store_true", help="force ASCII glyph set")
    p.add_argument("--json", action="store_true", help="emit raw JSON (machine-readable, backward-compat)")

    # progress
    p = sub.add_parser("progress", help="print a rich progress view for the active run")
    _add_common(p)
    p.add_argument("--run", default=None)
    p.add_argument("--ascii", action="store_true", help="force ASCII glyph set")

    # inspect
    p = sub.add_parser("inspect", help="extract a slice of a round artifact")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--path", default=None)
    p.add_argument(
        "--lines",
        default=None,
        help=(
            "line slice. Accepts 'N' (first N), 'N-' (from N onward), "
            "or 'A-B' (range). 1-indexed and inclusive."
        ),
    )

    # scout
    p = sub.add_parser("scout", help="emit small repo signal JSON")
    _add_common(p)
    p.add_argument("--goal", required=True)
    p.add_argument("--keywords", nargs="+", required=True)
    p.add_argument("--max-files", type=int, default=200)

    # continue
    p = sub.add_parser("continue", help="resume an interrupted run")
    _add_common(p)
    p.add_argument("--run", default=None)

    # advance-phase
    p = sub.add_parser("advance-phase", help="transition to next phase and update phase doc")
    _add_common(p)
    p.add_argument("--run", required=True)

    # memo-note
    p = sub.add_parser("memo-note", help="write a round memo block and set phase to skipped (supervisor-directed)")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)

    # phase-review
    p = sub.add_parser("phase-review", help="Codex quality review for a completed phase")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--phase", type=int, required=True)

    # phase-commit
    p = sub.add_parser("phase-commit", help="commit the current phase boundary and record sha in state.json")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--phase", type=int, required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _HANDLERS.get(args.cmd)
    if handler is None:
        parser.error(f"no handler for {args.cmd}")
    return handler(args)


# Import registry so command submodules can do `from agent_loop.registry import register`
# without a circular import, while existing callers that do
# `from agent_loop.cli import register, _HANDLERS` continue to work unchanged.
from agent_loop.registry import register, _HANDLERS  # noqa: F401  (re-exported)

# Legacy re-exports: tests and external callers do `from agent_loop.cli import <name>`.
# These symbols live in their real modules; we re-export them here so imports don't break.
from agent_loop.config import (  # noqa: F401
    ArtifactMode,
    _load_config,
    _artifact_mode,
    _worker_model_config,
    _worker_reasoning_config,
)
from agent_loop.round_plan import (  # noqa: F401
    _normalize_reason,
    _normalize_subtask,
    _normalize_subtasks,
    _parse_round_plan,
    _parse_phase_target_files,
    _validate_round_plan_quality,
)
from agent_loop.verification import (  # noqa: F401
    _scan_verification_outcomes,
    _count_consecutive_needs_changes,
    _bounded_memo,
)
from agent_loop.phases import (  # noqa: F401
    _single_phase_fallback,
    _validate_phase_specs,
    _assemble_phase_doc,
    _repair_target_files,
    _assemble_phases_from_specs,
    _parse_plan_phases,
    _parse_phases_response,
    _load_current_phase_section,
)
from agent_loop.prompt_sections import (  # noqa: F401
    _render_subtasks_block,
    _inject_subtasks_section,
)
from agent_loop.run_state import RunState  # noqa: F401

# Importing the commands package triggers any @register decorators in submodules.
# This import is placed at the bottom so cli.py is fully initialised before
# commands/__init__.py runs (prevents circular import).
import agent_loop.commands  # noqa: E402, F401


if __name__ == "__main__":
    sys.exit(main())
