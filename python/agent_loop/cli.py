"""agent-loop CLI entry point."""
from __future__ import annotations

import argparse
import sys


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--repo", default=".",
        help="target repo path (default: cwd)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-loop")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # init-run
    p = sub.add_parser("init-run", help="create new run directory")
    _add_common(p)
    p.add_argument("--goal", required=True)
    p.add_argument("--slug", required=True)

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
                   choices=["APPROVE", "NEEDS_CHANGES", "STOP_FOR_USER"])
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

    # inspect
    p = sub.add_parser("inspect", help="extract a slice of a round artifact")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--path", default=None)
    p.add_argument("--lines", default=None, help="e.g. 12-40")

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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _HANDLERS.get(args.cmd)
    if handler is None:
        parser.error(f"no handler for {args.cmd}")
    return handler(args)


_HANDLERS: dict = {}


def register(name: str):
    def deco(fn):
        _HANDLERS[name] = fn
        return fn
    return deco


# Handlers will be added in Task 3.2 below.

import datetime as _dt
import json as _json
from pathlib import Path as _Path

from agent_loop.run_state import RunState


def _run_dir(repo: _Path, run_id: str) -> _Path:
    return repo / ".agent-loop" / "runs" / run_id


def _today_slug(slug: str) -> str:
    return f"{_dt.date.today().isoformat()}-{slug}"


def _emit(obj) -> None:
    print(_json.dumps(obj, indent=2))


@register("init-run")
def _cmd_init_run(args) -> int:
    repo = _Path(args.repo).resolve()
    run_id = _today_slug(args.slug)
    run_dir = _run_dir(repo, run_id)
    (run_dir / "rounds").mkdir(parents=True, exist_ok=True)
    (run_dir / "shared").mkdir(parents=True, exist_ok=True)
    (run_dir / "goal.md").write_text(args.goal + "\n")
    (run_dir / "memo.md").write_text("# Round Memos\n\n")
    rs = RunState.new(run_id=run_id, goal_path="goal.md", plan_path="plan.md")
    rs.save(run_dir / "state.json")
    _emit({"run_id": run_id, "run_dir": str(run_dir)})
    return 0


@register("init-round")
def _cmd_init_round(args) -> int:
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    next_n = (rs.rounds[-1].n + 1) if rs.rounds else 1
    rd = run_dir / "rounds" / f"{next_n:02d}"
    rd.mkdir(parents=True, exist_ok=True)
    prompt_text = _Path(args.prompt_file).read_text()
    (rd / "claude-prompt.md").write_text(prompt_text)
    rs.start_round(n=next_n, started_at=_dt.datetime.utcnow().isoformat())
    rs.save(run_dir / "state.json")
    _emit({"round_n": next_n, "prompt_path": str(rd / "claude-prompt.md")})
    return 0


