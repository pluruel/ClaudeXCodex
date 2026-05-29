"""Planning command handlers: plan-init, plan-round."""
from __future__ import annotations

import datetime as _dt
import json as _json
import sys
from pathlib import Path as _Path

from agent_loop.registry import register
from agent_loop.run_state import RunState
from agent_loop.config import (
    _load_config,
    _worker_model_config,
    _worker_reasoning_config,
)
from agent_loop.round_plan import (
    _parse_round_plan,
    _parse_phase_target_files,
    _validate_round_plan_quality,
)
from agent_loop.verification import (
    _count_consecutive_needs_changes,
    _bounded_memo,
)
from agent_loop.phases import (
    _single_phase_fallback,
    _validate_phase_specs,
    _assemble_phases_from_specs,
    _parse_plan_phases,
    _parse_phases_response,
    _load_current_phase_section,
    _repair_target_files,
)
from agent_loop.prompt_sections import (
    _render_subtasks_block,
    _inject_subtasks_section,
)


def _run_dir(repo: _Path, run_id: str) -> _Path:
    return repo / ".agent-loop" / "runs" / run_id


def _emit(obj) -> None:
    print(_json.dumps(obj, indent=2))


@register("plan-init")
def _cmd_plan_init(args) -> int:
    from agent_loop.codex_client import call_codex, CodexCallError
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    goal = (run_dir / "goal.md").read_text(encoding="utf-8").strip()
    plan_path = run_dir / "plan.md"

    if plan_path.exists():
        # Pre-existing plan (written by init-run --plan-file or the plan skill).
        # Skip the draft Codex call; use the file as-is.
        plan_text = plan_path.read_text(encoding="utf-8")
        plan_source = "pre-existing"
    else:
        # First Codex call: draft plan.md (existing behavior).
        plan_prompt = (
            "You are drafting the initial implementation plan for the following goal. "
            "Output ONLY a markdown document with two sections:\n\n"
            "# Plan\n\n## Tasks\n1. [ ] <first concrete task>\n2. [ ] ...\n\n"
            "## Notes\n<short strategic notes>\n\n"
            "Aim for 3-7 tasks, each completable in one round. No prose outside these sections.\n\n"
            f"## Goal\n{goal}\n"
        )
        try:
            plan_res = call_codex(plan_prompt)
        except CodexCallError as e:
            print(f"codex error: {e}", file=sys.stderr)
            return 1
        plan_text = plan_res.final_text
        plan_path.write_text(plan_text, encoding="utf-8")
        plan_source = "codex"

    # Run scout BEFORE asking Codex to draft phases.
    # Derive keywords from the plan text: capitalized identifiers and path-like strings.
    import re as _re_kw
    _kw_candidates: list[str] = []
    # path-like strings (contain / or .)
    _kw_candidates += _re_kw.findall(r"[\w._/-]{3,}/[\w._/-]+", plan_text)
    # capitalized identifiers (CamelCase or ALL_CAPS)
    _kw_candidates += _re_kw.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", plan_text)
    # deduplicate, lowercase, cap to 6
    _seen_kw: set[str] = set()
    _keywords: list[str] = []
    for _kw in _kw_candidates:
        _lkw = _kw.lower()
        if _lkw not in _seen_kw:
            _seen_kw.add(_lkw)
            _keywords.append(_kw.lower())
        if len(_keywords) >= 6:
            break
    if not _keywords:
        _keywords = ["main"]

    scout_signal = {"file_tree": [], "grep_hits": [], "headers": []}
    try:
        from agent_loop.scout import scout as _scout
        _scout_rep = _scout(repo, goal=goal, keywords=_keywords, max_files=200)
        scout_signal = {
            "file_tree": _scout_rep.file_tree,
            "grep_hits": _scout_rep.grep_hits,
            "headers": _scout_rep.headers,
        }
    except Exception:
        pass  # Fall back to empty signal; do not abort plan-init

    phase_validation_errors: list[str] = []
    phase_source = "codex"

    # --- Parsed-plan fast path ---
    # When plan_source == "pre-existing" and the plan.md contains a ## Phases
    # section parseable by _parse_plan_phases, skip the Codex phases_prompt
    # call and assemble phase docs directly from the parsed specs.
    if plan_source == "pre-existing":
        _parsed_phases = _parse_plan_phases(plan_text)
        if _parsed_phases:
            # Repair any missing target_files paths with a single Codex call.
            _parsed_phases, _repair_log = _repair_target_files(
                _parsed_phases, repo, scout_signal, call_codex
            )
            phase_validation_errors = _repair_log
            phases_index = _assemble_phases_from_specs(_parsed_phases, run_dir, repo)
            if not phases_index:
                _fb = _single_phase_fallback()
                phases_dir = run_dir / "phases"
                phases_dir.mkdir(exist_ok=True)
                phases_index = []
                for _fbph in _fb:
                    _doc_path = phases_dir / f"phase-{_fbph['phase_n']:02d}.md"
                    _doc_path.write_text(_fbph["content"], encoding="utf-8")
                    phases_index.append({
                        "phase_n": _fbph["phase_n"],
                        "title": _fbph["title"],
                        "objective": _fbph["objective"],
                        "doc_path": f"phases/phase-{_fbph['phase_n']:02d}.md",
                    })
            phase_source = "parsed"
            (run_dir / "phases.json").write_text(
                _json.dumps(phases_index, indent=2) + "\n", encoding="utf-8",
            )
            rs = RunState.load(run_dir / "state.json")
            rs.total_phases = len(phases_index)
            rs.current_phase = 1
            rs.save(run_dir / "state.json")
            _emit({
                "plan_path": str(plan_path),
                "plan_source": plan_source,
                "phase_source": phase_source,
                "phases": phases_index,
                "phase_validation_errors": phase_validation_errors,
                "summary": f"{len(phases_index)} phase(s) drafted",
            })
            return 0
        # else: fall through to Codex phases_prompt path below

    # --- Codex phases_prompt path (existing behavior, unchanged) ---
    # Build the strict JSON phases prompt.
    _scout_file_tree_str = "\n".join(scout_signal["file_tree"][:80]) or "(none)"
    _scout_grep_hits_str = _json.dumps(scout_signal["grep_hits"][:40], indent=2) if scout_signal["grep_hits"] else "(none)"
    _scout_headers_str = _json.dumps(scout_signal["headers"][:20], indent=2) if scout_signal["headers"] else "(none)"

    phases_prompt = (
        "You are generating a phased implementation plan for a software development goal.\n\n"
        "IMPORTANT: Before populating 'target_files' for each phase, you MUST read at least 3 real "
        "source files in the repository. Use the Repo Signal below as a starting point, then open "
        "the actual files. Only cite repo-relative paths that genuinely exist in the repository.\n\n"
        "Analyze the goal complexity and decide how many phases (1-5):\n"
        "- 1 phase: simple goal, achievable in 3-7 rounds total\n"
        "- 2-3 phases: moderate complexity with distinct milestones\n"
        "- 4-5 phases: large goal with multiple independent subsystems\n\n"
        "Output ONLY JSON (no prose, no fenced block) matching this schema EXACTLY:\n"
        '{\n'
        '  "phases": [\n'
        '    {\n'
        '      "phase_n": 1,\n'
        '      "title": "<short phase title>",\n'
        '      "objective": "<one sentence: what this phase achieves>",\n'
        '      "scope_hint": "<one line: file paths, area of code, or domain hint>",\n'
        '      "target_files": ["<repo-relative POSIX path>", ...],\n'
        '      "acceptance_criteria": ["<criterion including a runnable command like pytest ... or grep ...>", ...],\n'
        '      "testing": {"command": "<runnable test command>", "expected": "<expected outcome>"},\n'
        '      "out_of_scope": ["<what this phase explicitly does NOT cover>"],\n'
        '      "notes": "<any constraints or context>"\n'
        '    }\n'
        '  ]\n'
        '}\n\n'
        "Rules:\n"
        "- 'target_files' MUST be repo-relative POSIX paths (no leading /, no ..).\n"
        "- Every path in 'target_files' MUST exist in the repository.\n"
        "- 'acceptance_criteria' MUST include at least one runnable command "
        "(e.g. 'pytest path/to/test.py', 'python -m ...', 'grep ...', or a line starting with '$ ...').\n\n"
        f"## Goal\n{goal}\n\n"
        f"## Plan (tasks overview)\n{plan_text}\n\n"
        "## Repo Signal\n\n"
        f"### file_tree\n{_scout_file_tree_str}\n\n"
        f"### grep_hits\n{_scout_grep_hits_str}\n\n"
        f"### headers\n{_scout_headers_str}\n"
    )

    try:
        phases_res = call_codex(phases_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1

    # Try to parse the strict JSON response.
    _phases_text = phases_res.final_text.strip()
    if _phases_text.startswith("```"):
        _phases_text = _re_kw.sub(r"^```(?:json)?\s*", "", _phases_text)
        _phases_text = _re_kw.sub(r"\s*```$", "", _phases_text).strip()
    _parsed_strict: dict | None = None
    try:
        _parsed_strict = _json.loads(_phases_text)
        if not isinstance(_parsed_strict, dict):
            _parsed_strict = None
    except _json.JSONDecodeError:
        _parsed_strict = None

    if _parsed_strict is not None and isinstance(_parsed_strict.get("phases"), list):
        # Validate the parsed specs.
        _specs = _parsed_strict["phases"]
        phase_validation_errors = _validate_phase_specs(_specs, repo)

        if phase_validation_errors:
            # Re-invoke Codex ONCE with a rejected preamble.
            _retry_prompt = (
                "Your previous response was rejected for the following reasons:\n"
                + "\n".join(f"- {e}" for e in phase_validation_errors)
                + "\nReturn corrected JSON matching the schema exactly.\n\n"
                + phases_prompt
            )
            try:
                _retry_res = call_codex(_retry_prompt)
                _retry_text = _retry_res.final_text.strip()
                if _retry_text.startswith("```"):
                    _retry_text = _re_kw.sub(r"^```(?:json)?\s*", "", _retry_text)
                    _retry_text = _re_kw.sub(r"\s*```$", "", _retry_text).strip()
                _retry_parsed: dict | None = None
                try:
                    _retry_parsed = _json.loads(_retry_text)
                    if not isinstance(_retry_parsed, dict):
                        _retry_parsed = None
                except _json.JSONDecodeError:
                    _retry_parsed = None

                if _retry_parsed is not None and isinstance(_retry_parsed.get("phases"), list):
                    _retry_specs = _retry_parsed["phases"]
                    _retry_errors = _validate_phase_specs(_retry_specs, repo)
                    phase_validation_errors = _retry_errors
                    _parsed_strict = _retry_parsed
                    _specs = _retry_specs
                # If retry parse failed, keep original _parsed_strict and errors
            except CodexCallError:
                pass  # Keep original _parsed_strict, errors persist

        # Assemble phase docs from JSON specs using shared helper.
        phases_index = _assemble_phases_from_specs(
            [dict(s) for s in _parsed_strict.get("phases", []) if isinstance(s, dict)],
            run_dir,
            repo,
        )

        if not phases_index:
            # All specs were invalid; fall back to single phase
            _fb = _single_phase_fallback()
            phases_index = []
            phases_dir = run_dir / "phases"
            phases_dir.mkdir(exist_ok=True)
            for _fbph in _fb:
                _doc_path = phases_dir / f"phase-{_fbph['phase_n']:02d}.md"
                _doc_path.write_text(_fbph["content"], encoding="utf-8")
                phases_index.append({
                    "phase_n": _fbph["phase_n"],
                    "title": _fbph["title"],
                    "objective": _fbph["objective"],
                    "doc_path": f"phases/phase-{_fbph['phase_n']:02d}.md",
                })

    else:
        # JSON parse failed entirely — fall back to the legacy markdown path.
        phases = _parse_phases_response(phases_res.final_text)
        phases_dir = run_dir / "phases"
        phases_dir.mkdir(exist_ok=True)
        phases_index = []
        for ph in phases:
            doc_path = phases_dir / f"phase-{ph['phase_n']:02d}.md"
            doc_path.write_text(ph["content"], encoding="utf-8")
            phases_index.append({
                "phase_n": ph["phase_n"],
                "title": ph["title"],
                "objective": ph["objective"],
                "doc_path": f"phases/phase-{ph['phase_n']:02d}.md",
            })

    (run_dir / "phases.json").write_text(
        _json.dumps(phases_index, indent=2) + "\n", encoding="utf-8",
    )

    # Update state with phase counts.
    rs = RunState.load(run_dir / "state.json")
    rs.total_phases = len(phases_index)
    rs.current_phase = 1
    rs.save(run_dir / "state.json")

    _emit({
        "plan_path": str(plan_path),
        "plan_source": plan_source,
        "phase_source": phase_source,
        "phases": phases_index,
        "phase_validation_errors": phase_validation_errors,
        "summary": f"{len(phases_index)} phase(s) drafted",
    })
    return 0


@register("plan-round")
def _cmd_plan_round(args) -> int:
    from agent_loop.codex_client import call_codex, CodexCallError
    from agent_loop.prompt_render import RoundContext, ReadingList, render_claude_prompt
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    consecutive_nc = _count_consecutive_needs_changes(rs)
    next_n = (rs.rounds[-1].n + 1) if rs.rounds else 1
    cfg = _load_config(repo)
    allowed_models, default_model = _worker_model_config(cfg)
    allowed_efforts, default_effort = _worker_reasoning_config(cfg)

    goal = (run_dir / "goal.md").read_text(encoding="utf-8").strip()
    plan_path = run_dir / "plan.md"
    plan = plan_path.read_text(encoding="utf-8") if plan_path.exists() else "(no plan.md)"
    memo_path = run_dir / "memo.md"
    memo_full = memo_path.read_text(encoding="utf-8") if memo_path.exists() else ""
    memo_bounded = _bounded_memo(memo_full, max_rounds=3)
    current_phase_section = _load_current_phase_section(run_dir, rs.current_phase)
    _phase_doc_path_str = str(run_dir / "phases" / f"phase-{rs.current_phase:02d}.md")

    prev_round = next_n - 1
    last_payload = ""
    if prev_round >= 1:
        ppath = run_dir / "rounds" / f"{prev_round:02d}" / "review-payload.json"
        if ppath.exists():
            last_payload = ppath.read_text(encoding="utf-8")

    round_plan_prompt = f"""You are selecting the Claude worker model, reasoning effort, and subtask breakdown for round {next_n}.

Output ONLY JSON with this schema:
{{
  "round_plan": {{
    "round": {next_n},
    "worker_model": "<one of: {', '.join(allowed_models)}>",
    "worker_model_reason": "<one sentence>",
    "reasoning_effort": "{'|'.join(allowed_efforts)}",
    "subtasks": [
      {{
        "id": "<round-unique string, e.g. r{next_n}-i1>",
        "role": "implementation|verification",
        "model": "<one of: {', '.join(allowed_models)}>",
        "reasoning_effort": "{'|'.join(allowed_efforts)}",
        "description": "<one sentence>",
        "required_reading": ["<path>"],
        "out_of_scope": ["<path-or-pattern>"],
        "depends_on": ["<same-round subtask id>"],
        "deliverable": "<what this subtask must produce>"
      }}
    ],
    "phase_complete_signal": true
  }},
  "task_description": "<one paragraph describing what the worker must accomplish this round>",
  "execution_plan_bullets": [
    "<step 1 — concrete: name files, edits, commands>",
    "<step 2>",
    "..."
  ],
  "acceptance_criteria": [
    "<checkable bullet 1>",
    "<checkable bullet 2>",
    "..."
  ],
  "carry_forward": "<bullet summary of what to carry from previous round, or empty string>"
}}

Repo-inspection requirement (MANDATORY — do this BEFORE drafting execution_plan_bullets):
- OPEN every file listed under the ## Target Files section of the current phase document (phase doc path: {_phase_doc_path_str}).
- Read enough of each file to locate the relevant functions, classes, or line ranges.
- In EACH execution_plan_bullets entry, quote a specific function name, symbol name, or line range from the file you opened (e.g. "python/agent_loop/cli.py:_cmd_plan_round" or "python/agent_loop/cli.py:350-390").

Execution plan quality rules (MANDATORY — violations cause worker failure):
- Every bullet in execution_plan_bullets MUST name a specific file path (e.g. "python/agent_loop/cli.py:354", NOT "the CLI file").
- Every bullet MUST state the exact change: function name, variable, line range, or the precise text to add/remove. "Update the function" is NOT acceptable.
- A worker reading ONLY these bullets, with zero additional context, must be able to execute without inference or guesswork.

Acceptance criteria quality rules (MANDATORY — vague criteria are rejected):
- Every criterion in acceptance_criteria MUST be mechanically verifiable: a named test, a grep command, or a file-existence check.
- NOT acceptable: "the feature works" or "code is clean".
- ACCEPTABLE: "pytest python/tests/test_cli_review_gate.py::test_memo_note_sets_skipped_phase passes" or "grep -n 'skipped' python/agent_loop/run_state.py returns a line in the Phase Literal".
- At least one criterion MUST be a runnable command with a specific expected output.

Self-check before outputting (mandatory):
- Could a worker with ZERO context complete every execution_plan_bullets step on the first try? If no → rewrite those bullets with specific file paths and line references.
- Is every acceptance_criteria criterion binary (pass/fail with a named command)? If no → rewrite as a command with expected output.

Model selection rules:
- haiku: mechanical, 1-2 likely files, clear execution plan, clear tests, low risk.
- sonnet: normal integration work, multiple files, pattern matching, moderate uncertainty.
- opus: architecture, broad debugging, unclear requirements, high-risk safety/security/build/data changes.

Reasoning-effort selection rules (independent from model selection):
- low: mechanical, low ambiguity; the execution plan can be followed step-by-step.
- medium: normal integration work; some judgement and pattern matching required.
- high: architecture, broad debugging, or high-risk cross-cutting changes; deep reasoning required.

Model and reasoning_effort are two independent axes. Do NOT collapse the two choices.

Round granularity: one round should cover a complete, reviewable slice of work — not a single file change. Err on the side of larger rounds. Aim for round boundaries that correspond to meaningful milestones (a feature is functional, a subsystem is refactored, a test suite passes).

Subtask roles and rules:

| role | what it may do |
|------|----------------|
| `implementation` | MAY edit source files, tests, configs |
| `verification` | run ONLY named pytest or equivalent test commands specified in the deliverable; do NOT run lint, grep, state inspection, or code review; report pass/fail only |

- implementation subtasks: each must declare depends_on over any preceding implementation subtask ids it relies on.
  When emitting multiple implementation subtasks, always chain them sequentially via depends_on: the second subtask must declare depends_on: [first_subtask_id], the third must declare depends_on: [second_subtask_id], and so on. Never emit parallel implementation subtasks.
- verification subtasks: MUST NOT edit source files. Must name an exact check command in the deliverable.
  Include a verification subtask only when there are named test commands (pytest, unittest, or equivalent) that the implementation subtasks would not run themselves. Do NOT use verification subtasks for lint, grep, or state inspection.
  Dispatched after all implementation subtasks complete.
  If multiple verification subtasks exist, each must declare `depends_on` over ALL preceding verification subtask ids to ensure sequential execution.
  Each verification subtask MUST append its results to `shared/test-results.md`
  under a `## <subtask_id>` heading:
    ## <subtask_id>
    Status: PASS|FAIL
    <failure details if FAIL>
  Sequential execution guarantees no parallel write conflicts.
- Each subtask required_reading is capped at 5 paths; split the subtask if more are needed.
- opus subtasks require justification in the description.

The round-level worker_model and reasoning_effort are the "dominant character"
summary for the user announce line. Per-subtask model/effort govern actual dispatch.

If the ideal model is unavailable, choose the closest allowed model from the list.
If `reasoning_effort` is unclear, prefer `{default_effort}`.

## Goal
{goal}
{current_phase_section}
## Plan
{plan}

## Memo So Far
{memo_bounded or "(empty -- first round)"}

## Previous Review Payload (round {prev_round})
{last_payload or "(none -- first round)"}
"""
    try:
        round_plan_res = call_codex(round_plan_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1
    round_plan = _parse_round_plan(
        round_plan_res.final_text,
        round_n=next_n,
        allowed_models=allowed_models,
        default_model=default_model,
        allowed_efforts=allowed_efforts,
        default_effort=default_effort,
    )

    # Quality gate: validate round plan bullets and acceptance criteria.
    # Skip quality retry when parse already failed (parse_failed handles that path).
    quality_failed = False
    quality_errors: list[str] = []
    if not round_plan.get("parse_failed"):
        _phase_target_files = _parse_phase_target_files(run_dir, rs.current_phase)
        _quality_errors_1 = _validate_round_plan_quality(round_plan, repo, _phase_target_files)
        if _quality_errors_1:
            # Retry once with vagueness rejection preamble
            _retry_preamble = (
                "Your previous round plan was rejected for vagueness for the following reasons:\n"
                + "\n".join(_quality_errors_1)
                + "\nReturn corrected JSON matching the schema exactly.\n\n"
            )
            try:
                _retry_res = call_codex(_retry_preamble + round_plan_prompt)
                round_plan = _parse_round_plan(
                    _retry_res.final_text,
                    round_n=next_n,
                    allowed_models=allowed_models,
                    default_model=default_model,
                    allowed_efforts=allowed_efforts,
                    default_effort=default_effort,
                )
                if not round_plan.get("parse_failed"):
                    quality_errors = _validate_round_plan_quality(round_plan, repo, _phase_target_files)
                else:
                    quality_errors = _quality_errors_1
            except CodexCallError:
                quality_errors = _quality_errors_1
            quality_failed = bool(quality_errors)
        # If first attempt passed, quality_failed stays False and quality_errors stays []

    # Attach quality flags to the round_plan dict for disk persistence and downstream use.
    round_plan["quality_failed"] = quality_failed
    round_plan["quality_errors"] = quality_errors
    if quality_failed:
        round_plan.setdefault("safety_flags", [])
        if "quality_failed" not in round_plan["safety_flags"]:
            round_plan["safety_flags"].append("quality_failed")

    # Build the worker prompt using the Python template (A2).
    # Collect the union of required_reading from all subtasks.
    all_required_reading: list[tuple[str, str]] = []
    seen_paths: set[str] = set()
    for st in round_plan.get("subtasks", []):
        for path in st.get("required_reading", []):
            if path not in seen_paths:
                all_required_reading.append((path, ""))
                seen_paths.add(path)

    # Collect out_of_scope union from all subtasks.
    all_out_of_scope: list[str] = []
    seen_oos: set[str] = set()
    for st in round_plan.get("subtasks", []):
        for path in st.get("out_of_scope", []):
            if path not in seen_oos:
                all_out_of_scope.append(path)
                seen_oos.add(path)

    run_dir_rel = str(_Path(".agent-loop") / "runs" / args.run)
    round_dir_rel = str(_Path(".agent-loop") / "runs" / args.run / "rounds" / f"{next_n:02d}")
    shared_dir_rel = str(_Path(".agent-loop") / "runs" / args.run / "shared")

    # Build task text from Codex content fields.
    task_desc = round_plan.get("task_description", "")
    ep_bullets = round_plan.get("execution_plan_bullets", [])
    ac_bullets = round_plan.get("acceptance_criteria", [])

    task_parts = []
    if task_desc:
        task_parts.append(task_desc)
    if ep_bullets:
        task_parts.append("\n## Execution Plan\n" + "\n".join(f"{i+1}. {b}" for i, b in enumerate(ep_bullets)))
    if ac_bullets:
        task_parts.append("\n## Acceptance Criteria\n" + "\n".join(f"- {b}" for b in ac_bullets))
    task_text = "\n\n".join(task_parts) if task_parts else "(no task description provided)"

    carry_fwd = round_plan.get("carry_forward", "") or "(none)"

    from agent_loop.prompt_render import RoundContext, ReadingList, render_claude_prompt
    ctx = RoundContext(
        round_n=next_n,
        goal=goal,
        task=task_text,
        carry_forward=carry_fwd,
        reading=ReadingList(
            required=all_required_reading,
            suggested=[],
            out_of_scope=all_out_of_scope,
            references=[],
        ),
        run_dir_rel=run_dir_rel,
        shared_dir_rel=shared_dir_rel,
        round_dir_rel=round_dir_rel,
    )
    prompt_body = render_claude_prompt(ctx)
    prompt_body = _inject_subtasks_section(prompt_body, round_plan.get("subtasks", []))

    rd = run_dir / "rounds" / f"{next_n:02d}"
    rd.mkdir(parents=True, exist_ok=True)
    # Canonical artifact name is round_plan.json (underscore). The hyphenated
    # name round-plan.json is kept as a compatibility symlink/copy so existing
    # tests and external tooling that expect the old name still work.
    round_plan_path = rd / "round_plan.json"
    round_plan_path.write_text(_json.dumps(round_plan, indent=2) + "\n", encoding="utf-8")
    # Write compatibility alias for tooling that still uses the hyphenated name.
    (rd / "round-plan.json").write_text(_json.dumps(round_plan, indent=2) + "\n", encoding="utf-8")
    (rd / "claude-prompt.md").write_text(prompt_body, encoding="utf-8")
    rs.start_round(n=next_n, started_at=_dt.datetime.utcnow().isoformat())
    rs.save(run_dir / "state.json")
    subtasks = round_plan.get("subtasks", [])
    _emit({
        "round_n": next_n,
        "current_phase": rs.current_phase,
        "total_phases": rs.total_phases,
        "consecutive_needs_changes": consecutive_nc,
        "prompt_path": str(rd / "claude-prompt.md"),
        "round_plan_path": str(round_plan_path),
        "worker_model": round_plan["worker_model"],
        "worker_model_reason": round_plan["worker_model_reason"],
        "reasoning_effort": round_plan["reasoning_effort"],
        "subtasks": subtasks,
        "subtask_count": len(subtasks),
        "commit_message": round_plan["commit_message"],
        "phase_complete_signal": round_plan["phase_complete_signal"],
        "quality_failed": quality_failed,
        "quality_errors": quality_errors,
        "summary": f"round {next_n} prompt drafted",
    })
    return 0
