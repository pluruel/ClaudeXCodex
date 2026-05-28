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


_HANDLERS: dict = {}


def register(name: str):
    def deco(fn):
        _HANDLERS[name] = fn
        return fn
    return deco


# Handlers will be added in Task 3.2 below.

import datetime as _dt
import json as _json
import shutil as _shutil
from pathlib import Path as _Path

from agent_loop.run_state import RunState

ArtifactMode = str


def _run_dir(repo: _Path, run_id: str) -> _Path:
    return repo / ".agent-loop" / "runs" / run_id


def _today_slug(slug: str) -> str:
    return f"{_dt.date.today().isoformat()}-{slug}"


def _unique_run_id(repo: _Path, slug: str) -> str:
    base = _today_slug(slug)
    runs_root = repo / ".agent-loop" / "runs"
    if not (runs_root / base).exists():
        return base
    i = 2
    while (runs_root / f"{base}-{i}").exists():
        i += 1
    return f"{base}-{i}"


def _emit(obj) -> None:
    print(_json.dumps(obj, indent=2))


def _load_config(repo: _Path) -> dict:
    import tomllib

    default_path = _Path(__file__).resolve().parents[2] / "config" / "defaults.toml"
    data: dict = {}
    if default_path.exists():
        data = tomllib.loads(default_path.read_text(encoding="utf-8"))

    local_path = repo / ".agent-loop" / "config.toml"
    if local_path.exists():
        local = tomllib.loads(local_path.read_text(encoding="utf-8"))
        for key, value in local.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key] = {**data[key], **value}
            else:
                data[key] = value
    return data


def _artifact_mode(cfg: dict) -> ArtifactMode:
    mode = cfg.get("artifacts", {}).get("mode", "compact")
    if mode not in ("compact", "debug"):
        raise ValueError(f"invalid artifacts.mode {mode!r}; expected 'compact' or 'debug'")
    return mode


def _worker_model_config(cfg: dict) -> tuple[list[str], str]:
    worker_cfg = cfg.get("worker_models", {})
    allowed = worker_cfg.get("allowed", ["haiku", "sonnet", "opus"])
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        allowed = ["haiku", "sonnet", "opus"]
    default = worker_cfg.get("default", "sonnet")
    if default not in allowed:
        default = allowed[0] if allowed else "sonnet"
    return allowed, default


def _worker_reasoning_config(cfg: dict) -> tuple[list[str], str]:
    """Read `[worker_reasoning]` defaults and return ``(allowed, default)``.

    Mirrors the shape of ``_worker_model_config``. The reasoning axis is
    intentionally independent from model selection: a haiku subtask can still
    elect `high` effort if the few changes touch deep architecture, and an
    opus subtask can elect `low` if the changes are mostly mechanical.
    """
    reasoning_cfg = cfg.get("worker_reasoning", {})
    allowed = reasoning_cfg.get("allowed", ["low", "medium", "high"])
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        allowed = ["low", "medium", "high"]
    default = reasoning_cfg.get("default", "medium")
    if default not in allowed:
        default = "medium" if "medium" in allowed else (allowed[0] if allowed else "medium")
    return allowed, default


def _normalize_reason(raw: object) -> str:
    """Collapse a Codex-supplied reason to a safe single line.

    Codex sometimes returns multiline JSON values for ``worker_model_reason``.
    Collapse all whitespace runs (including newlines and tabs) to a single
    space before storing. An empty or falsy value falls back to a fixed default.
    """
    if raw is None:
        return "default model selected"
    text = str(raw)
    collapsed = " ".join(text.split()).strip()
    return collapsed or "default model selected"


def _normalize_subtask(raw: object, *, idx: int,
                        allowed_models: list[str], default_model: str,
                        allowed_efforts: list[str], default_effort: str) -> dict:
    """Normalize a single subtask dict from a Codex round plan.

    Missing required fields are filled with safe defaults. An unknown model
    or reasoning_effort is replaced with the configured default. The ``id``
    field, if missing or non-string, is regenerated as ``r<idx>-t<idx>``.
    If the input is not a dict at all, returns a minimal fallback subtask.

    Shape (as of C1a): id, role, model, reasoning_effort, required_reading,
    out_of_scope, depends_on, deliverable, description. The ``scope`` field
    has been removed; r1-i2 may layer additional normalization on top.
    """
    if not isinstance(raw, dict):
        raw = {}

    # id
    raw_id = raw.get("id")
    subtask_id = str(raw_id).strip() if isinstance(raw_id, str) and raw_id.strip() else f"s-{idx}"

    # role
    raw_role = raw.get("role", "implementation")
    role = raw_role if raw_role in ("implementation", "verification") else "implementation"

    # model
    raw_model = raw.get("model", default_model)
    model = raw_model if raw_model in allowed_models else default_model

    # reasoning_effort — role-aware default when missing
    role_effort_defaults = {"implementation": default_effort, "verification": "low"}
    role_default = role_effort_defaults.get(role, default_effort)
    raw_effort = raw.get("reasoning_effort")
    effort = raw_effort if isinstance(raw_effort, str) and raw_effort in allowed_efforts else role_default

    # required_reading / out_of_scope
    def _to_str_list(val: object) -> list[str]:
        if not isinstance(val, list):
            return []
        return [str(x) for x in val if isinstance(x, str) and x.strip()][:5]

    required_reading = _to_str_list(raw.get("required_reading"))
    out_of_scope = _to_str_list(raw.get("out_of_scope"))

    # depends_on
    raw_deps = raw.get("depends_on")
    depends_on = [str(x) for x in raw_deps if isinstance(x, str) and x.strip()] if isinstance(raw_deps, list) else []

    # deliverable / goal (description field may be either key)
    # B2: Replace the silent "complete the assigned task" default with an
    # obviously-placeholder string that includes the subtask id.
    # Capture raw_description BEFORE any fallback so that the opus downgrade
    # check evaluates the actual supplied value, not a fallback-filled value.
    raw_description = str(raw.get("description", "")).strip()
    deliverable = (
        str(raw.get("deliverable", "")).strip()
        or str(raw.get("goal", "")).strip()
        or f"{subtask_id} (no description supplied)"
    )
    description = raw_description or deliverable

    # B2: Track normalization notes for downstream consumers (e.g., safety audit).
    normalized_notes: list[str] = []

    # B2: Downgrade opus to default model when raw description is empty/whitespace.
    # Evaluate against raw_description (pre-fallback) so that a blank description
    # with a non-empty deliverable still triggers the downgrade.
    if raw.get("model") == "opus" and not raw_description:
        model = default_model
        normalized_notes.append("opus_downgraded_no_description")

    return {
        "id": subtask_id,
        "role": role,
        "model": model,
        "reasoning_effort": effort,
        "required_reading": required_reading,
        "out_of_scope": out_of_scope,
        "depends_on": depends_on,
        "deliverable": deliverable,
        "description": description,
        "normalized_notes": normalized_notes,
    }


