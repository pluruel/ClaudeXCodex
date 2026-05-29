"""Phase parsing and assembly helpers."""
from __future__ import annotations

import json
import re
from pathlib import Path


def _single_phase_fallback() -> list[dict]:
    return [{
        "phase_n": 1,
        "title": "Implementation",
        "objective": "Complete the goal.",
        "content": "# Phase 1: Implementation\n\n## Objective\nComplete the goal.\n",
    }]


def _validate_phase_specs(specs: list[dict], repo: Path) -> list[str]:
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
    specs: list[dict],
    repo: Path,
    scout_signal: dict,
    call_codex,
) -> tuple[list[dict], list[str]]:
    """Repair missing/invalid target_files paths in phase specs using one Codex call.

    Collects paths that don't exist in the repo (or have leading / or ..) and
    asks Codex to map them to real paths.  Returns updated specs and a log of
    repairs/drops.  Makes at most ONE Codex call.  On CodexCallError, drops
    invalid paths silently.
    """
    import json as _json_r
    import re as _re_r
    from agent_loop.codex_client import CodexCallError as _CodexCallError

    def _is_valid(p: str, repo: Path) -> bool:
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
        raw_tf = spec.get("target_files")
        _tf_list = raw_tf if isinstance(raw_tf, list) else []
        for p in _tf_list:
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
        raw_tf2 = spec.get("target_files")
        tf = raw_tf2 if isinstance(raw_tf2, list) else []
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
    specs: list[dict],
    run_dir: Path,
    repo: Path,
) -> list[dict]:
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


def _parse_plan_phases(plan_text: str) -> list[dict] | None:
    """Parse the ## Phases section of a plan.md into a list of phase spec dicts.

    Each dict has keys: phase_n, title, objective, target_files,
    acceptance_criteria, testing, out_of_scope, notes.

    Returns None when there is no ## Phases section or zero phases are parsed.
    """
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

    def _split_top_level_bullets(body: str) -> list[tuple[str, str]]:
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

        def _find_block(prefix: str) -> str | None:
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
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
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
    for new_n, ph in enumerate(result, start=1):
        old_n = ph["phase_n"]
        ph["phase_n"] = new_n
        # Update heading if it matches the old phase number
        ph["content"] = re.sub(
            rf"^(# Phase ){old_n}([:.])",
            rf"\g<1>{new_n}\2",
            ph["content"],
            count=1,
        )

    return result


def _load_current_phase_section(run_dir: Path, current_phase: int) -> str:
    """Load current phase doc and return a formatted prompt section, or empty string.

    Returns empty string when phases.json is absent (single-phase / legacy run)
    or when the phase doc file is missing -- so callers need no special-casing.
    """
    phases_json_path = run_dir / "phases.json"
    if not phases_json_path.exists():
        return ""
    try:
        phases = json.loads(phases_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
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
