"""Pure render function for progress view output."""
from __future__ import annotations

from agent_loop.progress_parser import ProgressSnapshot

# Unicode glyphs
_U_DONE = "✓"
_U_ACTIVE = "▶"
_U_PENDING = "·"
_U_TREE_MID = "├─"
_U_TREE_END = "└─"

# ASCII glyphs
_A_DONE = "[x]"
_A_ACTIVE = "[>]"
_A_PENDING = "[ ]"
_A_TREE_MID = "|-"
_A_TREE_END = "+-"


def render_progress(
    state: dict,
    phases: list[dict],
    progress: ProgressSnapshot,
    *,
    ascii: bool = False,
) -> str:
    """Render a compact, scannable plain-text view of run progress.

    Parameters
    ----------
    state:
        RunState-compatible dict (shape from RunState.save / state.json).
    phases:
        List of phase dicts from phases.json (keys: phase_n, title, objective, doc_path).
    progress:
        ProgressSnapshot for the active round.
    ascii:
        If True, use ASCII-only glyphs; otherwise use Unicode box-drawing marks.
    """
    g_done = _A_DONE if ascii else _U_DONE
    g_active = _A_ACTIVE if ascii else _U_ACTIVE
    g_pending = _A_PENDING if ascii else _U_PENDING
    g_mid = _A_TREE_MID if ascii else _U_TREE_MID
    g_end = _A_TREE_END if ascii else _U_TREE_END

    run_id = state.get("run_id", "unknown")
    status = state.get("status", "unknown")
    current_phase = state.get("current_phase", 1)
    total_phases = state.get("total_phases", 1)
    current_round = state.get("current_round", 0)

    lines: list[str] = []

    # Header
    lines.append(
        f"Run: {run_id}  |  status: {status}  |  phase: {current_phase}/{total_phases}"
        + (f"  |  round: {current_round}" if current_round else "")
    )
    lines.append("")

    # Phase tree
    if phases:
        lines.append("Phases:")
        for i, phase in enumerate(phases):
            phase_n = phase.get("phase_n", i + 1)
            title = phase.get("title", f"Phase {phase_n}")
            is_last = i == len(phases) - 1
            connector = g_end if is_last else g_mid

            # Determine glyph
            if status == "completed" and phase_n <= current_phase:
                glyph = g_done
            elif phase_n < current_phase:
                glyph = g_done
            elif phase_n == current_phase:
                if status == "completed":
                    glyph = g_done
                else:
                    glyph = g_active
            else:
                glyph = g_pending

            lines.append(f"  {connector} {glyph} {title}")
        lines.append("")

    # Completed run: the per-round progress log is stale/irrelevant once the
    # run is done (and compact mode may have reaped it), so show a clean
    # completion summary instead of a misleading "done: 0 (no progress recorded)".
    # Keep this line glyph-free so the phase tree remains the only source of
    # done markers.
    if status == "completed":
        lines.append(f"All {total_phases} phase(s) complete.")
        return "\n".join(lines)

    # Active round progress
    lines.append(f"Round {current_round} progress:")
    lines.append(f"  done: {progress.done_count}")
    if progress.doing:
        lines.append(f"  {g_active} doing: {progress.doing}")
    if progress.planned:
        for item in progress.planned:
            lines.append(f"  {g_pending} planned: {item}")
    if not progress.doing and not progress.planned and progress.done_count == 0:
        lines.append("  (no progress recorded)")

    return "\n".join(lines)