def _normalize_subtasks(raw: object, *, allowed_models: list[str], default_model: str,
                         allowed_efforts: list[str], default_effort: str) -> list[dict]:
    """Normalize the ``subtasks`` field from a Codex round plan.

    Returns a list of normalized subtask dicts. An absent, non-list, or empty
    raw value returns an empty list (triggers single-worker fallback in the
    supervisor). Invalid list entries are normalized individually.

    B2: After individual normalization, a second pass detects and drops:
    - Cycle edges (A depends_on B which transitively depends_on A).
    - Reverse-direction edges (any subtask depending on a higher-role subtask
      in the wrong direction).

    Role ordering (lowest to highest): implementation < verification.
    A subtask may depend on same-role or lower-role subtasks only. A
    depends_on edge that points to a *higher*-role subtask is a reverse-
    direction edge and is dropped. Cycle edges are detected by DFS and dropped
    from the offending subtask's depends_on list.
    """
    if not isinstance(raw, list) or not raw:
        return []
    subtasks = [
        _normalize_subtask(
            item, idx=i,
            allowed_models=allowed_models, default_model=default_model,
            allowed_efforts=allowed_efforts, default_effort=default_effort,
        )
        for i, item in enumerate(raw)
    ]

    # B2: Build id -> subtask lookup and role-order map.
    _role_order = {"implementation": 0, "verification": 1}
    id_to_st: dict[str, dict] = {st["id"]: st for st in subtasks}

    # B2: Cycle detection using DFS. Returns True if `start` can reach `target`
    # by following depends_on edges (excluding the edge being tested).
    def _can_reach(start_id: str, target_id: str, exclude_edge: tuple[str, str] | None = None) -> bool:
        visited: set[str] = set()
        stack = [start_id]
        while stack:
            node = stack.pop()
            if node == target_id:
                return True
            if node in visited:
                continue
            visited.add(node)
            dep_st = id_to_st.get(node)
            if dep_st is None:
                continue
            for dep in dep_st.get("depends_on", []):
                if exclude_edge and (node, dep) == exclude_edge:
                    continue
                stack.append(dep)
        return False

    # B2: Drop reverse-direction and cycle edges.
    for st in subtasks:
        st_role_order = _role_order.get(st["role"], 1)
        clean_deps: list[str] = []
        for dep_id in st.get("depends_on", []):
            dep_st = id_to_st.get(dep_id)
            note: str | None = None
            if dep_st is not None:
                dep_role_order = _role_order.get(dep_st["role"], 1)
                if dep_role_order > st_role_order:
                    # Reverse-direction edge: this subtask has lower role but
                    # depends on a higher-role subtask.
                    note = f"dropped_reverse_edge:{dep_st['role']}->{st['role']}"
                elif _can_reach(dep_id, st["id"]):
                    # Cycle: dep already (transitively) depends on this subtask.
                    note = f"dropped_cycle_edge:{dep_id}->{st['id']}"
            if note is not None:
                st.setdefault("normalized_notes", []).append(note)
            else:
                clean_deps.append(dep_id)
        st["depends_on"] = clean_deps

    return subtasks


