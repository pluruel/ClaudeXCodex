# Phased Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-05-24
**Status:** Implementation-ready (spec approved, ASCII-safe)

**Goal:** Add a phase layer between the global goal and per-round tasks so Codex can pre-generate strategic phase docs, inject them as context, and autonomously transition between phases.

**Architecture:** `plan-init` makes a second Codex call to generate `phases.json` + `phases/phase-N.md` docs. `plan-round` and `review-round` load the current phase doc and inject it into every Codex prompt. `review-round` gains `PHASE_COMPLETE` as a decision value (removing `STOP_FOR_USER`). New `advance-phase` CLI subcommand asks Codex to update the next phase doc and increments `current_phase` in `state.json`. `resume.py` detects interrupted phase transitions via a `phase_advance_pending` flag. `SKILL.md` and reference docs are updated to reflect the new flow.

**Tech Stack:** Python 3.11+, `pytest` (run as `pytest tests/` from `python/` dir), subprocess-based CLI tests using `python -m agent_loop`, `codex_stub` / `tmp_repo` fixtures in `conftest.py`.

---

## Cross-References

| Document | Location | Relationship |
|---|---|---|
| Design spec | `docs/superpowers/specs/2026-05-24-phased-planning-design.md` | Authoritative design; this plan implements it |
| Supervisor skill | `skills/agent-loop/SKILL.md` | Updated in Task 7; supervisor round loop instructions |
| Safety rules | `skills/agent-loop/safety-rules.md` | Updated in Task 7; decision matrix |
| Resume doc | `skills/agent-loop/resume-run.md` | Updated in Task 7; resume action table |
| RunState | `python/agent_loop/run_state.py` | Foundation; gains phase fields (Task 1) |
| CLI | `python/agent_loop/cli.py` | Most code changes (Tasks 2--5) |
| Resume logic | `python/agent_loop/resume.py` | Gains `advance_phase` action (Task 6) |

---

## Purpose

The current agent-loop breaks large goals into 3--7 flat tasks in `plan.md`. For long-running goals this creates context drift: Codex and workers lose the strategic thread after several rounds because the memo window is bounded to 3 rounds. There is no persistent mid-level structure between the immutable goal and the per-round task.

The phased planning feature adds a **strategic phase layer**:

- Codex pre-generates phase documents at run start (1--5 phases, decided by Codex based on goal complexity)
- Each phase has a markdown document holding the phase objective, key context, constraints, completion criteria, and anticipated file areas
- Phase documents are injected into every Codex prompt (plan-round and review-round) so Codex always knows its mid-level objective
- Phase documents are updated at phase boundaries to reflect actual results before the next phase begins
- The global `goal.md` remains immutable -- the north star for the entire run

This is transparent to worker subagents: workers receive only their subtask description, not phase docs.

---

## Workflow Phases

### Artifact Structure

```
.agent-loop/runs/<run_id>/
  goal.md            # immutable -- unchanged
  plan.md            # Codex strategic notes -- written by plan-init (first Codex call)
  phases.json        # NEW: phase index [{phase_n, title, objective, doc_path}]
  phases/
    phase-01.md      # NEW: Codex-only context doc for phase 1
    phase-02.md      # updated by advance-phase before phase 2 starts
    ...
  state.json         # gains current_phase, total_phases, phase_advance_pending
  memo.md            # unchanged
  shared/            # unchanged
  rounds/            # unchanged
```

### Phase Hierarchy

```
Goal (immutable)
+-- Phase 1  <-- phase-01.md (Codex context)
    +-- Round 1  ->  NEEDS_CHANGES
    +-- Round 2  ->  NEEDS_CHANGES
    +-- Round 3  ->  PHASE_COMPLETE
+-- Phase 2  <-- phase-02.md (updated by advance-phase)
    +-- Round 4  ->  NEEDS_CHANGES
    +-- Round 5  ->  PHASE_COMPLETE
+-- Phase 3  <-- phase-03.md (updated by advance-phase)
    +-- Round 6  ->  NEEDS_CHANGES
    +-- Round 7  ->  APPROVE
```

Round numbers are continuous across all phases. Phase transitions are transparent to the round loop -- the supervisor just calls `advance-phase` between rounds.

### Decision Values

| Decision | Meaning | Supervisor action |
|---|---|---|
| `NEEDS_CHANGES` | Round incomplete | Next round, same phase |
| `PHASE_COMPLETE` | Phase objective met | Call `advance-phase`; if `is_last_phase` finalize; else next round |
| `APPROVE` | Entire goal achieved | `finalize` |

`STOP_FOR_USER` is removed entirely. Codex drives all decisions autonomously. Safety flags (if any) are passed to Codex in the review payload; Codex decides the appropriate decision.

### Codex Prompt Injection

`plan-round` and `review-round` inject the current phase doc between `## Goal` and `## Plan`:

```
## Goal
<goal.md content>

## Current Phase (Phase 2: "Data layer")
<phase-02.md full content>

## Plan
<plan.md content>

## Memo So Far
<bounded memo>
```

Workers do not receive this section -- only the subtask description is passed to them.

---

## Handoff Rules

### Phase Transition Protocol

Phase transitions follow a strict two-step handoff:

1. **`review-round` emits `PHASE_COMPLETE`** and sets `phase_advance_pending = True` in `state.json`.
2. **Supervisor immediately calls `advance-phase`:**
   - Loads `current_phase` and `total_phases` from `state.json`
   - If `current_phase >= total_phases`: clears `phase_advance_pending`, emits `{"is_last_phase": true}` -- supervisor calls `finalize`
   - Otherwise: calls Codex to update the next phase doc with context from `shared/knowledge.md`, `shared/decisions.md`, and the last `codex-review.md`; increments `current_phase`; clears `phase_advance_pending`
3. **Supervisor announces:** `Phase <N> complete -> advancing to Phase <N+1>: "<title from phases.json>"`
4. **Loop back** to round-loop step 1 (next round in new phase context)

### Resume Safety

`resume.py` checks `phase_advance_pending` before all other state checks. If `True`, it returns action `advance_phase` -- so an interrupted phase transition is safely resumed by re-calling `advance-phase`. No data is lost because:
- `phase_advance_pending` persists in `state.json`
- `current_phase` has not yet been incremented (advance-phase is idempotent at resume)
- Phase docs are on disk and survive process restart

