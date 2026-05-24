# Phased Planning Design

**Date:** 2026-05-24  
**Status:** Approved

## Problem

The current agent-loop handles large goals by breaking them into 3–7 flat tasks in `plan.md`. For long-running goals this creates context drift: Codex and workers lose the strategic thread after several rounds because the memo window is bounded to 3 rounds. There is no persistent mid-level structure between the immutable goal and the per-round task.

## Goal

Add a **phase layer** between the global goal and per-round tasks:

- Codex pre-generates phase documents at run start
- Each phase is a Codex-only strategic context document (workers do not read it)
- Phase documents are updated at phase boundaries to reflect actual results
- The global `goal.md` remains immutable — the north star for the entire run

## Design

### Artifact Structure

```
.agent-loop/runs/<run_id>/
  goal.md            # immutable — unchanged
  plan.md            # Codex strategic notes — unchanged
  phases.json        # NEW: phase index [{phase_n, title, objective, doc_path}]
  phases/
    phase-01.md      # NEW: Codex-only context doc for phase 1
    phase-02.md      # updated by advance-phase before phase 2 starts
    ...
  memo.md            # unchanged
  state.json         # current_phase field added
  shared/            # unchanged
  rounds/            # unchanged
```

### Hierarchy

```
Goal (immutable)
└── Phase 1  ←── phase-01.md (Codex context)
│   ├── Round 1  →  NEEDS_CHANGES
│   ├── Round 2  →  NEEDS_CHANGES
│   └── Round 3  →  PHASE_COMPLETE
└── Phase 2  ←── phase-02.md (updated by advance-phase)
│   ├── Round 4  →  NEEDS_CHANGES
│   └── Round 5  →  PHASE_COMPLETE
└── Phase 3  ←── phase-03.md (updated by advance-phase)
    ├── Round 6  →  NEEDS_CHANGES
    └── Round 7  →  APPROVE
```

Round numbers are continuous across the entire run. Phase transitions are transparent to the round loop.

### Decision Values

| Value | Meaning | Action |
|---|---|---|
| `NEEDS_CHANGES` | Round not sufficient | Next round, same phase |
| `PHASE_COMPLETE` | Phase objectives met | Call `advance-phase`, continue round loop in next phase |
| `APPROVE` | Entire goal achieved | `finalize` |

`STOP_FOR_USER` is removed. Codex drives all decisions autonomously.

### Changes Per Component

#### `plan-init` (extended)

Codex receives the goal and decides the number of phases (1–5). For simple goals, 1 phase is sufficient (same behavior as today). For complex goals, 2–5 phases.

Codex outputs:
- `plan.md` — existing strategic notes
- `phases/phase-N.md` — one document per phase, containing:
  - Phase objective
  - Key context and constraints for this phase
  - Expected completion criteria
  - Anticipated files/areas of the codebase involved
- `phases.json` — index of all phases

`plan-init` emits JSON:
```json
{
  "plan_path": "...",
  "phases": [
    {"phase_n": 1, "title": "...", "objective": "...", "doc_path": "phases/phase-01.md"},
    {"phase_n": 2, "title": "...", "objective": "...", "doc_path": "phases/phase-02.md"}
  ],
  "summary": "2 phases drafted"
}
```

`state.json` gains `current_phase: 1` at init. `phases.json` is written to disk by `plan-init`.

**Codex call strategy:** `plan-init` may use a single combined Codex call (outputting plan.md content + phases JSON together) or two sequential calls (plan.md first, then phases). Implementation detail to be decided during writing-plans; the output contract above is the same either way.

#### `plan-round` (extended)

Reads `state.json` → `current_phase` → loads `phases/phase-N.md`. Injects it into the Codex prompt between `## Goal` and `## Plan`:

```
## Goal
...

## Current Phase (Phase 2: "Data layer")
<phase-02.md full content>

## Plan
...

## Memo So Far
...
```

#### `review-round` (extended)

Same phase doc injection as `plan-round`. Decision choices updated:

```
## Decision
APPROVE | NEEDS_CHANGES | PHASE_COMPLETE
```

`PHASE_COMPLETE` guidance for Codex:
> Emit PHASE_COMPLETE when this phase's objective (from the Current Phase section) is satisfied and the codebase is ready to move to the next phase.

Output JSON adds:
```json
{
  "decision": "PHASE_COMPLETE",
  "current_phase": 2
}
```

#### `advance-phase` (new CLI subcommand)

Called by the supervisor immediately after `PHASE_COMPLETE`.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase --run <run_id>
```

Internal steps:
1. Read `current_phase` from `state.json`
2. Determine next phase from `phases.json`
3. If no next phase exists → emit `{"is_last_phase": true}` → supervisor calls `finalize`
4. Collect update context: `shared/knowledge.md`, `shared/decisions.md`, summary of last `codex-review.md`
5. Call Codex to update `phases/phase-N.md` (next phase doc) with actual results
6. Increment `current_phase` in `state.json`

Output JSON:
```json
{
  "previous_phase": 2,
  "current_phase": 3,
  "updated_doc": "phases/phase-03.md",
  "is_last_phase": false
}
```

#### `state.json` (extended)

```json
{
  "run_id": "...",
  "current_phase": 2,
  "total_phases": 3,
  ...
}
```

#### `resume.py` (extended)

`determine_resume_action` gains a new action:

| State | Action |
|---|---|
| PHASE_COMPLETE received, advance-phase not yet run | `advance_phase` |

The supervisor re-calls `advance-phase` on resume. All other resume logic is unchanged.

#### `SKILL.md` (supervisor instructions updated)

Supervisor round loop branch updated:

```
APPROVE        → finalize (unchanged)
NEEDS_CHANGES  → next round (unchanged)
PHASE_COMPLETE → call advance-phase → if is_last_phase: finalize; else: next round
```

Announce line on phase transition:
```
Phase <N> complete → advancing to Phase <N+1>: "<title>"
```

`STOP_FOR_USER` branch removed from all supervisor instructions.

## What Is NOT Changed

- Worker subagents do not receive phase documents (they stay focused on their subtask)
- Round numbering is continuous across phases
- `memo.md` bounded-window logic is unchanged (last 3 rounds)
- `shared/` files accumulate across all phases
- `compact` / `debug` artifact modes unchanged
- Subtask fan-out (analysis / implementation / verification) unchanged

## Resume Safety

Because `current_phase` lives in `state.json` and phase docs live on disk, a resumed run reads `current_phase` and picks up from the correct phase context automatically. No special recovery logic beyond the new `advance_phase` resume action.