def _parse_round_plan(raw: str, *, round_n: int, allowed_models: list[str],
                      default_model: str,
                      allowed_efforts: list[str] | None = None,
                      default_effort: str = "medium") -> dict:
    """Parse a Codex round-plan response (JSON or fenced JSON block).

    Accepts either the legacy flat JSON shape or the merged-envelope shape
    introduced by A1. The merged envelope wraps round-plan fields under
    ``round_plan`` and adds prompt-content fields (``task_description``,
    ``execution_plan_bullets``, ``acceptance_criteria``, ``carry_forward``)
    at the top level or under a ``prompt_content`` key.

    Returns a normalized dict. ``scope`` and ``complexity`` fields are NOT
    included (removed by C1a and A3 respectively).
    """
    import re as _re

    text = raw.strip()
    if text.startswith("```"):
        text = _re.sub(r"^```(?:json)?\s*", "", text)
        text = _re.sub(r"\s*```$", "", text).strip()
    parse_failed = False
    try:
        envelope = _json.loads(text)
    except _json.JSONDecodeError:
        envelope = {}
        parse_failed = True
    if not isinstance(envelope, dict):
        envelope = {}
        parse_failed = True

    # Support merged-envelope shape: if top-level has "round_plan" sub-object,
    # use it for routing fields; prompt-content fields live at top level or
    # under "prompt_content".
    if "round_plan" in envelope and isinstance(envelope["round_plan"], dict):
        plan = envelope["round_plan"]
        pc = envelope.get("prompt_content") or envelope
    elif "round_plan" in envelope:
        # round_plan key is present but not a dict (e.g. list, string, null).
        # Treat as a parse failure so the safety flag is surfaced.
        parse_failed = True
        plan = {}
        pc = envelope
    else:
        plan = envelope
        pc = envelope

    worker_model = plan.get("worker_model", default_model)
    if worker_model not in allowed_models:
        worker_model = default_model

    # Normalize reasoning_effort. Missing, non-string, or out-of-allowed
    # values fall back to the configured default. Old Codex outputs that
    # omit the field stay backward compatible.
    effort_allowed = allowed_efforts if allowed_efforts else ["low", "medium", "high"]
    raw_effort = plan.get("reasoning_effort")
    if isinstance(raw_effort, str) and raw_effort in effort_allowed:
        reasoning_effort = raw_effort
    else:
        reasoning_effort = default_effort

    # Normalize subtasks. round_n is intentionally NOT used to regenerate ids;
    # Codex-supplied ids are trusted if they are unique, non-empty strings.
    # The supervisor enforces depends_on ordering at dispatch time per SKILL.md
    # Phase 2; the CLI normalizes and passes the field through.
    subtasks = _normalize_subtasks(
        plan.get("subtasks"),
        allowed_models=allowed_models,
        default_model=default_model,
        allowed_efforts=effort_allowed,
        default_effort=reasoning_effort,
    )

    # Prompt-content fields (A1/A2 merged envelope). Safe defaults used if
    # the field is absent (legacy flat shape or parse failure).
    def _str_field(key: str) -> str:
        val = pc.get(key, "")
        return str(val).strip() if val else ""

    def _list_field(key: str) -> list[str]:
        val = pc.get(key)
        if isinstance(val, list):
            return [str(x) for x in val if str(x).strip()]
        return []

    return {
        "round": round_n,
        "worker_model": worker_model,
        "worker_model_reason": _normalize_reason(plan.get("worker_model_reason")),
        "reasoning_effort": reasoning_effort,
        "subtasks": subtasks,
        # Prompt-content fields (A2)
        "task_description": _str_field("task_description"),
        "execution_plan_bullets": _list_field("execution_plan_bullets"),
        "acceptance_criteria": _list_field("acceptance_criteria"),
        "carry_forward": _str_field("carry_forward"),
        # Commit field: commit_on_approve has been removed from the Codex output schema;
        # review-round always runs for every round.
        "commit_message": str(plan.get("commit_message", "")).strip(),
        # B1: parse failure flag — True when the raw JSON was malformed or non-dict.
        "parse_failed": parse_failed,
        # phase_complete_signal: True when Codex signals the current phase is done.
        "phase_complete_signal": bool(plan.get("phase_complete_signal")) if plan.get("phase_complete_signal") is not None else False,
    }



def _single_phase_fallback() -> list[dict]:
    return [{
        "phase_n": 1,
        "title": "Implementation",
        "objective": "Complete the goal.",
        "content": "# Phase 1: Implementation\n\n## Objective\nComplete the goal.\n",
    }]


def _validate_phase_specs(specs: list[dict], repo: "_Path") -> list[str]:
    """Validate parsed phase spec list against schema and file-existence rules.

    Returns a list of error strings. Empty list means all specs are valid.
    Each phase entry must have:
      - non-empty 'title', 'objective'
      - non-empty 'target_files' list of repo-relative POSIX paths (no leading /, no ..)
      - each target_files entry must exist in the repo
      - non-empty 'acceptance_criteria' list with at least one runnable-command pattern
    """
    _RUNNABLE_PATTERNS = [
        "pytest ", "python -m ", "python ", "grep ", "npm ", "node ",
        "go test", "cargo ",
    ]
    errors: list[str] = []
    for ph in specs:
        if not isinstance(ph, dict):
            errors.append("phase entry is not a dict")
            continue
        n = ph.get("phase_n", "?")

        # Required string fields
        title = ph.get("title", "")
        if not (isinstance(title, str) and title.strip()):
            errors.append(f"phase {n}: 'title' is missing or empty")

        objective = ph.get("objective", "")
        if not (isinstance(objective, str) and objective.strip()):
            errors.append(f"phase {n}: 'objective' is missing or empty")

        # target_files
        tf = ph.get("target_files")
        if not isinstance(tf, list) or not tf:
            errors.append(f"phase {n}: 'target_files' must be a non-empty list")
        else:
            for path_str in tf:
                if not isinstance(path_str, str) or not path_str.strip():
                    errors.append(f"phase {n}: target_files entry is not a non-empty string")
                    continue
                if path_str.startswith("/") or path_str.startswith("\\"):
                    errors.append(f"phase {n}: target_files entry {path_str!r} must not be an absolute path")
                    continue
                if ".." in path_str.split("/") or ".." in path_str.split("\\"):
                    errors.append(f"phase {n}: target_files entry {path_str!r} must not contain '..'")
                    continue
                if not (repo / path_str).exists():
                    errors.append(f"phase {n}: target_files entry {path_str!r} not found in repo")

        # acceptance_criteria
        ac = ph.get("acceptance_criteria")
        if not isinstance(ac, list) or not ac:
            errors.append(f"phase {n}: 'acceptance_criteria' must be a non-empty list")
        else:
            has_runnable = any(
                any(pat in bullet for pat in _RUNNABLE_PATTERNS)
                or (isinstance(bullet, str) and bullet.strip().startswith("$ "))
                for bullet in ac
                if isinstance(bullet, str)
            )
            if not has_runnable:
                errors.append(
                    f"phase {n}: 'acceptance_criteria' must contain at least one runnable-command pattern "
                    f"(e.g. 'pytest ', 'python -m ', 'grep ', '$ ...', etc.)"
                )

        # testing dict (soft check — just presence)
        testing = ph.get("testing")
        if not isinstance(testing, dict):
            errors.append(f"phase {n}: 'testing' must be a dict with 'command' and 'expected'")
        else:
            if not testing.get("command"):
                errors.append(f"phase {n}: 'testing.command' is missing or empty")
            if not testing.get("expected"):
                errors.append(f"phase {n}: 'testing.expected' is missing or empty")

    return errors