### Backward Compatibility

Runs without `phases.json` (pre-feature or single-phase): `_load_current_phase_section` returns an empty string, so no injection occurs. `RunState.load()` sets defaults (`current_phase=1`, `total_phases=1`, `phase_advance_pending=False`) for old state files that lack these fields.

### Target Audiences

- **Codex** receives phase docs via prompt injection in `plan-round` and `review-round`. Codex is the sole decision-maker for PHASE_COMPLETE transitions.
- **The supervisor** reads JSON output from CLI subcommands and orchestrates the round loop. `SKILL.md` is the supervisor's authoritative reference.
- **Workers** (Task tool subagents) do NOT receive phase documents -- they stay focused on their subtask only.

---

## Examples

### Example 1: 3-Phase Run (Complex Goal)

```
plan-init
  -> first Codex call: writes plan.md (3-7 tasks)
  -> second Codex call: generates 3 phases
  -> writes phases.json + phases/phase-01.md, phase-02.md, phase-03.md
  -> state: current_phase=1, total_phases=3

Phase 1 context active (phase-01.md injected each round)
  Round 1: plan-round -> dispatch -> review-round -> NEEDS_CHANGES
  Round 2: plan-round -> dispatch -> review-round -> NEEDS_CHANGES
  Round 3: plan-round -> dispatch -> review-round -> PHASE_COMPLETE
    -> state: phase_advance_pending=True
    -> advance-phase: Codex updates phase-02.md with actual results
    -> state: current_phase=2, phase_advance_pending=False
    -> announce: "Phase 1 complete -> advancing to Phase 2: 'Core Logic'"

Phase 2 context active (phase-02.md injected each round)
  Round 4: plan-round -> dispatch -> review-round -> NEEDS_CHANGES
  Round 5: plan-round -> dispatch -> review-round -> PHASE_COMPLETE
    -> advance-phase: Codex updates phase-03.md
    -> state: current_phase=3, phase_advance_pending=False
    -> announce: "Phase 2 complete -> advancing to Phase 3: 'Integration'"

Phase 3 context active (phase-03.md injected each round)
  Round 6: plan-round -> dispatch -> review-round -> NEEDS_CHANGES
  Round 7: plan-round -> dispatch -> review-round -> APPROVE
    -> finalize -> final-report.md written
```

### Example 2: Single-Phase Run (Simple Goal)

```
plan-init
  -> Codex decides 1 phase is sufficient
  -> writes phases.json (1 entry) + phases/phase-01.md
  -> state: current_phase=1, total_phases=1

Phase 1 context active
  Round 1: plan-round -> dispatch -> review-round -> NEEDS_CHANGES
  Round 2: plan-round -> dispatch -> review-round -> APPROVE
    -> finalize (no advance-phase needed)
```

### Example 3: Resume After Interrupted Phase Transition

```
Round 3 completes with PHASE_COMPLETE
  -> state: phase_advance_pending=True, current_phase=1
  -> process crashes before advance-phase runs

On resume:
  -> resume.py detects phase_advance_pending=True
  -> returns action: advance_phase
  -> supervisor calls advance-phase --run <run_id>
  -> advance-phase runs normally: updates phase-02.md, current_phase=2, phase_advance_pending=False
  -> round loop continues from round 4
```

### Example 4: plan-init with Malformed Phases Response

```
Codex returns invalid JSON for phases generation
  -> _parse_phases_response falls back to 1-phase default
  -> writes phases/phase-01.md with generic content
  -> state: current_phase=1, total_phases=1
  -> run proceeds as single-phase (graceful degradation)
```

---

## File Map

| File | Change |
|---|---|
| `python/agent_loop/run_state.py` | `Decision` type -> add `PHASE_COMPLETE`, remove `STOP_FOR_USER`; add `current_phase`, `total_phases`, `phase_advance_pending` fields; backward-compat `load()`; `advance_current_phase()` method |
| `python/agent_loop/cli.py` | New helpers `_parse_phases_response`, `_load_current_phase_section`; extend `_cmd_plan_init`; extend `_cmd_plan_round`; extend `_cmd_review_round`; new `_cmd_advance_phase` + parser entry |
| `python/agent_loop/resume.py` | Add `advance_phase` to `Action` literal; add `phase_advance_pending` check in `determine_resume_action` |
| `skills/agent-loop/SKILL.md` | Update round-loop heading, plan-init output description, step-6 decision list, step-7 PHASE_COMPLETE branch; remove STOP_FOR_USER |
| `skills/agent-loop/safety-rules.md` | Remove STOP_FOR_USER rows; note safety_flags are passed to Codex but no longer force a specific decision |
| `skills/agent-loop/resume-run.md` | Add `advance_phase` action row; update `branch_decision` description |
| `python/tests/test_run_state_phase.py` | New -- unit tests for new RunState fields |
| `python/tests/test_plan_init_phases.py` | New -- CLI tests for phase generation in plan-init |
| `python/tests/test_phase_injection.py` | New -- unit tests for `_load_current_phase_section` + CLI tests verifying injection |
| `python/tests/test_cli_advance_phase.py` | New -- CLI tests for advance-phase subcommand |
| `python/tests/test_resume.py` | Add `advance_phase` action test |
| `python/tests/test_cli_plan_round.py` | Update line 742: change `STOP_FOR_USER` stub to `NEEDS_CHANGES` |

---

### Task 1: RunState -- Decision type, phase fields, advance_current_phase

**Files:**
- Modify: `python/agent_loop/run_state.py`
- Create: `python/tests/test_run_state_phase.py`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_run_state_phase.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_loop.run_state import RunState


def test_run_state_has_current_phase_default():
    rs = RunState.new(run_id="x", goal_path="g", plan_path="p")
    assert rs.current_phase == 1


def test_run_state_has_total_phases_default():
    rs = RunState.new(run_id="x", goal_path="g", plan_path="p")
    assert rs.total_phases == 1


def test_run_state_has_phase_advance_pending_default():
    rs = RunState.new(run_id="x", goal_path="g", plan_path="p")
    assert rs.phase_advance_pending is False


def test_run_state_advance_current_phase_increments(tmp_path: Path):
    rs = RunState.new(run_id="x", goal_path="g", plan_path="p")
    rs.total_phases = 3
    rs.advance_current_phase()
    assert rs.current_phase == 2
    assert rs.phase_advance_pending is False


