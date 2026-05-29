"""Round-plan parsing and quality-gate helpers extracted from cli.py."""
from __future__ import annotations

import json as _json
from pathlib import Path as _Path


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
        # Wrapper/punctuation chars that surround a path token in prose or
        # markdown bullets (backticks, quotes, parens, brackets, trailing
        # punctuation). Stripped from both ends so a path written as
        # `pkg/mod.py:func`, is recognized.
        _wrap = "`'\"()[]{}.,;:"
        for token in tokens_raw:
            token = token.strip(_wrap)
            # Extract the path part before any colon suffix (e.g. cli.py:354 or cli.py:_func)
            # Split on ':' and take the first component as the candidate path.
            colon_idx = token.find(":")
            path_part = token[:colon_idx] if colon_idx != -1 else token
            # Strip any remaining wrapper/punctuation from the path part
            path_part = path_part.strip(_wrap)
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