def _assemble_phase_doc(spec: dict) -> str:
    """Assemble a phase markdown document from a validated phase spec dict.

    Returns markdown with the six required headings in fixed order:
    ## Objective, ## Target Files, ## Acceptance Criteria, ## Testing,
    ## Out of Scope, ## Notes.

    Uses the literal string '(none)' when a field is empty.
    """
    n = spec.get("phase_n", "?")
    title = spec.get("title", f"Phase {n}")
    objective = spec.get("objective", "(none)") or "(none)"

    tf = spec.get("target_files", [])
    if isinstance(tf, list) and tf:
        tf_block = "\n".join(f"- {p}" for p in tf)
    else:
        tf_block = "- (none)"

    ac = spec.get("acceptance_criteria", [])
    if isinstance(ac, list) and ac:
        ac_block = "\n".join(f"- {bullet}" for bullet in ac)
    else:
        ac_block = "- (none)"

    testing = spec.get("testing") or {}
    cmd = testing.get("command", "(none)") or "(none)"
    expected = testing.get("expected", "(none)") or "(none)"

    oos = spec.get("out_of_scope", [])
    if isinstance(oos, list) and oos:
        oos_block = "\n".join(f"- {item}" for item in oos)
    else:
        oos_block = "- (none)"

    notes = spec.get("notes", "(none)") or "(none)"

    return (
        f"# Phase {n}: {title}\n\n"
        f"## Objective\n{objective}\n\n"
        f"## Target Files\n{tf_block}\n\n"
        f"## Acceptance Criteria\n{ac_block}\n\n"
        f"## Testing\n- Command: `{cmd}`\n- Expected: {expected}\n\n"
        f"## Out of Scope\n{oos_block}\n\n"
        f"## Notes\n{notes}\n"
    )


def _repair_target_files(
    specs: "list[dict]",
    repo: "_Path",
    scout_signal: dict,
    call_codex,
) -> "tuple[list[dict], list[str]]":
    """Repair missing/invalid target_files paths in phase specs using one Codex call.

    Collects paths that don't exist in the repo (or have leading / or ..) and
    asks Codex to map them to real paths.  Returns updated specs and a log of
    repairs/drops.  Makes at most ONE Codex call.  On CodexCallError, drops
    invalid paths silently.
    """
    import json as _json_r
    import re as _re_r
    from agent_loop.codex_client import CodexCallError as _CodexCallError

    def _is_valid(p: str, repo: "_Path") -> bool:
        if not isinstance(p, str) or not p.strip():
            return False
        if p.startswith("/") or p.startswith("\\"):
            return False
        if ".." in p.split("/") or ".." in p.split("\\"):
            return False
        return (repo / p).exists()

    # Collect missing paths per spec index
    missing: list[str] = []
    for spec in specs:
        for p in (spec.get("target_files") or []):
            if not _is_valid(p, repo):
                if p not in missing:
                    missing.append(p)

    if not missing:
        return specs, []

    # Build repair prompt
    _file_tree_str = "\n".join(scout_signal.get("file_tree", [])[:80]) or "(none)"
    repair_prompt = (
        "Some target_files paths in a phased plan do not exist in the repository.\n"
        "For each missing path, find the best matching real repo-relative POSIX path "
        "that currently exists, or return empty string if no good match exists.\n\n"
        "Missing paths:\n"
        + "\n".join(f"- {p}" for p in missing)
        + "\n\nRepo file tree (partial):\n"
        + _file_tree_str
        + "\n\nRespond with ONLY a JSON object, no prose, no fences:\n"
        '{"repairs": {"<missing/path.py>": "<real/path.py or empty string>"}}'
    )

    repairs: dict[str, str] = {}
    try:
        repair_res = call_codex(repair_prompt)
        raw = repair_res.final_text.strip()
        # Strip ``` fences
        raw = _re_r.sub(r"^```(?:json)?\s*", "", raw)
        raw = _re_r.sub(r"\s*```$", "", raw).strip()
        try:
            parsed = _json_r.loads(raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("repairs"), dict):
                repairs = {str(k): str(v) for k, v in parsed["repairs"].items()}
        except _json_r.JSONDecodeError:
            pass
    except _CodexCallError:
        pass  # Drop invalid paths without repair

    repair_log: list[str] = []
    updated_specs: list[dict] = []
    for spec in specs:
        spec = dict(spec)
        n = spec.get("phase_n", "?")
        tf = spec.get("target_files") or []
        new_tf: list[str] = []
        for p in tf:
            if _is_valid(p, repo):
                new_tf.append(p)
            else:
                repaired = repairs.get(p, "")
                if repaired and _is_valid(repaired, repo):
                    new_tf.append(repaired)
                    repair_log.append(f"phase {n}: {p} -> {repaired}")
                else:
                    repair_log.append(f"phase {n}: dropped nonexistent {p}")
        spec["target_files"] = new_tf
        updated_specs.append(spec)

    return updated_specs, repair_log


def _assemble_phases_from_specs(
    specs: "list[dict]",
    run_dir: "_Path",
    repo: "_Path",
) -> "list[dict]":
    """Normalize, filter, sort, write phase docs, and return phases_index.

    Used by both the parsed-plan path and the Codex-JSON path so no
    assembly logic is duplicated.  Specs are modified in-place (phase_n
    re-numbered).  Returns the phases_index list (dicts with phase_n, title,
    objective, doc_path).
    """
    # Filter out invalid target_files in each spec
    normalized: list[dict] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        spec = dict(spec)
        tf = spec.get("target_files", [])
        if isinstance(tf, list):
            spec["target_files"] = [
                p for p in tf
                if isinstance(p, str) and p.strip()
                and not p.startswith("/")
                and ".." not in p.split("/")
                and (repo / p).exists()
            ]
        normalized.append(spec)

    # Sort and cap
    normalized.sort(key=lambda s: s.get("phase_n", 999))
    normalized = normalized[:5]

    # Re-number
    for new_n, spec in enumerate(normalized, start=1):
        spec["phase_n"] = new_n

    phases_dir = run_dir / "phases"
    phases_dir.mkdir(exist_ok=True)
    phases_index: list[dict] = []
    for spec in normalized:
        ph_n = spec["phase_n"]
        title = str(spec.get("title", f"Phase {ph_n}")).strip()
        objective = str(spec.get("objective", "")).strip()
        doc_content = _assemble_phase_doc(spec)
        doc_path = phases_dir / f"phase-{ph_n:02d}.md"
        doc_path.write_text(doc_content, encoding="utf-8")
        phases_index.append({
            "phase_n": ph_n,
            "title": title,
            "objective": objective,
            "doc_path": f"phases/phase-{ph_n:02d}.md",
        })

    return phases_index