def test_run_state_advance_current_phase_clamps_at_total(tmp_path: Path):
    rs = RunState.new(run_id="x", goal_path="g", plan_path="p")
    rs.total_phases = 2
    rs.current_phase = 2
    rs.advance_current_phase()
    assert rs.current_phase == 2


def test_run_state_advance_current_phase_clears_pending(tmp_path: Path):
    rs = RunState.new(run_id="x", goal_path="g", plan_path="p")
    rs.total_phases = 3
    rs.phase_advance_pending = True
    rs.advance_current_phase()
    assert rs.phase_advance_pending is False


def test_run_state_serialize_deserialize_phase_fields(tmp_path: Path):
    rs = RunState.new(run_id="x", goal_path="g", plan_path="p")
    rs.total_phases = 3
    rs.current_phase = 2
    rs.phase_advance_pending = True
    path = tmp_path / "state.json"
    rs.save(path)
    rs2 = RunState.load(path)
    assert rs2.total_phases == 3
    assert rs2.current_phase == 2
    assert rs2.phase_advance_pending is True


def test_run_state_load_missing_phase_fields_defaults(tmp_path: Path):
    """Old state.json without phase fields loads with defaults (backward compat)."""
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "run_id": "x", "goal_path": "g", "plan_path": "p",
        "current_round": 0, "status": "in_progress",
        "rounds": [], "safety_flags": [], "last_heartbeat": None,
    }), encoding="utf-8")
    rs = RunState.load(path)
    assert rs.current_phase == 1
    assert rs.total_phases == 1
    assert rs.phase_advance_pending is False