@register("plan-init")
def _cmd_plan_init(args) -> int:
    from agent_loop.codex_client import call_codex, CodexCallError
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    goal = (run_dir / "goal.md").read_text(encoding="utf-8").strip()
    meta_prompt = (
        "You are drafting the initial implementation plan for the following goal. "
        "Output ONLY a markdown document with two sections:\n\n"
        "# Plan\n\n## Tasks\n1. [ ] <first concrete task>\n2. [ ] ...\n\n"
        "## Notes\n<short strategic notes>\n\n"
        "Aim for 3-7 tasks, each completable in one round. No prose outside these sections.\n\n"
        f"## Goal\n{goal}\n"
    )
    try:
        res = call_codex(meta_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1
    plan_path = run_dir / "plan.md"
    plan_path.write_text(res.final_text, encoding="utf-8")
    _emit({"plan_path": str(plan_path), "summary": "plan drafted"})
    return 0


@register("plan-round")
def _cmd_plan_round(args) -> int:
    from agent_loop.codex_client import call_codex, CodexCallError
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    next_n = (rs.rounds[-1].n + 1) if rs.rounds else 1

    goal = (run_dir / "goal.md").read_text(encoding="utf-8").strip()
    plan_path = run_dir / "plan.md"
    plan = plan_path.read_text(encoding="utf-8") if plan_path.exists() else "(no plan.md)"
    memo_path = run_dir / "memo.md"
    memo = memo_path.read_text(encoding="utf-8") if memo_path.exists() else ""

    prev_round = next_n - 1
    last_payload = ""
    if prev_round >= 1:
        ppath = run_dir / "rounds" / f"{prev_round:02d}" / "review-payload.json"
        if ppath.exists():
            last_payload = ppath.read_text(encoding="utf-8")

    meta_prompt = f"""You are drafting the Claude worker prompt for round {next_n}.

Write ONLY the prompt body (markdown). It MUST include these sections:
- ## Carry-Forward From Previous Round
- ## Goal
- ## Task (this round)
- ## Required Reading (read these first, in order)
- ## Suggested Reading (only if needed)
- ## Out of Scope (do not Read/Edit/Write)
- ## External References
- ## Mandatory Outputs (progress.md, claude-result.md schema, shared/* discipline)
- ## Reading List Discipline
- ## Forbidden Actions
- ## claude-result.md schema

Use the goal, plan, memo, and previous review payload (if any) to fill these in.
Keep Required Reading to <= 4 paths. Out of Scope must cover unrelated top-level dirs.

## Goal
{goal}

## Plan
{plan}

## Memo So Far
{memo or "(empty -- first round)"}

## Previous Review Payload (round {prev_round})
{last_payload or "(none -- first round)"}
"""
    try:
        res = call_codex(meta_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1

    rd = run_dir / "rounds" / f"{next_n:02d}"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "claude-prompt.md").write_text(res.final_text, encoding="utf-8")
    rs.start_round(n=next_n, started_at=_dt.datetime.utcnow().isoformat())
    rs.save(run_dir / "state.json")
    _emit({
        "round_n": next_n,
        "prompt_path": str(rd / "claude-prompt.md"),
        "summary": f"round {next_n} prompt drafted",
    })
    return 0


@register("review-round")
def _cmd_review_round(args) -> int:
    import re
    import tomllib
    from agent_loop.codex_client import call_codex, CodexCallError
    from agent_loop.diff_capture import compute_stats
    from agent_loop.payload import build_review_payload
    from agent_loop.result_parser import parse_result, ClaudeResult
    from agent_loop.safety import SafetyConfig, classify_diff_size
    from agent_loop.shared_io import SharedDelta

    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rd = run_dir / "rounds" / f"{args.round:02d}"

    cfg_path = repo / ".agent-loop" / "config.toml"
    if not cfg_path.exists():
        cfg_path = _Path(__file__).resolve().parents[2] / "config" / "defaults.toml"
    safety_cfg_data = tomllib.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    safety = SafetyConfig(
        bash_block_patterns=safety_cfg_data.get("safety", {}).get("bash_block", {}).get("patterns", []),
        sensitive_path_patterns=safety_cfg_data.get("safety", {}).get("sensitive_paths", {}).get("patterns", []),
        diff_warn_files=safety_cfg_data.get("safety", {}).get("diff_size", {}).get("warn_files", 15),
        diff_warn_lines=safety_cfg_data.get("safety", {}).get("diff_size", {}).get("warn_lines", 600),
    )

    diff_path = rd / "diff.patch"
    if not diff_path.exists():
        diff_path.write_text("", encoding="utf-8")
    diff = diff_path.read_text(encoding="utf-8")
    stats = compute_stats(diff, sensitive_patterns=safety.sensitive_path_patterns)
    (rd / "diff-stats.json").write_text(_json.dumps(stats.__dict__, indent=2), encoding="utf-8")

    safety_flags: list[str] = ["diff_has_sensitive"] if stats.sensitive_hits else []
    safety_flags += classify_diff_size(
        files=stats.files_changed,
        lines=stats.insertions + stats.deletions,
        cfg=safety,
    )

    result_path = rd / "claude-result.md"
    if result_path.exists():
        result = parse_result(result_path)
    else:
        result = ClaudeResult(summary="(no claude-result.md found)")
        safety_flags.append("missing_claude_result")

    delta = SharedDelta()
    goal_summary = (run_dir / "goal.md").read_text(encoding="utf-8").strip().splitlines()[0]
    payload = build_review_payload(
        out_path=rd / "review-payload.json",
        round_n=args.round,
        goal_summary=goal_summary,
        result=result,
        stats=stats,
        shared_delta=delta,
        artifact_paths={
            "result": str(result_path.relative_to(repo)) if result_path.exists() else "",
            "diff": str(diff_path.relative_to(repo)),
            "test_log": str((rd / "test-log.txt").relative_to(repo)) if (rd / "test-log.txt").exists() else "",
            "messages": "",
        },
        safety_flags=safety_flags,
    )

    memo_path = run_dir / "memo.md"
    memo = memo_path.read_text(encoding="utf-8") if memo_path.exists() else ""

    result_md = result_path.read_text(encoding="utf-8") if result_path.exists() else "(missing)"

    meta_prompt = f"""You are reviewing one round of Claude's work.

Output a markdown review body following this schema EXACTLY:

# Codex Review -- Round {args.round}

## Decision
APPROVE | NEEDS_CHANGES | STOP_FOR_USER

## Goal Alignment
<1-2 sentences>

## Findings
- [severity: high|med|low] <file:line if known> -- <issue>

## Verification
- Tests: pass|fail|missing -- <specifics>

## Risks
- <if any>

## Carry-Forward For Next Round
- <bullet, <= 3 items, quoted verbatim into next prompt>

## Final Notes
<optional>

Decision rules:
- STOP_FOR_USER if safety_flags non-empty, OR result.requires_user true, OR you see ambiguity needing human judgement.
- APPROVE if goal satisfied this round + tests pass + no flags.
- NEEDS_CHANGES otherwise (default).

## Payload For This Round
{_json.dumps(payload, indent=2)}

## Accumulated Memo So Far
{memo or "(empty)"}

## Claude's Result Report
{result_md}
"""
    try:
        res = call_codex(meta_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1

    (rd / "codex-review.md").write_text(res.final_text, encoding="utf-8")

    m = re.search(
        r"##\s+Decision\s*\n\s*(APPROVE|NEEDS_CHANGES|STOP_FOR_USER)\s*",
        res.final_text, re.IGNORECASE,
    )
    decision = m.group(1).upper() if m else "STOP_FOR_USER"

    rs = RunState.load(run_dir / "state.json")
    rs.set_round_decision(args.round, decision)
    rs.set_round_phase(args.round, "reviewed")
    rs.save(run_dir / "state.json")

    _emit({
        "decision": decision,
        "review_path": str(rd / "codex-review.md"),
        "round": args.round,
        "safety_flags": safety_flags,
    })
    return 0


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


@register("scout")
def _cmd_scout(args) -> int:
    from agent_loop.scout import scout
    repo = _Path(args.repo).resolve()
    rep = scout(repo, goal=args.goal, keywords=args.keywords, max_files=args.max_files)
    _emit({
        "file_tree": rep.file_tree,
        "grep_hits": rep.grep_hits,
        "headers": rep.headers,
    })
    return 0


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
    memo_tail = ""
    memo_path = run_dir / "memo.md"
    if memo_path.exists():
        memo_tail = "\n".join(memo_path.read_text().splitlines()[-30:])
    _emit({"state": _json.loads((run_dir / "state.json").read_text()), "memo_tail": memo_tail})
    return 0


@register("finalize")
def _cmd_finalize(args) -> int:
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    rs.status = "completed"
    rs.save(run_dir / "state.json")
    memo = (run_dir / "memo.md").read_text() if (run_dir / "memo.md").exists() else ""
    (run_dir / "final-report.md").write_text(
        f"# Final Report — {rs.run_id}\n\nStatus: {rs.status}\n\n## Round Memos\n\n{memo}\n"
    )
    _emit({"final_report": str(run_dir / "final-report.md"), "status": rs.status})
    return 0


@register("abort")
def _cmd_abort(args) -> int:
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    rs.status = "aborted"
    rs.save(run_dir / "state.json")
    _emit({"status": rs.status})
    return 0


@register("inspect")
def _cmd_inspect(args) -> int:
    repo = _Path(args.repo).resolve()
    rd = _run_dir(repo, args.run) / "rounds" / f"{args.round:02d}"
    target = rd / args.file
    if not target.exists():
        _emit({"error": f"not found: {target}"})
        return 1
    text = target.read_text()
    if args.lines:
        a, b = (int(x) for x in args.lines.split("-"))
        lines = text.splitlines()
        text = "\n".join(lines[a - 1:b])
    if args.path:
        # naive filter for diff.patch: only emit chunks mentioning the path
        if args.file == "diff.patch":
            chunks = []
            keep = False
            for ln in text.splitlines():
                if ln.startswith("diff --git "):
                    keep = args.path in ln
                if keep:
                    chunks.append(ln)
            text = "\n".join(chunks)
    print(text)
    return 0


@register("write-review")
def _cmd_write_review(args) -> int:
    repo = _Path(args.repo).resolve()
    rd = _run_dir(repo, args.run) / "rounds" / f"{args.round:02d}"
    body = _Path(args.review_file).read_text()
    (rd / "codex-review.md").write_text(body)
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
    body = _Path(args.memo_file).read_text()
    with memo_path.open("a") as f:
        f.write("\n" + body.strip() + "\n")
    rs = RunState.load(_run_dir(repo, args.run) / "state.json")
    rs.set_round_phase(args.round, "memo_written")
    rs.save(_run_dir(repo, args.run) / "state.json")
    rs.set_round_phase(args.round, "completed")
    rs._round(args.round).ended_at = _dt.datetime.utcnow().isoformat()
    rs.save(_run_dir(repo, args.run) / "state.json")
    _emit({"memo_path": str(memo_path)})
    return 0


@register("continue")
def _cmd_continue(args) -> int:
    from agent_loop.resume import determine_resume_action, find_active_run
    repo = _Path(args.repo).resolve()
    if args.run:
        run_dir = _run_dir(repo, args.run)
    else:
        run_dir = find_active_run(repo)
        if run_dir is None:
            print("no active run", file=sys.stderr)
            return 1
    rs = RunState.load(run_dir / "state.json")
    plan = determine_resume_action(rs, run_dir=run_dir)
    _emit({
        "action": plan.action,
        "notes": plan.notes,
        "options": plan.options,
        "run_id": rs.run_id,
        "current_round": rs.current_round,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
