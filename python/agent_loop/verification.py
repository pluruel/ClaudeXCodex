"""Verification helpers extracted from cli.py."""
from __future__ import annotations

import re as _re
from pathlib import Path as _Path


def _scan_verification_outcomes(progress_path: "_Path") -> "list[dict]":
    """B3: Scan rounds/NN/progress.md for verification outcome lines.

    Recognises lines of the form:
      [done] <subtask_id> verification: pass[<optional note>]
      [done] <subtask_id> verification: fail[<optional note>]

    Returns a list of dicts ``{subtask_id, status, note}``. If the file is
    absent or contains no matching lines, returns an empty list.
    """
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


def _count_consecutive_needs_changes(rs: "object") -> int:
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


def _bounded_memo(memo_text: str, max_rounds: int = 3) -> str:
    """Return a sliding window of the last ``max_rounds`` round blocks from memo.

    Each round block begins with a ``## Round N`` heading. If fewer than
    ``max_rounds`` blocks exist, all are returned. The on-disk memo.md is
    unchanged; this function only slices the text for the Codex input.
    """
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
