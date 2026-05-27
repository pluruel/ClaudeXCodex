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

    # Second Codex call: generate phase docs.
    phases_prompt = (
        "You are generating a phased implementation plan for a software development goal.\n\n"
        "Analyze the goal complexity and decide how many phases (1-5):\n"
        "- 1 phase: simple goal, achievable in 3-7 rounds total\n"
        "- 2-3 phases: moderate complexity with distinct milestones\n"
        "- 4-5 phases: large goal with multiple independent subsystems\n\n"
        'Output ONLY JSON (no prose, no fenced block):\n'
        '{\n'
        '  "phases": [\n'
        '    {\n'
        '      "phase_n": 1,\n'
        '      "title": "<short phase title>",\n'
        '      "objective": "<one sentence: what this phase achieves>",\n'
        '      "content": "<full markdown for this phase doc -- include: objective, key context, constraints, expected completion criteria, anticipated files/areas. Under 400 words.>"\n'
        '    }\n'
        '  ]\n'
        '}\n\n'
        f"## Goal\n{goal}\n\n"
        f"## Plan (tasks overview)\n{plan_text}\n"
    )
    try:
        phases_res = call_codex(phases_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1

    phases = _parse_phases_response(phases_res.final_text)

    # Write phase docs and index.
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
    rs.total_phases = len(phases)
    rs.current_phase = 1
    rs.save(run_dir / "state.json")

    _emit({
        "plan_path": str(plan_path),
        "plan_source": plan_source,
        "phases": phases_index,
        "summary": f"{len(phases)} phase(s) drafted",
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
        "summary": f"round {next_n} prompt drafted",
    })
    return 0


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


if __name__ == "__main__":
    sys.exit(main())