def _parse_plan_phases(plan_text: str) -> "list[dict] | None":
    """Parse the ## Phases section of a plan.md into a list of phase spec dicts.

    Each dict has keys: phase_n, title, objective, target_files,
    acceptance_criteria, testing, out_of_scope, notes.

    Returns None when there is no ## Phases section or zero phases are parsed.
    """
    import re

    # Extract the ## Phases section (ends at next ## heading or end of document)
    phases_match = re.search(
        r"^## Phases\s*\n(.*?)(?=\n## |\Z)",
        plan_text,
        re.MULTILINE | re.DOTALL,
    )
    if not phases_match:
        return None

    section = phases_match.group(1)

    # Split into per-phase blocks on lines matching: N. **Title** -- objective
    # Separators: --, —, –, or :
    phase_header_re = re.compile(
        r"^(\d+)\.\s+\*\*([^*]+)\*\*\s*(?:--|—|–|:)\s*(.*?)\s*$",
        re.MULTILINE,
    )

    # Also match one-liner or no-separator form: N. **Title**
    phase_header_nosep_re = re.compile(
        r"^(\d+)\.\s+\*\*([^*]+)\*\*\s*$",
        re.MULTILINE,
    )

    # Find all phase header positions in section
    headers: list[tuple[int, int, str, str]] = []  # (start, number, title, objective)
    for m in re.finditer(
        r"^(\d+)\.\s+\*\*([^*]+)\*\*(?:\s*(?:--|—|–|:)\s*(.*?))?\s*$",
        section,
        re.MULTILINE,
    ):
        num = int(m.group(1))
        title = m.group(2).strip()
        objective = (m.group(3) or "").strip()
        headers.append((m.start(), num, title, objective))

    if not headers:
        return None

    def _split_top_level_bullets(body: str) -> "list[tuple[str, str]]":
        """Split body into (key, block) pairs by top-level sub-bullets.

        A top-level sub-bullet is a line whose bullet character is at the
        leftmost indented position — i.e., the first bullet indent level seen.
        Returns list of (header_text, full_block_text) tuples.
        """
        lines = body.split("\n")
        if not lines:
            return []
        # Determine the outermost indent level from first bullet line
        outer_indent: int | None = None
        for line in lines:
            stripped = line.lstrip()
            if stripped and stripped[0] in "-*":
                outer_indent = len(line) - len(stripped)
                break
        if outer_indent is None:
            return []

        outer_bullet_re = re.compile(r"^" + " " * outer_indent + r"[-*]\s+(.*)")
        blocks: list[tuple[str, str]] = []
        current_key = ""
        current_lines: list[str] = []
        for line in lines:
            m = outer_bullet_re.match(line)
            if m:
                if current_key:
                    blocks.append((current_key, "\n".join(current_lines)))
                current_key = m.group(1)
                current_lines = [line]
            else:
                if current_key:
                    current_lines.append(line)
        if current_key:
            blocks.append((current_key, "\n".join(current_lines)))
        return blocks

    specs: list[dict] = []
    for idx, (start, num, title, objective) in enumerate(headers):
        # Body is text from after this header line to start of next header (or end)
        line_end = section.index("\n", start) if "\n" in section[start:] else len(section)
        body_start = line_end + 1
        body_end = headers[idx + 1][0] if idx + 1 < len(headers) else len(section)
        body = section[body_start:body_end]

        # Split body into top-level sub-bullet blocks
        bullet_blocks = _split_top_level_bullets(body)
        blocks_by_key: dict[str, str] = {}
        for key, block in bullet_blocks:
            key_lower = key.lower().rstrip(":")
            blocks_by_key[key_lower] = block

        def _find_block(prefix: str) -> "str | None":
            for k, v in blocks_by_key.items():
                if k.lower().startswith(prefix.lower()):
                    return v
            return None

        # target_files
        target_files: list[str] = []
        tf_block = _find_block("target file")
        if tf_block:
            # First line has "Target files: ..." rest
            first_line = tf_block.split("\n")[0]
            colon_pos = first_line.find(":")
            if colon_pos >= 0:
                tf_text = first_line[colon_pos + 1:].strip()
                bt_tokens = re.findall(r"`([^`]+)`", tf_text)
                if bt_tokens:
                    target_files = [t.strip() for t in bt_tokens if t.strip()]
                else:
                    target_files = [s.strip() for s in tf_text.split(",") if s.strip()]

        # acceptance_criteria
        acceptance_criteria: list[str] = []
        ac_block = _find_block("acceptance criteri")
        if ac_block:
            for item in re.findall(r"\n\s+[-*]\s+(?:\[[ xX]\]\s*)?(.*)", ac_block):
                item = item.strip()
                if item:
                    acceptance_criteria.append(item)

        # testing
        testing = {"command": "", "expected": ""}
        test_block = _find_block("testing")
        if test_block:
            # Look for "How to verify:" line
            verify_match = re.search(r"(?i)how to verify:\s*(.*)", test_block)
            if verify_match:
                verify_text = verify_match.group(1).strip()
                cmd_bt = re.findall(r"`([^`]+)`", verify_text)
                if cmd_bt:
                    testing["command"] = cmd_bt[0].strip()
                    # expected: text after separator on the same line
                    after_cmd = re.sub(r"^`[^`]+`\s*", "", verify_text)
                    sep_m = re.match(r"(?:--|—|–|:)\s*(.*)", after_cmd)
                    if sep_m:
                        testing["expected"] = sep_m.group(1).strip()
            else:
                # Inline: look for backtick in test_block
                cmd_bt = re.findall(r"`([^`]+)`", test_block)
                if cmd_bt:
                    testing["command"] = cmd_bt[0].strip()

        # out_of_scope
        out_of_scope: list[str] = []
        oos_block = _find_block("out of scope")
        if oos_block:
            for item in re.findall(r"\n\s+[-*]\s+(?:\[[ xX]\]\s*)?(.*)", oos_block):
                item = item.strip()
                if item:
                    out_of_scope.append(item)
            if not out_of_scope:
                first_line = oos_block.split("\n")[0]
                colon_pos = first_line.find(":")
                if colon_pos >= 0:
                    remainder = first_line[colon_pos + 1:].strip()
                    if remainder:
                        out_of_scope = [s.strip() for s in remainder.split(",") if s.strip()]

        # notes
        notes = ""
        notes_block = _find_block("note")
        if notes_block:
            first_line = notes_block.split("\n")[0]
            colon_pos = first_line.find(":")
            if colon_pos >= 0:
                notes = first_line[colon_pos + 1:].strip()

        specs.append({
            "phase_n": num,
            "title": title,
            "objective": objective,
            "target_files": target_files,
            "acceptance_criteria": acceptance_criteria,
            "testing": testing,
            "out_of_scope": out_of_scope,
            "notes": notes,
        })

    return specs if specs else None