def test_decision_literal_contains_phase_complete():
    from agent_loop.run_state import Decision
    import typing
    args = typing.get_args(Decision)
    assert "PHASE_COMPLETE" in args
    assert "STOP_FOR_USER" not in args
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_run_state_phase.py -v
```

Expected: all fail (fields don't exist yet).

- [ ] **Step 3: Implement changes in run_state.py**

Replace `Decision` line and `RunState` dataclass. The complete updated `run_state.py`:

```python
"""Run state persistence and phase machine."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

Phase = Literal[
    "planned",
    "init",
    "dispatched",
    "claude_completed",
    "reviewed",
    "memo_written",
    "completed",
]

PHASES: list[Phase] = [
    "planned",
    "init",
    "dispatched",
    "claude_completed",
    "reviewed",
    "memo_written",
    "completed",
]


def next_phase(current: Phase) -> Phase:
    if current == "completed":
        return "completed"
    idx = PHASES.index(current)
    return PHASES[idx + 1]


Decision = Literal["APPROVE", "NEEDS_CHANGES", "PHASE_COMPLETE"]


@dataclass
class RoundEntry:
    n: int
    phase: Phase = "planned"
    decision: Optional[Decision] = None
    memo_lines: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


@dataclass
class RunState:
    run_id: str
    goal_path: str
    plan_path: str
    current_round: int = 0
    current_phase: int = 1
    total_phases: int = 1
    phase_advance_pending: bool = False
    status: Literal["in_progress", "completed", "aborted"] = "in_progress"
    rounds: list[RoundEntry] = field(default_factory=list)
    safety_flags: list[str] = field(default_factory=list)
    last_heartbeat: Optional[str] = None

    @classmethod
    def new(cls, *, run_id: str, goal_path: str, plan_path: str) -> "RunState":
        return cls(run_id=run_id, goal_path=goal_path, plan_path=plan_path)

    @classmethod
    def load(cls, path: Path) -> "RunState":
        raw = json.loads(path.read_text(encoding="utf-8"))
        rounds = [RoundEntry(**r) for r in raw.pop("rounds", [])]
        raw.setdefault("current_phase", 1)
        raw.setdefault("total_phases", 1)
        raw.setdefault("phase_advance_pending", False)
        return cls(rounds=rounds, **raw)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def start_round(self, *, n: int, started_at: str) -> None:
        self.current_round = n
        self.rounds.append(RoundEntry(n=n, phase="init", started_at=started_at))

    def _round(self, n: int) -> RoundEntry:
        for r in self.rounds:
            if r.n == n:
                return r
        raise KeyError(f"round {n} not in state")

    def advance_round_phase(self, n: int) -> None:
        r = self._round(n)
        r.phase = next_phase(r.phase)

    def set_round_phase(self, n: int, phase: Phase) -> None:
        self._round(n).phase = phase

    def set_round_decision(self, n: int, decision: Decision) -> None:
        self._round(n).decision = decision

    def touch_heartbeat(self, ts: str) -> None:
        self.last_heartbeat = ts

    def advance_current_phase(self) -> None:
        """Increment current_phase (capped at total_phases) and clear pending flag."""
        self.current_phase = min(self.current_phase + 1, self.total_phases)
        self.phase_advance_pending = False
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_run_state_phase.py -v
```

Expected: all pass.

- [ ] **Step 5: Run full test suite to check for regressions**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/ -v
```

The `test_run_state.py` tests should still pass (no fields removed). If any test references `STOP_FOR_USER` as a valid `Decision` literal value and fails a type check, note it -- it will be cleaned up in Task 4.

- [ ] **Step 6: Commit**

```bash
git add python/agent_loop/run_state.py python/tests/test_run_state_phase.py
git commit -m "feat(run-state): add phase fields and PHASE_COMPLETE decision"
```

---

### Task 2: plan-init -- phase generation (second Codex call)

**Files:**
- Modify: `python/agent_loop/cli.py` (functions `_parse_phases_response`, `_cmd_plan_init`)
- Create: `python/tests/test_plan_init_phases.py`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_plan_init_phases.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "agent_loop", *args],
        cwd=cwd, capture_output=True, text=True, check=False, env=env,
    )


def _two_call_stub(tmp_repo: Path, plan_text: str, phases_json: str) -> dict:
    """Stub that returns plan_text on first call, phases_json on second."""
    stub_path = tmp_repo / "codex_stub2.py"
    data_path = tmp_repo / "codex_stub2_state.json"
    data_path.write_text(json.dumps({"i": 0, "responses": [plan_text, phases_json]}), encoding="utf-8")
    stub_path.write_text(
        "import json\n"
        f"p = {str(data_path)!r}\n"
        "data = json.load(open(p, encoding='utf-8'))\n"
        "i = data['i']\n"
        "content = data['responses'][i % len(data['responses'])]\n"
        "data['i'] = i + 1\n"
        "json.dump(data, open(p, 'w', encoding='utf-8'))\n"
        "print(json.dumps({'type': 'assistant_message', 'content': content}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}


PLAN_TEXT = "# Plan\n\n## Tasks\n1. [ ] do thing\n"
PHASES_JSON = json.dumps({
    "phases": [
        {"phase_n": 1, "title": "Foundation", "objective": "Set up the base.", "content": "# Phase 1\n\n## Objective\nSet up the base.\n"},
        {"phase_n": 2, "title": "Core Logic", "objective": "Implement core.", "content": "# Phase 2\n\n## Objective\nImplement core.\n"},
    ]
})


def test_plan_init_writes_phases_json(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "big goal", "--slug", "big"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]

    env = _two_call_stub(tmp_repo, PLAN_TEXT, PHASES_JSON)
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r2.returncode == 0, r2.stderr

    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    phases_json_path = run_dir / "phases.json"
    assert phases_json_path.exists(), "phases.json not written"
    phases = json.loads(phases_json_path.read_text(encoding="utf-8"))
    assert len(phases) == 2
    assert phases[0]["phase_n"] == 1
    assert phases[0]["title"] == "Foundation"


def test_plan_init_writes_phase_docs(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "big goal", "--slug", "big"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]

    env = _two_call_stub(tmp_repo, PLAN_TEXT, PHASES_JSON)
    _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)

    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    assert (run_dir / "phases" / "phase-01.md").exists()
    assert (run_dir / "phases" / "phase-02.md").exists()
    assert "Phase 1" in (run_dir / "phases" / "phase-01.md").read_text(encoding="utf-8")


def test_plan_init_sets_state_phase_fields(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "big goal", "--slug", "big"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]

    env = _two_call_stub(tmp_repo, PLAN_TEXT, PHASES_JSON)
    _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)

    state = json.loads((tmp_repo / ".agent-loop" / "runs" / run_id / "state.json").read_text(encoding="utf-8"))
    assert state["current_phase"] == 1
    assert state["total_phases"] == 2


def test_plan_init_emits_phases_in_json(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "big goal", "--slug", "big"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]

    env = _two_call_stub(tmp_repo, PLAN_TEXT, PHASES_JSON)
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    out = json.loads(r2.stdout)
    assert "phases" in out
    assert len(out["phases"]) == 2
    assert "2 phase" in out["summary"]


def test_plan_init_single_phase_fallback_on_bad_json(tmp_repo: Path) -> None:
    """Malformed phases JSON -> fallback to 1 phase."""
    r1 = _run(["init-run", "--goal", "simple goal", "--slug", "simple"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]

    env = _two_call_stub(tmp_repo, PLAN_TEXT, "not json at all")
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r2.returncode == 0, r2.stderr
    out = json.loads(r2.stdout)
    assert len(out["phases"]) == 1

    state = json.loads((tmp_repo / ".agent-loop" / "runs" / run_id / "state.json").read_text(encoding="utf-8"))
    assert state["total_phases"] == 1
    assert state["current_phase"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_plan_init_phases.py -v
```

Expected: all fail (`phases` key missing from output, no phase files written).

- [ ] **Step 3: Add `_parse_phases_response` helper to cli.py**

Add this function near `_parse_round_plan` in `python/agent_loop/cli.py`:

```python
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
        n = int(ph.get("phase_n", i))
        title = str(ph.get("title", f"Phase {n}")).strip()
        objective = str(ph.get("objective", "")).strip()
        content = str(ph.get("content", "")).strip()
        if not content:
            content = f"# Phase {n}: {title}\n\n## Objective\n{objective}\n"
        result.append({
            "phase_n": n,
            "title": title,
            "objective": objective,
            "content": content + "\n",
        })
    return result if result else _single_phase_fallback()


def _single_phase_fallback() -> list[dict]:
    return [{
        "phase_n": 1,
        "title": "Implementation",
        "objective": "Complete the goal.",
        "content": "# Phase 1: Implementation\n\n## Objective\nComplete the goal.\n",
    }]
```

- [ ] **Step 4: Extend `_cmd_plan_init` in cli.py**

Replace the existing `_cmd_plan_init` function body with:

```python
@register("plan-init")
def _cmd_plan_init(args) -> int:
    from agent_loop.codex_client import call_codex, CodexCallError
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    goal = (run_dir / "goal.md").read_text(encoding="utf-8").strip()

    # First Codex call: draft plan.md (existing behavior)
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
    plan_path = run_dir / "plan.md"
    plan_path.write_text(plan_res.final_text, encoding="utf-8")

    # Second Codex call: generate phases
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
        f"## Plan (tasks overview)\n{plan_res.final_text}\n"
    )
    try:
        phases_res = call_codex(phases_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1

    phases = _parse_phases_response(phases_res.final_text)

    # Write phase docs and index
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

    # Update state with phase counts
    rs = RunState.load(run_dir / "state.json")
    rs.total_phases = len(phases)
    rs.current_phase = 1
    rs.save(run_dir / "state.json")

    _emit({
        "plan_path": str(plan_path),
        "phases": phases_index,
        "summary": f"{len(phases)} phase(s) drafted",
    })
    return 0
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_plan_init_phases.py -v
```

Expected: all pass.

- [ ] **Step 6: Run full suite to check regressions**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/ -v
```

`test_plan_init_writes_plan_md` should still pass -- plan.md behavior is unchanged.

- [ ] **Step 7: Commit**

```bash
git add python/agent_loop/cli.py python/tests/test_plan_init_phases.py
git commit -m "feat(plan-init): generate phase docs via second Codex call"
```

---

### Task 3: plan-round and review-round -- inject current phase doc

**Files:**
- Modify: `python/agent_loop/cli.py` (add `_load_current_phase_section`, extend `_cmd_plan_round`, extend `_cmd_review_round`)
- Create: `python/tests/test_phase_injection.py`

- [ ] **Step 1: Write failing tests**

Create `python/tests/test_phase_injection.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "agent_loop", *args],
        cwd=cwd, capture_output=True, text=True, check=False, env=env,
    )


def _setup_run_with_phases(tmp_repo: Path, n_phases: int = 2) -> tuple[str, Path]:
    """init-run + manually create phases.json + phase docs. Returns (run_id, run_dir)."""
    r = _run(["init-run", "--goal", "big goal", "--slug", "test"], cwd=tmp_repo)
    run_id = json.loads(r.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # Write plan.md
    (run_dir / "plan.md").write_text("# Plan\n\n## Tasks\n1. [ ] thing\n", encoding="utf-8")

    # Write phase docs
    (run_dir / "phases").mkdir()
    phases_index = []
    for i in range(1, n_phases + 1):
        doc = f"# Phase {i}: Title{i}\n\n## Objective\nObjective {i}.\n"
        (run_dir / "phases" / f"phase-{i:02d}.md").write_text(doc, encoding="utf-8")
        phases_index.append({"phase_n": i, "title": f"Title{i}", "objective": f"Objective {i}.", "doc_path": f"phases/phase-{i:02d}.md"})
    (run_dir / "phases.json").write_text(json.dumps(phases_index), encoding="utf-8")

    # Set state: current_phase=1, total_phases=n_phases
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    state["current_phase"] = 1
    state["total_phases"] = n_phases
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    return run_id, run_dir


def _make_round_plan_stub(tmp_repo: Path, content: str) -> dict:
    stub_path = tmp_repo / "codex_round_stub.py"
    stub_path.write_text(
        "import json\n"
        f"print(json.dumps({{'type': 'assistant_message', 'content': {content!r}}}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}


ROUND_PLAN_JSON = json.dumps({
    "round_plan": {"round": 1, "worker_model": "haiku", "worker_model_reason": "simple", "reasoning_effort": "low", "subtasks": []},
    "task_description": "do the task",
    "execution_plan_bullets": ["step 1"],
    "acceptance_criteria": ["criterion 1"],
    "carry_forward": "",
})


def test_plan_round_prompt_contains_current_phase(tmp_repo: Path) -> None:
    run_id, run_dir = _setup_run_with_phases(tmp_repo)
    env = _make_round_plan_stub(tmp_repo, ROUND_PLAN_JSON)
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    prompt = (run_dir / "rounds" / "01" / "claude-prompt.md").read_text(encoding="utf-8")
    assert "Current Phase" in prompt
    assert "Title1" in prompt
    assert "Objective 1" in prompt


def test_plan_round_no_phase_injection_when_no_phases_json(tmp_repo: Path) -> None:
    """plan-round works normally when phases.json doesn't exist (single-phase run)."""
    r = _run(["init-run", "--goal", "simple", "--slug", "simple"], cwd=tmp_repo)
    run_id = json.loads(r.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    (run_dir / "plan.md").write_text("# Plan\n\n## Tasks\n1. [ ] thing\n", encoding="utf-8")

    env = _make_round_plan_stub(tmp_repo, ROUND_PLAN_JSON)
    r2 = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r2.returncode == 0, r2.stderr


def test_plan_round_injects_phase2_when_current_phase_is_2(tmp_repo: Path) -> None:
    run_id, run_dir = _setup_run_with_phases(tmp_repo)
    # Set current_phase to 2
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    state["current_phase"] = 2
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    env = _make_round_plan_stub(tmp_repo, ROUND_PLAN_JSON)
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr

    prompt = (run_dir / "rounds" / "01" / "claude-prompt.md").read_text(encoding="utf-8")
    assert "Title2" in prompt
    assert "Objective 2" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_phase_injection.py -v
```

Expected: `test_plan_round_prompt_contains_current_phase` and `test_plan_round_injects_phase2_when_current_phase_is_2` fail.

- [ ] **Step 3: Add `_load_current_phase_section` helper to cli.py**

Add after `_single_phase_fallback()` in `cli.py`:

```python
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
    entry = next((p for p in phases if p.get("phase_n") == current_phase), None)
    if entry is None:
        return ""
    doc_path = run_dir / entry.get("doc_path", f"phases/phase-{current_phase:02d}.md")
    if not doc_path.exists():
        return ""
    content = doc_path.read_text(encoding="utf-8").strip()
    title = entry.get("title", f"Phase {current_phase}")
    return f'\n## Current Phase (Phase {current_phase}: "{title}")\n{content}\n'
```

- [ ] **Step 4: Inject phase section in `_cmd_plan_round`**

In `_cmd_plan_round` in `cli.py`, after `memo_bounded = _bounded_memo(...)`, add:

```python
    current_phase_section = _load_current_phase_section(run_dir, rs.current_phase)
```

Then in `round_plan_prompt`, insert `{current_phase_section}` between `## Goal` and `## Plan`:

```python
    round_plan_prompt = f"""...
## Goal
{goal}
{current_phase_section}
## Plan
{plan}
...
```

The exact insertion: find the line `f"## Goal\n{goal}\n\n## Plan\n{plan}\n\n"` in the existing f-string and replace it with `f"## Goal\n{goal}\n{current_phase_section}\n## Plan\n{plan}\n\n"`.

- [ ] **Step 5: Run tests to verify they pass**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_phase_injection.py -v
```

Expected: all pass.

- [ ] **Step 6: Run full suite**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add python/agent_loop/cli.py python/tests/test_phase_injection.py
git commit -m "feat(plan-round): inject current phase doc into Codex prompt"
```

---

### Task 4: review-round -- PHASE_COMPLETE decision, remove STOP_FOR_USER

**Files:**
- Modify: `python/agent_loop/cli.py` (`_cmd_review_round`)
- Modify: `python/tests/test_cli_plan_round.py` (fix STOP_FOR_USER stub on line 742)
- Modify: `python/tests/test_cli_review_round.py` (add PHASE_COMPLETE test)

- [ ] **Step 1: Write the failing test for PHASE_COMPLETE**

Add to `python/tests/test_cli_review_round.py`:

```python
def test_review_round_handles_phase_complete(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    rd = run_dir / "rounds" / "01"
    rd.mkdir(parents=True)
    (rd / "claude-result.md").write_text(
        "# Claude Result\n\n## Summary\ndid stuff\n\n## Test Outcome\npass\n\n## Decision Hint\ncompleted\n\n## Requires User\nfalse\n",
        encoding="utf-8",
    )
    (rd / "diff.patch").write_text("", encoding="utf-8")

    state_p = run_dir / "state.json"
    state = json.loads(state_p.read_text(encoding="utf-8"))
    state["rounds"].append({"n": 1, "phase": "claude_completed", "decision": None, "memo_lines": None, "started_at": "t", "ended_at": None})
    state["current_round"] = 1
    state["current_phase"] = 1
    state["total_phases"] = 2
    state_p.write_text(json.dumps(state), encoding="utf-8")

    fake_body = (
        "# Codex Review -- Round 1\n\n"
        "## Decision\nPHASE_COMPLETE\n\n"
        "## Findings\n- phase objective met\n"
    )
    env = codex_stub(fake_body)
    r = _run(["review-round", "--run", run_id, "--round", "1"], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["decision"] == "PHASE_COMPLETE"
    assert js["current_phase"] == 1

    # phase_advance_pending must be set in state.json
    state2 = json.loads(state_p.read_text(encoding="utf-8"))
    assert state2["phase_advance_pending"] is True


def test_review_round_fallback_decision_is_needs_changes(tmp_repo: Path, codex_stub) -> None:
    """When Codex outputs no parseable decision, fallback is NEEDS_CHANGES (not STOP_FOR_USER)."""
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    rd = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rd.mkdir(parents=True)
    (rd / "claude-result.md").write_text(
        "# Claude Result\n\n## Summary\nx\n\n## Test Outcome\npass\n\n## Decision Hint\ncompleted\n\n## Requires User\nfalse\n",
        encoding="utf-8",
    )
    (rd / "diff.patch").write_text("", encoding="utf-8")

    state_p = tmp_repo / ".agent-loop" / "runs" / run_id / "state.json"
    state = json.loads(state_p.read_text(encoding="utf-8"))
    state["rounds"].append({"n": 1, "phase": "claude_completed", "decision": None, "memo_lines": None, "started_at": "t", "ended_at": None})
    state["current_round"] = 1
    state_p.write_text(json.dumps(state), encoding="utf-8")

    # No ## Decision section -> fallback
    env = codex_stub("# Codex Review\n\nSome text without a decision section.")
    r = _run(["review-round", "--run", run_id, "--round", "1"], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["decision"] == "NEEDS_CHANGES"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_cli_review_round.py::test_review_round_handles_phase_complete tests/test_cli_review_round.py::test_review_round_fallback_decision_is_needs_changes -v
```

Expected: both fail.

- [ ] **Step 3: Update `_cmd_review_round` in cli.py**

Make these targeted changes in `_cmd_review_round`:

**3a.** Load `rs` from state early (after loading `cfg`) and add phase section injection:

After `rs = RunState.load(run_dir / "state.json")` (or add it before `meta_prompt`), add:
```python
    rs = RunState.load(run_dir / "state.json")
    current_phase_section = _load_current_phase_section(run_dir, rs.current_phase)
```

**3b.** In `meta_prompt`, add `{current_phase_section}` after `## Claude's Result Report` section and update the Decision rules block:

Replace in `meta_prompt`:
```python
"## Decision\nAPPROVE | NEEDS_CHANGES | STOP_FOR_USER\n"
```
With:
```python
"## Decision\nAPPROVE | NEEDS_CHANGES | PHASE_COMPLETE\n"
```

Replace the Decision rules block:
```python
"Decision rules:\n"
"- STOP_FOR_USER if safety_flags non-empty, OR result.requires_user true, OR you see ambiguity needing human judgement.\n"
"- APPROVE if goal satisfied this round + tests pass + no flags.\n"
"- NEEDS_CHANGES otherwise (default).\n"
```
With:
```python
"Decision rules:\n"
"- PHASE_COMPLETE when this phase's objective (from the Current Phase section) is fully achieved and the codebase is ready for the next phase.\n"
"- APPROVE if the entire run goal is achieved (all phases complete or goal fully satisfied).\n"
"- NEEDS_CHANGES otherwise (default).\n"
"Safety flags (if any) are informational -- Codex decides the appropriate decision.\n"
```

Add phase section in `meta_prompt` after the payload block:
```python
f"{current_phase_section}"
```

**3c.** Update the decision regex (two places in the function):

```python
    m = re.search(
        r"##\s+Decision\s*\n\s*(APPROVE|NEEDS_CHANGES|PHASE_COMPLETE)\s*",
        res.final_text, re.IGNORECASE,
    )
    decision = m.group(1).upper() if m else "NEEDS_CHANGES"
```

**3d.** After setting `decision`, set `phase_advance_pending` when PHASE_COMPLETE:

```python
    if decision == "PHASE_COMPLETE":
        rs.phase_advance_pending = True
```

Ensure `rs.save(run_dir / "state.json")` is called after this.

**3e.** Update compact artifacts condition (remove STOP_FOR_USER check):

Replace:
```python
    if artifact_mode == "compact" and decision != "STOP_FOR_USER" and not safety_flags:
```
With:
```python
    if artifact_mode == "compact" and not safety_flags:
```

**3f.** Add `current_phase` to emitted JSON:

```python
    _emit({
        "decision": decision,
        "current_phase": rs.current_phase,
        "review_path": str(rd / "codex-review.md"),
        ...
    })
```

- [ ] **Step 4: Fix STOP_FOR_USER reference in test_cli_plan_round.py**

In `python/tests/test_cli_plan_round.py` at line 742, the codex stub returns `STOP_FOR_USER`. Change to `NEEDS_CHANGES`:

```python
# Before (line ~742):
"# Codex Review -- Round 1\n\n## Decision\nSTOP_FOR_USER\n\n"
# After:
"# Codex Review -- Round 1\n\n## Decision\nNEEDS_CHANGES\n\n"
```

Also update the assertion that follows (if any) from `STOP_FOR_USER` to `NEEDS_CHANGES`.

- [ ] **Step 5: Run the new tests to verify they pass**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_cli_review_round.py -v
```

Expected: all pass including new tests.

- [ ] **Step 6: Run full suite**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add python/agent_loop/cli.py python/tests/test_cli_review_round.py python/tests/test_cli_plan_round.py
git commit -m "feat(review-round): add PHASE_COMPLETE decision, remove STOP_FOR_USER"
```

---

### Task 5: advance-phase CLI subcommand

**Files:**
- Modify: `python/agent_loop/cli.py` (parser entry + `_cmd_advance_phase`)
- Create: `python/tests/test_cli_advance_phase.py`

- [ ] **Step 1: Write failing tests**

Create `python/tests/test_cli_advance_phase.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "agent_loop", *args],
        cwd=cwd, capture_output=True, text=True, check=False, env=env,
    )


def _setup_two_phase_run(tmp_repo: Path) -> tuple[str, Path]:
    """Create a run with 2 phases in phase-complete state."""
    r = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    (run_dir / "plan.md").write_text("# Plan\n\n## Tasks\n1. [ ] x\n", encoding="utf-8")
    (run_dir / "phases").mkdir()
    phases_index = [
        {"phase_n": 1, "title": "Phase1", "objective": "Obj1.", "doc_path": "phases/phase-01.md"},
        {"phase_n": 2, "title": "Phase2", "objective": "Obj2.", "doc_path": "phases/phase-02.md"},
    ]
    (run_dir / "phases.json").write_text(json.dumps(phases_index), encoding="utf-8")
    (run_dir / "phases" / "phase-01.md").write_text("# Phase 1\n\nObj1.\n", encoding="utf-8")
    (run_dir / "phases" / "phase-02.md").write_text("# Phase 2\n\nObj2 original.\n", encoding="utf-8")

    # shared context
    (run_dir / "shared").mkdir(exist_ok=True)
    (run_dir / "shared" / "knowledge.md").write_text("key fact\n", encoding="utf-8")

    # state: phase 1, 2 total, advance pending
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    state["current_phase"] = 1
    state["total_phases"] = 2
    state["phase_advance_pending"] = True
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    return run_id, run_dir


def _stub(tmp_repo: Path, content: str) -> dict:
    stub_path = tmp_repo / "stub_adv.py"
    stub_path.write_text(
        "import json\n"
        f"print(json.dumps({{'type': 'assistant_message', 'content': {content!r}}}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    return {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}


def test_advance_phase_increments_current_phase(tmp_repo: Path) -> None:
    run_id, run_dir = _setup_two_phase_run(tmp_repo)
    env = _stub(tmp_repo, "# Phase 2 updated\n\nUpdated content.\n")
    r = _run(["advance-phase", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["previous_phase"] == 1
    assert js["current_phase"] == 2
    assert js["is_last_phase"] is False

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["current_phase"] == 2
    assert state["phase_advance_pending"] is False


def test_advance_phase_updates_next_phase_doc(tmp_repo: Path) -> None:
    run_id, run_dir = _setup_two_phase_run(tmp_repo)
    updated_content = "# Phase 2 Updated\n\nNew content from Codex.\n"
    env = _stub(tmp_repo, updated_content)
    _run(["advance-phase", "--run", run_id], cwd=tmp_repo, env_overrides=env)

    doc = (run_dir / "phases" / "phase-02.md").read_text(encoding="utf-8")
    assert "New content from Codex" in doc


def test_advance_phase_emits_is_last_phase_when_on_last(tmp_repo: Path) -> None:
    """When already on the last phase, emit is_last_phase=true without Codex call."""
    r = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    (run_dir / "phases").mkdir()
    phases_index = [{"phase_n": 1, "title": "Only", "objective": "O.", "doc_path": "phases/phase-01.md"}]
    (run_dir / "phases.json").write_text(json.dumps(phases_index), encoding="utf-8")
    (run_dir / "phases" / "phase-01.md").write_text("# Phase 1\n", encoding="utf-8")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    state["current_phase"] = 1
    state["total_phases"] = 1
    state["phase_advance_pending"] = True
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    # No codex stub needed -- should return is_last_phase without calling Codex
    env = {"AGENT_LOOP_CODEX_BIN": str(tmp_repo / "nonexistent-codex")}
    r = _run(["advance-phase", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["is_last_phase"] is True

    state2 = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state2["phase_advance_pending"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_cli_advance_phase.py -v
```

Expected: all fail (`advance-phase` subcommand not registered).

- [ ] **Step 3: Add `advance-phase` to the CLI parser**

In `build_parser()` in `cli.py`, add after the `continue` block:

```python
    # advance-phase
    p = sub.add_parser("advance-phase", help="transition to next phase and update phase doc")
    _add_common(p)
    p.add_argument("--run", required=True)
```

- [ ] **Step 4: Implement `_cmd_advance_phase`**

Add to `cli.py`:

```python
@register("advance-phase")
def _cmd_advance_phase(args) -> int:
    from agent_loop.codex_client import call_codex, CodexCallError
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    current_phase = rs.current_phase

    # If already on last phase, emit sentinel without Codex call
    if current_phase >= rs.total_phases:
        rs.phase_advance_pending = False
        rs.save(run_dir / "state.json")
        _emit({
            "previous_phase": current_phase,
            "current_phase": current_phase,
            "is_last_phase": True,
        })
        return 0

    # Load phases index
    phases_json_path = run_dir / "phases.json"
    if not phases_json_path.exists():
        print("phases.json not found", file=sys.stderr)
        return 1
    try:
        phases = _json.loads(phases_json_path.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as e:
        print(f"phases.json parse error: {e}", file=sys.stderr)
        return 1

    next_phase_n = current_phase + 1
    next_entry = next((p for p in phases if p.get("phase_n") == next_phase_n), None)
    if next_entry is None:
        print(f"no phases.json entry for phase {next_phase_n}", file=sys.stderr)
        return 1

    # Gather update context
    def _read_safe(path: _Path, cap: int = 0) -> str:
        if not path.exists():
            return "(none)"
        text = path.read_text(encoding="utf-8").strip()
        return text[:cap] if cap else text

    knowledge = _read_safe(run_dir / "shared" / "knowledge.md")
    decisions = _read_safe(run_dir / "shared" / "decisions.md")
    last_review = ""
    if rs.rounds:
        last_review = _read_safe(
            run_dir / "rounds" / f"{rs.rounds[-1].n:02d}" / "codex-review.md",
            cap=1500,
        )

    doc_path = run_dir / next_entry.get("doc_path", f"phases/phase-{next_phase_n:02d}.md")
    original_doc = _read_safe(doc_path)

    update_prompt = (
        f"You are updating the strategic context document for Phase {next_phase_n} of an ongoing implementation.\n\n"
        "The previous phase is complete. Update the phase document to reflect what was actually accomplished "
        "and what this next phase should focus on.\n\n"
        "Output ONLY the updated markdown content (no JSON, no explanation, just the markdown document).\n\n"
        f"## Phase {next_phase_n} Original Document\n{original_doc}\n\n"
        f"## Accumulated Knowledge\n{knowledge}\n\n"
        f"## Accumulated Decisions\n{decisions}\n\n"
        f"## Last Codex Review\n{last_review or '(none)'}\n"
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
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_cli_advance_phase.py -v
```

Expected: all pass.

- [ ] **Step 6: Run full suite**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add python/agent_loop/cli.py python/tests/test_cli_advance_phase.py
git commit -m "feat(advance-phase): new CLI subcommand for phase transitions"
```

---

### Task 6: resume.py -- add advance_phase action

**Files:**
- Modify: `python/agent_loop/resume.py`
- Modify: `python/tests/test_resume.py`

- [ ] **Step 1: Write failing test**

Add to `python/tests/test_resume.py`:

```python
def test_determine_resume_action_advance_phase_when_pending(tmp_path: Path) -> None:
    from agent_loop.resume import determine_resume_action
    from agent_loop.run_state import RunState, RoundEntry

    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.total_phases = 2
    rs.current_phase = 1
    rs.phase_advance_pending = True
    rs.rounds.append(RoundEntry(n=1, phase="completed", decision="PHASE_COMPLETE"))
    rs.current_round = 1

    run_dir = tmp_path / "runs" / "r"
    run_dir.mkdir(parents=True)

    plan = determine_resume_action(rs, run_dir=run_dir)
    assert plan.action == "advance_phase"
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_resume.py::test_determine_resume_action_advance_phase_when_pending -v
```

Expected: fail (action not `advance_phase`).

- [ ] **Step 3: Update resume.py**

In `python/agent_loop/resume.py`:

**3a.** Add `advance_phase` to `Action` literal:

```python
Action = Literal[
    "plan_round",
    "dispatch",
    "advance_to_review",
    "write_review",
    "write_memo",
    "branch_decision",
    "advance_phase",
    "user_confirm",
    "finalize",
]
```

**3b.** Add check at top of `determine_resume_action` (before the `if not rs.rounds` check):

```python
def determine_resume_action(rs: RunState, *, run_dir: Path) -> ResumePlan:
    if rs.phase_advance_pending:
        return ResumePlan(
            action="advance_phase",
            notes="PHASE_COMPLETE received; advance-phase has not yet run",
        )
    if not rs.rounds:
        return ResumePlan(action="plan_round", notes="no rounds started yet")
    ...
```

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/test_resume.py -v
```

Expected: all pass.

- [ ] **Step 5: Run full suite**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add python/agent_loop/resume.py python/tests/test_resume.py
git commit -m "feat(resume): add advance_phase action for interrupted phase transitions"
```

---

### Task 7: Update skill docs (SKILL.md, safety-rules.md, resume-run.md)

These are documentation-only changes, no tests needed.

**Files:**
- Modify: `skills/agent-loop/SKILL.md`
- Modify: `skills/agent-loop/safety-rules.md`
- Modify: `skills/agent-loop/resume-run.md`

- [ ] **Step 1: Update SKILL.md**

Make these targeted changes:

**1a.** Round loop heading (line 136): replace `APPROVE / STOP_FOR_USER` with `APPROVE / PHASE_COMPLETE`:
```
## Round loop (repeat until APPROVE / PHASE_COMPLETE)
```

**1b.** On start step 2: update plan-init output description to mention phases:
```
2. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" plan-init --run <run_id>`
   -> JSON `{plan_path, phases, summary}`. (Codex drafted plan.md and phase docs on disk.)
```

**1c.** Review-round step 6: update decision description:
```
6. After Task tool returns, run: `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" review-round --run <run_id> --round N`
   -> JSON `{decision, current_phase, review_path, safety_flags, memo_appended, memo_path}`. Decision is one of APPROVE / NEEDS_CHANGES / PHASE_COMPLETE.
```

**1d.** Step 7 decision branch: replace STOP_FOR_USER with PHASE_COMPLETE:
```
7. Branch on `decision`:
   - `APPROVE` ->
     1. If `commit_on_approve` is `true`: `Bash: git add -A && git commit -m "<commit_message>"`. Show commit hash.
     2. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" finalize --run <run_id>`. Tell user run completed; point at `final-report.md`. END.
   - `PHASE_COMPLETE` ->
     1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase --run <run_id>`
        -> JSON `{previous_phase, current_phase, updated_doc, is_last_phase}`.
     2. If `is_last_phase` is `true`: call finalize (step above). END.
     3. Announce: `Phase <previous_phase> complete -> advancing to Phase <current_phase>: "<title from phases.json>"`.
     4. Loop back to step 1 (next round in new phase).
   - `NEEDS_CHANGES` -> Loop back to step 1 (next round).
```

**1e.** Remove the `STOP_FOR_USER` bullet entirely.

- [ ] **Step 2: Update safety-rules.md**

Replace the Supervisor reaction matrix section:

```markdown
## Supervisor reaction matrix

| Decision (from review-round JSON) | What to do |
|---|---|
| `APPROVE` | Call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" finalize`. |
| `PHASE_COMPLETE` | Call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase`. If `is_last_phase` true, then finalize. |
| `NEEDS_CHANGES` | Next round. |

`safety_flags` (if any) are passed to Codex in the review payload -- Codex decides the appropriate decision. The supervisor does not override Codex's decision based on flags.
```

Remove the old `STOP_FOR_USER` rows and the "defense in depth" note.

- [ ] **Step 3: Update resume-run.md**

**3a.** Add `advance_phase` to the action table:

```markdown
| `advance_phase` | Call `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase --run <run_id>`. If `is_last_phase` true, finalize. Otherwise loop back to round-loop step 1. |
```

**3b.** Update `branch_decision` row to remove STOP_FOR_USER:
```markdown
| `branch_decision` | Review and memo are done, just branch (APPROVE / PHASE_COMPLETE / NEEDS_CHANGES). |
```

- [ ] **Step 4: Verify SKILL.md has no remaining STOP_FOR_USER references**

```bash
grep -r "STOP_FOR_USER" skills/
```

Expected: no output.

- [ ] **Step 5: Run full test suite one final time**

```
cd C:\dev\ClaudeXCodex\python
pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit all skill doc changes**

```bash
git add skills/agent-loop/SKILL.md skills/agent-loop/safety-rules.md skills/agent-loop/resume-run.md
git commit -m "docs(skill): update supervisor instructions for PHASE_COMPLETE and advance-phase"
```
