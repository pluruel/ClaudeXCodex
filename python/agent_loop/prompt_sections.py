"""Prompt section rendering helpers."""
from __future__ import annotations

import re


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
    if not subtasks:
        return prompt_text

    block = _render_subtasks_block(subtasks)

    # Idempotency: skip if already present.
    if "### Subtasks (this round)" in prompt_text:
        return prompt_text

    # Insert after ## Task (this round) block, before ## Required Reading.
    # We look for the ## Task heading and then find the next ## heading after it.
    task_re = re.compile(
        r"(^##\s+Task\b[^\n]*\n.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = task_re.search(prompt_text)
    if m:
        end = m.end()
        return prompt_text[:end] + "\n" + block + "\n" + prompt_text[end:]

    # Fallback: append at end.
    return prompt_text + "\n" + block