def _parse_phases_response(raw: str) -> list[dict]:
    """Parse Codex phase-generation output into normalized phase dicts.

    Returns list of dicts with keys: phase_n, title, objective, content.
    Falls back to a single generic phase on any parse error.
    """
    import re as _re

    text = raw.strip()
    if text.startswith("```"):
        text = _re.sub(r"^```(?:json)?\s*", "", text)
        text = _re.sub(r"\s*```$", "", text).strip()
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    raw_phases = data.get("phases")
    if not isinstance(raw_phases, list) or not raw_phases:
        return _single_phase_fallback()

    result = []
    for i, ph in enumerate(raw_phases, start=1):
        if not isinstance(ph, dict):
            continue
        try:
            n = int(ph.get("phase_n", i))
        except (TypeError, ValueError):
            n = i
        title = str(ph.get("title", f"Phase {n}")).strip()
        objective = str(ph.get("objective", "")).strip()
        content = str(ph.get("content", "")).strip()
        if not content:
            content = f"# Phase {n}: {title}\n\n## Objective\n{objective}\n"
        result.append({
            "phase_n": n,
            "title": title,
            "objective": objective,
            "content": content + "\n" if not content.endswith("\n") else content,
        })

    if not result:
        return _single_phase_fallback()

    # --- Normalization pass ---
    # 1. Sort by original phase_n for stable ordering
    result.sort(key=lambda ph: ph["phase_n"])
    # 2. Cap to max 5 phases
    result = result[:5]
    # 3. Re-number contiguously from 1 and fix content headings
    import re as _re2
    for new_n, ph in enumerate(result, start=1):
        old_n = ph["phase_n"]
        ph["phase_n"] = new_n
        # Update heading if it matches the old phase number
        ph["content"] = _re2.sub(
            rf"^(# Phase ){old_n}([:.])",
            rf"\g<1>{new_n}\2",
            ph["content"],
            count=1,
        )

    return result


def _load_current_phase_section(run_dir: "_Path", current_phase: int) -> str:
    """Load current phase doc and return a formatted prompt section, or empty string.

    Returns empty string when phases.json is absent (single-phase / legacy run)
    or when the phase doc file is missing -- so callers need no special-casing.
    """
    phases_json_path = run_dir / "phases.json"
    if not phases_json_path.exists():
        return ""
    try:
        phases = _json.loads(phases_json_path.read_text(encoding="utf-8"))
    except (_json.JSONDecodeError, OSError):
        return ""
    if not isinstance(phases, list):
        return ""
    entry = next((p for p in phases if isinstance(p, dict) and p.get("phase_n") == current_phase), None)
    if entry is None:
        return ""
    doc_path = run_dir / entry.get("doc_path", f"phases/phase-{current_phase:02d}.md")
    if not doc_path.exists():
        return ""
    content = doc_path.read_text(encoding="utf-8").strip()
    title = entry.get("title", f"Phase {current_phase}")
    return f'\n## Current Phase (Phase {current_phase}: "{title}")\n{content}\n'


def _render_subtasks_block(subtasks: list[dict]) -> str:
    """Render a human-readable ### Subtasks (this round) markdown block.

    Returns an empty string when subtasks is empty so the caller can skip
    injection cleanly without adding a blank section.
    """
    if not subtasks:
        return ""
    lines = [
        "### Subtasks (this round)",
        "",
        "| id | role | model | effort | description |",
        "|----|------|-------|--------|-------------|",
    ]
    for st in subtasks:
        sid = st.get("id", "?")
        role = st.get("role", "?")
        model = st.get("model", "?")
        effort = st.get("reasoning_effort", "?")
        desc = st.get("description", st.get("deliverable", "")).replace("|", "\\|")
        lines.append(f"| {sid} | {role} | {model} | {effort} | {desc} |")
    lines.append("")
    lines.append("Each subtask runs as an independent subagent. Implement only your own subtask id.")
    lines.append("Do not read or write files owned by another subtask unless they are in `shared/`.")
    lines.append("")
    return "\n".join(lines)


def _inject_subtasks_section(prompt_text: str, subtasks: list[dict]) -> str:
    """Inject the ### Subtasks block after ## Task (this round) and before ## Required Reading.

    Returns the prompt unchanged if subtasks is empty. Idempotent if the block
    is already present.
    """
    import re as _re

    if not subtasks:
        return prompt_text

    block = _render_subtasks_block(subtasks)

    # Idempotency: skip if already present.
    if "### Subtasks (this round)" in prompt_text:
        return prompt_text

    # Insert after ## Task (this round) block, before ## Required Reading.
    # We look for the ## Task heading and then find the next ## heading after it.
    task_re = _re.compile(
        r"(^##\s+Task\b[^\n]*\n.*?)(?=^##\s+|\Z)",
        _re.MULTILINE | _re.DOTALL,
    )
    m = task_re.search(prompt_text)
    if m:
        end = m.end()
        return prompt_text[:end] + "\n" + block + "\n" + prompt_text[end:]

    # Fallback: append at end.
    return prompt_text + "\n" + block




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


