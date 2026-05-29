"""Review command handlers: review-round, phase-review."""
from __future__ import annotations

import datetime as _dt
import json as _json
import sys
from pathlib import Path as _Path

from agent_loop.registry import register
from agent_loop.run_state import RunState
from agent_loop.config import (
    _load_config,
    _artifact_mode,
)
from agent_loop.verification import (
    _scan_verification_outcomes,
    _bounded_memo,
)
from agent_loop.phases import (
    _load_current_phase_section,
)


def _run_dir(repo: _Path, run_id: str) -> _Path:
    return repo / ".agent-loop" / "runs" / run_id


def _emit(obj) -> None:
    print(_json.dumps(obj, indent=2))


def _parse_review_fields(review_md: str) -> dict:
    """Extract memo-relevant sections from Codex review markdown."""
    import re as _re
    def section(name: str) -> str:
        m = _re.search(
            rf"^##\s+{_re.escape(name)}\s*\n(.*?)(?=^##\s+|\Z)",
            review_md, _re.MULTILINE | _re.DOTALL,
        )
        return m.group(1).strip() if m else ""

    def bullets(text: str, cap: int = 3) -> list[str]:
        import re as _re2
        out = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith(("-", "*")):
                out.append(_re2.sub(r"^[-*]\s*", "", s).strip())
        return [b for b in out if b][:cap]

    goal = section("Goal Alignment")
    goal_line = " ".join(goal.split())[:200] if goal else ""
    return {
        "goal_progress": goal_line,
        "top_risks": bullets(section("Risks")),
        "carry_forward": bullets(section("Carry-Forward For Next Round")),
    }


def _compose_memo_block(round_n: int, decision: str, fields: dict,
                       stats, safety_flags: list) -> str:
    """Build the 5-10 line memo block per round-memo.md schema."""
    def join_bullets(items: list[str], empty: str) -> str:
        return "; ".join(items) if items else empty
    sensitive = (
        "yes -- diff touched sensitive paths"
        if "diff_has_sensitive" in safety_flags else "none"
    )
    diff_size = (
        f"files={stats.files_changed}, "
        f"+{stats.insertions}/-{stats.deletions}"
    )
    return "\n".join([
        f"## Round {round_n} - {decision}",
        f"- Goal progress: {fields['goal_progress'] or '(unspecified)'}",
        f"- Top risks: {join_bullets(fields['top_risks'], '(none flagged)')}",
        f"- Carry forward: {join_bullets(fields['carry_forward'], '(none)')}",
        f"- Sensitive: {sensitive}",
        f"- Diff size: {diff_size}",
        "",
    ])


def _append_memo_idempotent(memo_path: _Path, round_n: int, block: str) -> bool:
    """Append memo block unless this round already appears in memo.md.

    Returns True if appended, False if skipped (already present).
    """
    import re as _re
    existing = memo_path.read_text(encoding="utf-8") if memo_path.exists() else ""
    if _re.search(rf"^##\s+Round\s+{round_n}\s+-\s+",
                  existing, _re.MULTILINE):
        return False
    with memo_path.open("a", encoding="utf-8") as f:
        f.write("\n" + block.strip() + "\n")
    return True


def _compact_round_artifacts(rd: _Path, *, keep_diff: bool) -> list[str]:
    removed: list[str] = []
    names = ["diff-stats.json", "progress.md"]
    if not keep_diff:
        names.append("diff.patch")
    for name in names:
        path = rd / name
        if path.exists():
            path.unlink()
            removed.append(name)
    return removed