def _strip_routing_metadata(text: str) -> str:
    """Remove ## Worker Model sections from goal text before storage.

    Users sometimes paste routing hints (## Worker Model, Scope:, Reasoning Effort:)
    into the goal. These are not parsed or enforced — routing is decided by plan-round
    JSON — so strip them to keep goal.md clean.
    """
    import re as _re
    return _re.sub(
        r"^##\s+Worker\s+Model\s*\n.*?(?=^##\s+|\Z)",
        "",
        text,
        flags=_re.MULTILINE | _re.DOTALL,
    ).strip()


@register("init-run")
def _cmd_init_run(args) -> int:
    repo = _Path(args.repo).resolve()
    run_id = _unique_run_id(repo, args.slug)
    run_dir = _run_dir(repo, run_id)
    plan_file = getattr(args, "plan_file", None)
    if plan_file is not None:
        src = _Path(plan_file)
        if not src.exists():
            print(f"plan-file not found: {plan_file}", file=sys.stderr)
            return 1
    (run_dir / "rounds").mkdir(parents=True, exist_ok=True)
    (run_dir / "shared").mkdir(parents=True, exist_ok=True)
    goal = _strip_routing_metadata(args.goal)
    (run_dir / "goal.md").write_text(goal + "\n", encoding="utf-8")
    (run_dir / "memo.md").write_text("# Round Memos\n\n", encoding="utf-8")
    if plan_file is not None:
        _shutil.copy2(src, run_dir / "plan.md")
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
    prompt_text = _Path(args.prompt_file).read_text(encoding="utf-8")
    (rd / "claude-prompt.md").write_text(prompt_text, encoding="utf-8")
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


def _bounded_memo(memo_text: str, max_rounds: int = 3) -> str:
    """Return a sliding window of the last ``max_rounds`` round blocks from memo.

    Each round block begins with a ``## Round N`` heading. If fewer than
    ``max_rounds`` blocks exist, all are returned. The on-disk memo.md is
    unchanged; this function only slices the text for the Codex input.
    """
    import re as _re
    if not memo_text.strip():
        return memo_text
    # Find all start positions of "## Round N" headings.
    boundaries = [m.start() for m in _re.finditer(r"^##\s+Round\s+\d+", memo_text, _re.MULTILINE)]
    if not boundaries:
        return memo_text
    if len(boundaries) <= max_rounds:
        return memo_text
    # Return from the (len - max_rounds)-th boundary to the end.
    start = boundaries[len(boundaries) - max_rounds]
    return memo_text[:boundaries[0]] + memo_text[start:]


def _count_consecutive_needs_changes(rs: "RunState") -> int:
    """Count consecutive NEEDS_CHANGES decisions at the tail of rs.rounds.

    Scans rounds in reverse, skipping None (in-progress) decisions.
    Stops at the first PHASE_COMPLETE or APPROVE decision (phase boundary / run reset).
    Returns 0 when there is no history or no consecutive NEEDS_CHANGES tail.
    """
    count = 0
    for entry in reversed(rs.rounds):
        if entry.decision is None:
            continue
        if entry.decision == "NEEDS_CHANGES":
            count += 1
        else:
            break
    return count


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


def _parse_phase_target_files(run_dir: "_Path", current_phase: int) -> "list[str]":
    """Parse ## Target Files from the current phase doc.

    Returns a de-duped, order-preserved list of repo-relative path strings.
    On any IO/parse error returns [].
    """
    import re as _re
    phase_doc_path = run_dir / "phases" / f"phase-{current_phase:02d}.md"
    try:
        content = phase_doc_path.read_text(encoding="utf-8")
    except OSError:
        return []

    # Find the ## Target Files section: between that heading and the next ## heading.
    m = _re.search(
        r"^##\s+Target Files\s*\n(.*?)(?=^##\s+|\Z)",
        content,
        _re.MULTILINE | _re.DOTALL,
    )
    if not m:
        return []

    section_text = m.group(1)
    seen: set[str] = set()
    result: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        # Strip leading "- "
        token_text = stripped[1:].strip()
        if not token_text or token_text.lower() == "(none)":
            continue
        # Take the first whitespace-or-( delimited token
        token = _re.split(r"[\s(]", token_text)[0].strip()
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def _validate_round_plan_quality(
    round_plan: dict,
    repo: "_Path",
    phase_target_files: "list[str] | None" = None,
) -> "list[str]":
    """Validate round plan for concrete file-backed bullets and runnable acceptance criteria.

    Returns a list of error strings. Empty list means quality OK.
    """
    import re as _re

    _FILE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".toml", ".json", ".go", ".rs"}
    _RUNNABLE_PATTERNS = [
        "pytest ", "python -m ", "python ", "grep ", "npm ", "node ",
        "go test", "cargo ", "rg ",
    ]

    if phase_target_files is None:
        phase_target_files = []

    errors: list[str] = []

    # Validate execution_plan_bullets
    bullets = round_plan.get("execution_plan_bullets") or []
    for idx, bullet in enumerate(bullets):
        if not isinstance(bullet, str):
            continue
        bullet_text = bullet.strip()
        # Extract candidate path tokens: whitespace-delimited tokens with / AND a file extension
        # Strip trailing punctuation and :NN line suffixes
        tokens_raw = bullet_text.split()
        candidate_paths: list[str] = []
        for token in tokens_raw:
            # Strip trailing punctuation (but not colons here — handled below)
            token = _re.sub(r"[.,;)\]]+$", "", token)
            # Extract the path part before any colon suffix (e.g. cli.py:354 or cli.py:_func)
            # Split on ':' and take the first component as the candidate path.
            colon_idx = token.find(":")
            path_part = token[:colon_idx] if colon_idx != -1 else token
            # Strip any remaining trailing punctuation from the path part
            path_part = path_part.rstrip(".,;:)]")
            # Check it has a / and a file extension
            if "/" not in path_part:
                continue
            suffix = _Path(path_part).suffix if path_part else ""
            if suffix not in _FILE_EXTS:
                continue
            # Reject absolute paths
            if path_part.startswith("/") or path_part.startswith("\\"):
                continue
            candidate_paths.append(path_part)

        if not candidate_paths:
            truncated = bullet_text[:80]
            errors.append(
                f"bullet {idx}: missing concrete repo-resident path token: {truncated!r}"
            )
            continue

        # Check if at least one candidate matches a target file or exists in repo
        found_valid = False
        for cpath in candidate_paths:
            if cpath in phase_target_files:
                found_valid = True
                break
            if (repo / cpath).exists():
                found_valid = True
                break

        if not found_valid:
            truncated = bullet_text[:80]
            errors.append(
                f"bullet {idx}: missing concrete repo-resident path token: {truncated!r}"
            )

    # Validate acceptance_criteria
    criteria = round_plan.get("acceptance_criteria") or []
    has_runnable = False
    for crit in criteria:
        if not isinstance(crit, str):
            continue
        if any(pat in crit for pat in _RUNNABLE_PATTERNS):
            has_runnable = True
            break
        if crit.strip().startswith("$ "):
            has_runnable = True
            break

    if not has_runnable:
        errors.append("acceptance_criteria: no runnable command pattern found")

    return errors


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


def _scan_verification_outcomes(progress_path: "_Path") -> "list[dict]":
    """B3: Scan rounds/NN/progress.md for verification outcome lines.

    Recognises lines of the form:
      [done] <subtask_id> verification: pass[<optional note>]
      [done] <subtask_id> verification: fail[<optional note>]

    Returns a list of dicts ``{subtask_id, status, note}``. If the file is
    absent or contains no matching lines, returns an empty list.
    """
    import re as _re

    if not progress_path.exists():
        return []
    text = progress_path.read_text(encoding="utf-8")
    outcomes: list[dict] = []
    pattern = _re.compile(
        r"^\[done\]\s+(\S+)\s+verification:\s*(pass|fail)(.*)?$",
        _re.IGNORECASE | _re.MULTILINE,
    )
    for m in pattern.finditer(text):
        subtask_id = m.group(1).strip()
        status = m.group(2).lower()
        note = (m.group(3) or "").strip().lstrip("-—").strip()
        outcomes.append({"subtask_id": subtask_id, "status": status, "note": note})
    return outcomes


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
        memo_tail = "\n".join(memo_path.read_text(encoding="utf-8").splitlines()[-30:])
    _emit({
        "state": _json.loads((run_dir / "state.json").read_text(encoding="utf-8")),
        "memo_tail": memo_tail,
    })
    return 0


@register("finalize")
def _cmd_finalize(args) -> int:
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    rs.status = "completed"
    rs.save(run_dir / "state.json")
    memo = (
        (run_dir / "memo.md").read_text(encoding="utf-8")
        if (run_dir / "memo.md").exists()
        else ""
    )
    (run_dir / "final-report.md").write_text(
        f"# Final Report — {rs.run_id}\n\nStatus: {rs.status}\n\n## Round Memos\n\n{memo}\n",
        encoding="utf-8",
    )
    plan_file = repo / ".agent-loop-plan.md"
    plan_file_cleaned = plan_file.exists()
    if plan_file_cleaned:
        plan_file.unlink()
    _emit({"final_report": str(run_dir / "final-report.md"), "status": rs.status, "plan_file_cleaned": plan_file_cleaned})
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


def _parse_lines_spec(spec: str, total: int) -> tuple[int, int]:
    """Parse an ``--lines`` argument into an inclusive 1-indexed (start, end).

    Accepted forms:
      - ``N``    -> first N lines           -> (1, N)
      - ``N-``   -> from line N to the end  -> (N, total)
      - ``A-B``  -> A through B inclusive   -> (A, B)

    ``total`` is the number of lines available so ``N-`` and out-of-range
    requests clamp gracefully instead of silently emitting nothing. Raises
    ``ValueError`` with a human-readable message on malformed input.
    """
    raw = (spec or "").strip()
    if not raw:
        raise ValueError("--lines must not be empty")
    if "-" in raw:
        left, _, right = raw.partition("-")
        left = left.strip()
        right = right.strip()
        if not left:
            raise ValueError(
                f"--lines {spec!r}: missing start. Use 'N', 'N-', or 'A-B'."
            )
        try:
            a = int(left)
        except ValueError as e:
            raise ValueError(
                f"--lines {spec!r}: start is not an integer. Use 'N', 'N-', or 'A-B'."
            ) from e
        if right == "":
            b = total
        else:
            try:
                b = int(right)
            except ValueError as e:
                raise ValueError(
                    f"--lines {spec!r}: end is not an integer. Use 'N', 'N-', or 'A-B'."
                ) from e
    else:
        try:
            n = int(raw)
        except ValueError as e:
            raise ValueError(
                f"--lines {spec!r}: not an integer. Use 'N', 'N-', or 'A-B'."
            ) from e
        a, b = 1, n
    if a < 1:
        a = 1
    if b < a:
        raise ValueError(
            f"--lines {spec!r}: end ({b}) is before start ({a})."
        )
    return a, b


@register("inspect")
def _cmd_inspect(args) -> int:
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rd = run_dir / "rounds" / f"{args.round:02d}"
    target = (rd / args.file).resolve()
    if not target.is_relative_to(run_dir.resolve()):
        _emit({"error": f"refusing to inspect outside run directory: {args.file}"})
        return 1
    if not target.exists():
        _emit({"error": f"not found: {target}"})
        return 1
    text = target.read_text(encoding="utf-8")
    if args.lines:
        lines = text.splitlines()
        try:
            a, b = _parse_lines_spec(args.lines, total=len(lines))
        except ValueError as e:
            _emit({"error": str(e)})
            return 1
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


if __name__ == "__main__":
    sys.exit(main())