@register("review-round")
def _cmd_review_round(args) -> int:
    import re
    from agent_loop.codex_client import call_codex, CodexCallError
    from agent_loop.diff_capture import compute_stats
    from agent_loop.payload import build_review_payload
    from agent_loop.safety import SafetyConfig
    from agent_loop.shared_io import SharedDelta

    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rd = run_dir / "rounds" / f"{args.round:02d}"

    # Verify round plan exists before proceeding.
    _gate_path = rd / "round_plan.json"
    if not _gate_path.exists():
        _gate_path = rd / "round-plan.json"
    if not _gate_path.exists():
        print(f"review-round refused: no round plan found for round {args.round}", file=sys.stderr)
        return 1

    cfg = _load_config(repo)
    artifact_mode = _artifact_mode(cfg)
    safety_cfg_data = cfg
    safety = SafetyConfig(
        bash_block_patterns=safety_cfg_data.get("safety", {}).get("bash_block", {}).get("patterns", []),
        sensitive_path_patterns=safety_cfg_data.get("safety", {}).get("sensitive_paths", {}).get("patterns", []),
    )

    # Load state early so we can inject the current phase doc into the review prompt.
    rs = RunState.load(run_dir / "state.json")
    current_phase_section = _load_current_phase_section(run_dir, rs.current_phase)

    diff_path = rd / "diff.patch"
    if not diff_path.exists():
        diff_path.write_text("", encoding="utf-8")
    diff = diff_path.read_text(encoding="utf-8")
    stats = compute_stats(diff, sensitive_patterns=safety.sensitive_path_patterns)
    if artifact_mode == "debug":
        (rd / "diff-stats.json").write_text(_json.dumps(stats.__dict__, indent=2), encoding="utf-8")

    safety_flags: list[str] = ["diff_has_sensitive"] if stats.sensitive_hits else []

    # B1: Check if this round's plan had a parse failure; surface as safety flag.
    round_plan_path = rd / "round_plan.json"
    if not round_plan_path.exists():
        round_plan_path = rd / "round-plan.json"
    if round_plan_path.exists():
        try:
            rp_data = _json.loads(round_plan_path.read_text(encoding="utf-8"))
            if rp_data.get("parse_failed"):
                safety_flags.append("round_plan_parse_failed")
        except (_json.JSONDecodeError, OSError):
            safety_flags.append("round_plan_parse_failed")

    # B3: Scan progress.md for verification outcomes.
    verification_outcomes = _scan_verification_outcomes(rd / "progress.md")

    delta = SharedDelta()
    goal_summary = (run_dir / "goal.md").read_text(encoding="utf-8").strip().splitlines()[0]
    payload = build_review_payload(
        out_path=rd / "review-payload.json",
        round_n=args.round,
        goal_summary=goal_summary,
        stats=stats,
        shared_delta=delta,
        artifact_paths={
            "result": "",
            "diff": str(diff_path.relative_to(repo)),
            "test_log": str((rd / "test-log.txt").relative_to(repo)) if (rd / "test-log.txt").exists() else "",
            "messages": "",
        },
        safety_flags=safety_flags,
        verification_outcomes=verification_outcomes,
    )

    memo_path = run_dir / "memo.md"
    memo = memo_path.read_text(encoding="utf-8") if memo_path.exists() else ""

    test_results_path = run_dir / "shared" / "test-results.md"
    test_results_content = (
        test_results_path.read_text(encoding="utf-8")
        if test_results_path.exists()
        else "(none — test results unavailable; treat test status as unknown)"
    )

    shared_decisions_path = run_dir / "shared" / "decisions.md"
    shared_decisions_content = (
        shared_decisions_path.read_text(encoding="utf-8")
        if shared_decisions_path.exists()
        else "(none)"
    )

    shared_knowledge_path = run_dir / "shared" / "knowledge.md"
    shared_knowledge_content = (
        shared_knowledge_path.read_text(encoding="utf-8")
        if shared_knowledge_path.exists()
        else "(none)"
    )

    meta_prompt = f"""You are reviewing one round of Claude's work.

Output a markdown review body following this schema EXACTLY:

# Codex Review -- Round {args.round}

## Decision
APPROVE | NEEDS_CHANGES | PHASE_COMPLETE

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

Review directives:
- Do NOT attempt to run tests yourself. Use the `## Test Results` section above as the sole source of test status.
- Read the changed files from the diff directly to review code quality, logic errors, and correctness.
- If test results are unavailable (unknown), note this but do not issue NEEDS_CHANGES solely because you could not run tests.
- Do NOT flag mojibake, garbled text, or character encoding issues. On Windows with CP949/EUC-KR, non-ASCII bytes in diffs are a local encoding display artifact — not actual data corruption. Completely ignore any findings about unreadable characters, encoding errors, or suspicious byte sequences in diffs.

Decision rules:
- PHASE_COMPLETE when this phase's objective (from the Current Phase section) is fully achieved and the codebase is ready for the next phase.
- APPROVE if the entire run goal is achieved (all phases complete or goal fully satisfied).
- NEEDS_CHANGES otherwise (default).

Note: safety_flags in the payload are informational context. Use them to inform your decision freely — they do not force any particular outcome.

## Payload For This Round
{_json.dumps(payload, indent=2)}

## Accumulated Memo So Far
{memo or "(empty)"}

## Test Results (recorded by verification subtask)
{test_results_content}
{current_phase_section}
## Shared Context

### decisions.md
{shared_decisions_content}

### knowledge.md
{shared_knowledge_content}
"""
    try:
        res = call_codex(meta_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1

    (rd / "codex-review.md").write_text(res.final_text, encoding="utf-8")

    m = re.search(
        r"##\s+Decision\s*\n\s*(APPROVE|NEEDS_CHANGES|PHASE_COMPLETE)\s*",
        res.final_text, re.IGNORECASE,
    )
    decision = m.group(1).upper() if m else "NEEDS_CHANGES"

    # Reload to pick up any external mutation while the Codex call was in flight,
    # then mutate and persist.
    rs = RunState.load(run_dir / "state.json")
    rs.set_round_decision(args.round, decision)
    rs.set_round_phase(args.round, "reviewed")
    if decision == "PHASE_COMPLETE":
        rs.phase_advance_pending = True
    rs.save(run_dir / "state.json")

    memo_fields = _parse_review_fields(res.final_text)
    import re as _re_sev
    severity_counts = {"high": 0, "med": 0, "low": 0}
    for _m in _re_sev.finditer(r"\[severity:\s*(high|med|low)\]", res.final_text, _re_sev.IGNORECASE):
        _key = _m.group(1).lower()
        severity_counts[_key] = severity_counts.get(_key, 0) + 1
    memo_block = _compose_memo_block(
        round_n=args.round,
        decision=decision,
        fields=memo_fields,
        stats=stats,
        safety_flags=safety_flags,
    )
    memo_path = run_dir / "memo.md"
    appended = _append_memo_idempotent(memo_path, args.round, memo_block)
    rs.set_round_phase(args.round, "memo_written")
    rs.set_round_phase(args.round, "completed")
    rs._round(args.round).ended_at = _dt.datetime.utcnow().isoformat()
    rs.save(run_dir / "state.json")

    artifacts_removed: list[str] = []
    if artifact_mode == "compact" and not safety_flags:
        artifacts_removed = _compact_round_artifacts(rd, keep_diff=False)

    _emit({
        "decision": decision,
        "current_phase": rs.current_phase,
        "review_path": str(rd / "codex-review.md"),
        "round": args.round,
        "safety_flags": safety_flags,
        "memo_appended": appended,
        "memo_path": str(memo_path),
        "artifact_mode": artifact_mode,
        "artifacts_removed": artifacts_removed,
        "severity_counts": severity_counts,
        "carry_forward": memo_fields["carry_forward"],
    })
    return 0


@register("phase-review")
def _cmd_phase_review(args) -> int:
    import re as _re
    import subprocess as _sp

    from agent_loop.codex_client import call_codex, CodexCallError
    from agent_loop.run_state import RunState

    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)

    # Guard: require phase-commit to have been recorded first
    rs = RunState.load(run_dir / "state.json")
    if not rs.phase_commits.get(str(args.phase)):
        print(f"phase-commit not recorded for phase {args.phase}", file=sys.stderr)
        return 1

    # Collect phase diff from the recorded phase commit sha
    phase_commit_sha = rs.phase_commits[str(args.phase)]
    diff_result = _sp.run(
        ["git", "diff", f"{phase_commit_sha}~1", phase_commit_sha],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    phase_diff = diff_result.stdout if diff_result.returncode == 0 else "(git diff failed)"

    # Load phase objective doc
    phase_doc = ""
    phases_json_path = run_dir / "phases.json"
    if phases_json_path.exists():
        try:
            phases = _json.loads(phases_json_path.read_text(encoding="utf-8"))
            entry = next((p for p in phases if isinstance(p, dict) and p.get("phase_n") == args.phase), None)
            if entry:
                doc_path = run_dir / entry.get("doc_path", f"phases/phase-{args.phase:02d}.md")
                if doc_path.exists():
                    phase_doc = doc_path.read_text(encoding="utf-8").strip()
        except (_json.JSONDecodeError, OSError):
            pass

    def _read_safe(path: _Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else "(none)"

    test_results = _read_safe(run_dir / "shared" / "test-results.md")
    decisions = _read_safe(run_dir / "shared" / "decisions.md")
    knowledge = _read_safe(run_dir / "shared" / "knowledge.md")
    memo = _read_safe(run_dir / "memo.md")

    # Save phase diff artifact
    phases_dir = run_dir / "phases"
    phases_dir.mkdir(exist_ok=True)
    diff_artifact = phases_dir / f"phase-{args.phase:02d}-diff.patch"
    diff_artifact.write_text(phase_diff, encoding="utf-8")

    prompt = f"""You are reviewing Phase {args.phase} of a software implementation.

Output a markdown review following this schema EXACTLY:

# Phase Review -- Phase {args.phase}

## Decision
APPROVE | NEEDS_CHANGES

## Goal Alignment
<1-2 sentences: did the phase diff achieve the phase objective?>

## Findings
- [severity: high|med|low] <file:line if known> -- <issue>

## Verification
- Tests: pass|fail|missing -- <specifics>

## Risks
- <if any>

## Carry-Forward For Next Round
- <bullet, <= 3 items>

## Final Notes
<optional>

Decision rules:
- APPROVE: phase objective fully achieved, tests pass, no high-severity issues.
- NEEDS_CHANGES: objective not met, OR high-severity issues, OR tests fail.

Do NOT flag mojibake, garbled text, or character encoding issues. On Windows with CP949/EUC-KR, non-ASCII bytes in diffs are a local encoding display artifact — not actual data corruption.

## Phase Objective
{phase_doc or "(no phase doc available)"}

## Phase Diff (git diff HEAD~1)
{phase_diff or "(empty diff)"}

## Test Results
{test_results}

## Accumulated Memo
{memo}

## Shared Context

### decisions.md
{decisions}

### knowledge.md
{knowledge}
"""

    try:
        res = call_codex(prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1

    # Save review artifact
    review_path = phases_dir / f"phase-{args.phase:02d}-review.md"
    review_path.write_text(res.final_text, encoding="utf-8")

    # Parse decision
    m = _re.search(r"##\s+Decision\s*\n\s*(APPROVE|NEEDS_CHANGES)\s*", res.final_text, _re.IGNORECASE)
    decision = m.group(1).upper() if m else "NEEDS_CHANGES"

    # Parse severity counts
    severity_counts: dict[str, int] = {"high": 0, "med": 0, "low": 0}
    for sm in _re.finditer(r"\[severity:\s*(high|med|low)\]", res.final_text, _re.IGNORECASE):
        k = sm.group(1).lower()
        severity_counts[k] = severity_counts.get(k, 0) + 1

    # Parse carry_forward bullets
    cf_match = _re.search(
        r"##\s+Carry-Forward For Next Round\s*\n(.*?)(?=^##\s+|\Z)",
        res.final_text, _re.MULTILINE | _re.DOTALL,
    )
    carry_forward: list[str] = []
    if cf_match:
        for line in cf_match.group(1).splitlines():
            s = line.strip()
            if s.startswith(("-", "*")):
                carry_forward.append(_re.sub(r"^[-*]\s*", "", s).strip())
    carry_forward = [c for c in carry_forward if c][:3]

    # Get current HEAD sha
    sha_r = _sp.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    current_sha = sha_r.stdout.strip() if sha_r.returncode == 0 else ""

    # Update state
    rs = RunState.load(run_dir / "state.json")
    rs.add_phase_review(
        phase_n=args.phase,
        decision=decision,
        sha=current_sha,
        review_path=str(review_path.relative_to(repo)),
    )
    consecutive_nc = rs.consecutive_phase_needs_changes(args.phase) if decision == "NEEDS_CHANGES" else 0
    rs.save(run_dir / "state.json")

    # Append memo (idempotent — use synthetic round_n 1000+phase to avoid clash with real round memos)
    memo_block = "\n".join([
        f"## Round {1000 + args.phase} - Phase {args.phase} Review {decision}",
        f"- Severity: high={severity_counts['high']}, med={severity_counts['med']}, low={severity_counts['low']}",
        f"- Carry forward: {'; '.join(carry_forward) if carry_forward else '(none)'}",
        "",
    ])
    appended = _append_memo_idempotent(
        run_dir / "memo.md",
        round_n=1000 + args.phase,
        block=memo_block,
    )

    _emit({
        "decision": decision,
        "phase": args.phase,
        "review_path": str(review_path.relative_to(repo)),
        "severity_counts": severity_counts,
        "carry_forward": carry_forward,
        "memo_appended": appended,
        "consecutive_needs_changes": consecutive_nc,
    })
    return 0
