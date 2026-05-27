# Phase-Level Review & Commit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-round Codex review with phase-level review+commit so diffs are meaningful and Codex sees clean git state.

**Architecture:** (1) `RunState` gains `phase_reviews` list. (2) `plan-round` emits `phase_complete_signal`. (3) New `phase-review` CLI subcommand stages, reads `git diff HEAD~1`, calls Codex, records result. (4) SKILL.md round loop drops `review-round`, adds supervisor phase-complete judgment + `phase-review` call.

**Tech Stack:** Python 3.11+, pytest, git subprocess, existing `codex_client.call_codex` pattern.

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `python/agent_loop/run_state.py` | Modify | Add `phase_reviews: list[dict]`, `add_phase_review()`, `consecutive_phase_needs_changes()` |
| `python/agent_loop/cli.py` | Modify | `_parse_round_plan` adds `phase_complete_signal`; `_cmd_plan_round` prompt/emit updated; add `phase-review` parser+handler |
| `skills/agent-loop/SKILL.md` | Modify | Round loop rewrite: drop `review-round`, add supervisor judgment + `phase-review` |
| `python/tests/test_run_state.py` | Modify | Tests for `phase_reviews` field and helpers |
| `python/tests/test_cli_plan_round.py` | Modify | Test `phase_complete_signal` in emitted JSON |
| `python/tests/test_cli_phase_review.py` | Create | Full test suite for `phase-review` subcommand |

---

## Task 1: RunState — phase_reviews field

**Files:**
- Modify: `python/agent_loop/run_state.py`
- Modify: `python/tests/test_run_state.py`

- [ ] **Step 1: Write failing tests**

Add to `python/tests/test_run_state.py`:

```python
def test_phase_reviews_default_empty():
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    assert rs.phase_reviews == []


def test_add_phase_review_appends():
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.add_phase_review(phase_n=1, decision="APPROVE", sha="abc123", review_path="phases/phase-01-review.md")
    assert len(rs.phase_reviews) == 1
    assert rs.phase_reviews[0] == {
        "phase_n": 1, "decision": "APPROVE", "sha": "abc123",
        "review_path": "phases/phase-01-review.md",
    }


def test_consecutive_phase_needs_changes_counts_tail():
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.add_phase_review(phase_n=1, decision="NEEDS_CHANGES", sha="a", review_path="r1")
    rs.add_phase_review(phase_n=1, decision="NEEDS_CHANGES", sha="b", review_path="r2")
    assert rs.consecutive_phase_needs_changes(1) == 2


def test_consecutive_phase_needs_changes_resets_on_approve():
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.add_phase_review(phase_n=1, decision="NEEDS_CHANGES", sha="a", review_path="r1")
    rs.add_phase_review(phase_n=1, decision="APPROVE", sha="b", review_path="r2")
    rs.add_phase_review(phase_n=1, decision="NEEDS_CHANGES", sha="c", review_path="r3")
    assert rs.consecutive_phase_needs_changes(1) == 1


def test_phase_reviews_round_trip(tmp_path):
    path = tmp_path / "state.json"
    rs = RunState.new(run_id="r", goal_path="g", plan_path="p")
    rs.add_phase_review(phase_n=2, decision="NEEDS_CHANGES", sha="xyz", review_path="phases/phase-02-review.md")
    rs.save(path)
    rs2 = RunState.load(path)
    assert rs2.phase_reviews == [{"phase_n": 2, "decision": "NEEDS_CHANGES", "sha": "xyz", "review_path": "phases/phase-02-review.md"}]


def test_phase_reviews_load_backward_compat(tmp_path):
    """Old state.json without phase_reviews field loads without error."""
    path = tmp_path / "state.json"
    path.write_text('{"run_id":"r","goal_path":"g","plan_path":"p","rounds":[]}', encoding="utf-8")
    rs = RunState.load(path)
    assert rs.phase_reviews == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd python && python -m pytest tests/test_run_state.py -k "phase_review" -v
```
Expected: `AttributeError: 'RunState' object has no attribute 'phase_reviews'` (or similar)

- [ ] **Step 3: Implement in run_state.py**

In `python/agent_loop/run_state.py`, edit the `RunState` dataclass and `load` classmethod:

```python
# Add field after last_heartbeat:
phase_reviews: list[dict] = field(default_factory=list)
```

In `load` classmethod, after the existing `raw.setdefault(...)` lines:
```python
raw.setdefault("phase_reviews", [])
```

Add two new methods after `advance_current_phase`:
```python
def add_phase_review(self, *, phase_n: int, decision: str, sha: str, review_path: str) -> None:
    self.phase_reviews.append({
        "phase_n": phase_n,
        "decision": decision,
        "sha": sha,
        "review_path": review_path,
    })

def consecutive_phase_needs_changes(self, phase_n: int) -> int:
    """Count consecutive NEEDS_CHANGES phase reviews for phase_n at the tail."""
    count = 0
    for r in reversed(self.phase_reviews):
        if r["phase_n"] != phase_n:
            continue
        if r["decision"] == "NEEDS_CHANGES":
            count += 1
        else:
            break
    return count
```

- [ ] **Step 4: Run tests to confirm they pass**

```
cd python && python -m pytest tests/test_run_state.py -k "phase_review" -v
```
Expected: all 6 tests PASS

- [ ] **Step 5: Run full test suite to check no regressions**

```
cd python && python -m pytest --tb=short -q
```
Expected: all existing tests pass

- [ ] **Step 6: Commit**

```
git add python/agent_loop/run_state.py python/tests/test_run_state.py
git commit -m "feat(run_state): add phase_reviews field and helpers"
```

---

## Task 2: plan-round — phase_complete_signal

**Files:**
- Modify: `python/agent_loop/cli.py` (functions `_parse_round_plan` and `_cmd_plan_round`)
- Modify: `python/tests/test_cli_plan_round.py`

- [ ] **Step 1: Write failing test**

Add to `python/tests/test_cli_plan_round.py` (reuse the existing `_run` and `_merged_envelope` helpers already in that file):

```python
def test_plan_round_emits_phase_complete_signal_true(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    _run(["plan-init", "--run", run_id], cwd=tmp_repo,
         env_overrides=_codex_stub_sequence(tmp_repo, [
             json.dumps({"phases": [{"phase_n": 1, "title": "T", "objective": "O", "content": "C"}]}),
         ]))

    envelope = {
        "round_plan": {
            "round": 1, "worker_model": "haiku", "worker_model_reason": "simple",
            "reasoning_effort": "low", "phase_complete_signal": True, "subtasks": [],
        },
        "task_description": "do x", "execution_plan_bullets": [], "acceptance_criteria": [], "carry_forward": "",
    }
    env = codex_stub(json.dumps(envelope))
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["phase_complete_signal"] is True


def test_plan_round_phase_complete_signal_defaults_false(tmp_repo: Path, codex_stub) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    _run(["plan-init", "--run", run_id], cwd=tmp_repo,
         env_overrides=_codex_stub_sequence(tmp_repo, [
             json.dumps({"phases": [{"phase_n": 1, "title": "T", "objective": "O", "content": "C"}]}),
         ]))

    # Codex returns envelope without phase_complete_signal
    envelope = {
        "round_plan": {
            "round": 1, "worker_model": "haiku", "worker_model_reason": "simple",
            "reasoning_effort": "low", "subtasks": [],
        },
        "task_description": "do x", "execution_plan_bullets": [], "acceptance_criteria": [], "carry_forward": "",
    }
    env = codex_stub(json.dumps(envelope))
    r = _run(["plan-round", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["phase_complete_signal"] is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd python && python -m pytest tests/test_cli_plan_round.py -k "phase_complete_signal" -v
```
Expected: `KeyError: 'phase_complete_signal'` (key missing from emitted JSON)

- [ ] **Step 3: Implement in cli.py — _parse_round_plan**

In `_parse_round_plan` (around line 525 in `python/agent_loop/cli.py`), after the `commit_message` line in the return dict, add:

```python
raw_signal = plan.get("phase_complete_signal")
phase_complete_signal = bool(raw_signal) if raw_signal is not None else False
```

Add to the return dict:
```python
"phase_complete_signal": phase_complete_signal,
```

- [ ] **Step 4: Implement in cli.py — _cmd_plan_round emit**

In `_cmd_plan_round`, inside the `_emit({...})` call (around line 1129), add:
```python
"phase_complete_signal": round_plan["phase_complete_signal"],
```

- [ ] **Step 5: Update plan-round prompt schema**

In `_cmd_plan_round`, inside `round_plan_prompt` string, replace the existing `"commit_message"` line in the JSON schema block with `"phase_complete_signal"`:

Find:
```
    "commit_message": "<Conventional Commits one-liner, or empty string if nothing shippable>"
```
Replace with:
```
    "phase_complete_signal": true
```
(Keep `commit_message` parsing in `_parse_round_plan` for backward compat with old Codex outputs, but stop asking Codex to produce it.)

- [ ] **Step 6: Run tests to confirm they pass**

```
cd python && python -m pytest tests/test_cli_plan_round.py -k "phase_complete_signal" -v
```
Expected: both tests PASS

- [ ] **Step 7: Run full test suite**

```
cd python && python -m pytest --tb=short -q
```
Expected: all tests pass

- [ ] **Step 8: Commit**

```
git add python/agent_loop/cli.py python/tests/test_cli_plan_round.py
git commit -m "feat(plan-round): emit phase_complete_signal from Codex round plan"
```

---

## Task 3: phase-review subcommand

**Files:**
- Modify: `python/agent_loop/cli.py`
- Create: `python/tests/test_cli_phase_review.py`

- [ ] **Step 1: Write failing tests**

Create `python/tests/test_cli_phase_review.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    import os
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "agent_loop", *args],
        cwd=cwd, capture_output=True, text=True, check=False, env=env,
    )


def _bootstrap_run(tmp_repo: Path, codex_stub) -> str:
    """Create a run with a single committed file so HEAD~1 exists."""
    # Make an initial commit so HEAD~1 is valid after we commit phase changes
    (tmp_repo / "src.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "src.py"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_repo, check=True)

    # Write a "phase" change and commit it (simulates phase commit)
    (tmp_repo / "src.py").write_text("x = 2\n")
    subprocess.run(["git", "add", "src.py"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "phase 1: update x"], cwd=tmp_repo, check=True)

    r = _run(["init-run", "--goal", "improve x", "--slug", "test"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    run_id = json.loads(r.stdout)["run_id"]

    # Write a phases.json so phase-review can find the phase doc
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    phases_dir = run_dir / "phases"
    phases_dir.mkdir(parents=True, exist_ok=True)
    (phases_dir / "phase-01.md").write_text("# Phase 1\n\nUpdate x to 2.", encoding="utf-8")
    (run_dir / "phases.json").write_text(
        json.dumps([{"phase_n": 1, "title": "Update x", "objective": "set x=2", "doc_path": "phases/phase-01.md"}]),
        encoding="utf-8",
    )
    (run_dir / "shared").mkdir(exist_ok=True)
    return run_id


def test_phase_review_emits_approve(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)

    fake_review = (
        "# Phase Review -- Phase 1\n\n"
        "## Decision\nAPPROVE\n\n"
        "## Goal Alignment\nObjective met.\n\n"
        "## Findings\n- none\n\n"
        "## Verification\n- Tests: pass\n\n"
        "## Risks\n- none\n\n"
        "## Carry-Forward For Next Round\n- (none)\n"
    )
    env = codex_stub(fake_review)
    r = _run(["phase-review", "--run", run_id, "--phase", "1"],
             cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["decision"] == "APPROVE"
    assert js["phase"] == 1
    assert js["memo_appended"] is True


def test_phase_review_emits_needs_changes(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)

    fake_review = (
        "# Phase Review -- Phase 1\n\n"
        "## Decision\nNEEDS_CHANGES\n\n"
        "## Goal Alignment\nNot done.\n\n"
        "## Findings\n- [severity: high] src.py:1 -- value wrong\n\n"
        "## Verification\n- Tests: fail\n\n"
        "## Risks\n- regression risk\n\n"
        "## Carry-Forward For Next Round\n- fix x value\n"
    )
    env = codex_stub(fake_review)
    r = _run(["phase-review", "--run", run_id, "--phase", "1"],
             cwd=tmp_repo, env_overrides=env)
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["decision"] == "NEEDS_CHANGES"
    assert js["severity_counts"]["high"] == 1
    assert "fix x value" in js["carry_forward"]


def test_phase_review_writes_review_file(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)

    fake_review = "# Phase Review -- Phase 1\n\n## Decision\nAPPROVE\n\n## Findings\n- none\n"
    env = codex_stub(fake_review)
    _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)

    review_path = tmp_repo / ".agent-loop" / "runs" / run_id / "phases" / "phase-01-review.md"
    assert review_path.exists()
    assert "APPROVE" in review_path.read_text(encoding="utf-8")


def test_phase_review_updates_state(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)
    fake_review = "# Phase Review -- Phase 1\n\n## Decision\nAPPROVE\n\n## Findings\n- none\n"
    env = codex_stub(fake_review)
    _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)

    state_path = tmp_repo / ".agent-loop" / "runs" / run_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state["phase_reviews"]) == 1
    assert state["phase_reviews"][0]["phase_n"] == 1
    assert state["phase_reviews"][0]["decision"] == "APPROVE"


def test_phase_review_consecutive_needs_changes(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)
    fake_review = "# Phase Review -- Phase 1\n\n## Decision\nNEEDS_CHANGES\n\n## Findings\n- none\n"

    # First NEEDS_CHANGES
    env = codex_stub(fake_review)
    r = _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)
    assert json.loads(r.stdout)["consecutive_needs_changes"] == 1

    # Make another commit so HEAD~1 is valid for second review
    (tmp_repo / "src.py").write_text("x = 3\n")
    subprocess.run(["git", "add", "src.py"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "phase 1 fix"], cwd=tmp_repo, check=True)

    # Second NEEDS_CHANGES
    env = codex_stub(fake_review)
    r = _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)
    assert json.loads(r.stdout)["consecutive_needs_changes"] == 2


def test_phase_review_memo_idempotent(tmp_repo: Path, codex_stub) -> None:
    run_id = _bootstrap_run(tmp_repo, codex_stub)
    fake_review = "# Phase Review -- Phase 1\n\n## Decision\nAPPROVE\n\n## Findings\n- none\n"

    env = codex_stub(fake_review)
    _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=env)
    r2 = _run(["phase-review", "--run", run_id, "--phase", "1"], cwd=tmp_repo, env_overrides=codex_stub(fake_review))
    js2 = json.loads(r2.stdout)
    assert js2["memo_appended"] is False  # second call is a no-op
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd python && python -m pytest tests/test_cli_phase_review.py -v
```
Expected: `SystemExit` or `error: argument cmd: invalid choice: 'phase-review'`

- [ ] **Step 3: Add phase-review to the CLI parser**

In `python/agent_loop/cli.py`, inside `build_parser()`, after the `memo-note` parser block (around line 148), add:

```python
# phase-review
p = sub.add_parser("phase-review", help="Codex quality review for a completed phase")
_add_common(p)
p.add_argument("--run", required=True)
p.add_argument("--phase", type=int, required=True)
```

- [ ] **Step 4: Implement _cmd_phase_review handler**

Add the following handler in `python/agent_loop/cli.py`, after `_cmd_memo_note` and before the `if __name__ == "__main__":` block:

```python
@register("phase-review")
def _cmd_phase_review(args) -> int:
    import re as _re
    import subprocess as _sp

    from agent_loop.codex_client import call_codex, CodexCallError
    from agent_loop.run_state import RunState

    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)

    # Collect phase diff from git (the phase commit)
    diff_result = _sp.run(
        ["git", "diff", "HEAD~1"],
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

    # Append memo (idempotent)
    memo_block = "\n".join([
        f"## Phase {args.phase} Review - {decision}",
        f"- Severity: high={severity_counts['high']}, med={severity_counts['med']}, low={severity_counts['low']}",
        f"- Carry forward: {'; '.join(carry_forward) if carry_forward else '(none)'}",
        "",
    ])
    appended = _append_memo_idempotent(
        run_dir / "memo.md",
        # Re-use existing helper: encode phase review as "round" with a synthetic key
        # to avoid duplicate appends. We use a high fake round number to avoid clash.
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
```

> **Note on `_append_memo_idempotent`:** The existing helper checks for `## Round N - ` pattern. Using `round_n=1000+phase` (e.g. 1001 for phase 1) ensures no collision with real round memos (rounds are typically 1–20) and keeps idempotency working without a new helper.

- [ ] **Step 5: Run tests to confirm they pass**

```
cd python && python -m pytest tests/test_cli_phase_review.py -v
```
Expected: all 6 tests PASS

- [ ] **Step 6: Run full test suite**

```
cd python && python -m pytest --tb=short -q
```
Expected: all tests pass

- [ ] **Step 7: Commit**

```
git add python/agent_loop/cli.py python/tests/test_cli_phase_review.py
git commit -m "feat(cli): add phase-review subcommand"
```

---

## Task 4: SKILL.md — round loop rewrite

**Files:**
- Modify: `skills/agent-loop/SKILL.md`

This task has no automated tests (skill docs are read by Claude at runtime). After editing, manually verify the logic reads consistently.

- [ ] **Step 1: Replace the Round loop section**

In `skills/agent-loop/SKILL.md`, replace the entire `## Round loop (repeat until APPROVE / PHASE_COMPLETE)` section with the following:

```markdown
## Round loop (repeat until phase-review APPROVE / run complete)

For each round N (starting at 1):

1. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" plan-round --run <run_id>`
   → JSON `{round_n, current_phase, total_phases, prompt_path, round_plan_path, worker_model, worker_model_reason, reasoning_effort, phase_complete_signal, subtasks, summary}`.
2. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" capture-baseline`
   → JSON `{baseline}`. Save the sha.
3. **Announce the round to the user** (one line, verbatim format, BEFORE dispatch):

   ```
   Phase <current_phase>/<total_phases> · Round N — worker (dominant): <worker_model> (<worker_model_reason>), effort: <reasoning_effort> — subtasks: <count> (implementation×<i>, verification×<v>)
   ```

4. `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" mark-dispatched --run <run_id> --round N`
5. **Dispatch worker subagents via Task tool** (same subtask fan-out rules as before — see Subtask roles and dispatch rules section).

   After all phases complete:
   Run: `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" record-diff --run <run_id> --round N --baseline <baseline>`
   Run: `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" mark-worker-done --run <run_id> --round N`

6. **Check verification outcome.**
   Check the CURRENT ROUND's `rounds/NN/progress.md` for any `[done] <id> verification: fail` line.

   - **Any verification FAIL found** → Do NOT proceed to phase judgment. Read failure summary from `shared/test-results.md` (first 30 lines). Dispatch a fix worker (next round). Loop back to step 1.

   - **All verification PASS (or no verification subtask)** → proceed to step 7.

7. **Supervisor phase-complete judgment.**

   Declare phase complete when BOTH hold:
   - All verification subtasks PASS (step 6 above).
   - `phase_complete_signal: true` in the round plan, OR all `acceptance_criteria` from the round plan are satisfied per test results.

   If a hard round cap is needed: after 8 consecutive rounds in a phase without declaring completion, escalate to the user.

   - **Phase NOT complete** → loop back to step 1 (next round).
   - **Phase complete** → proceed to step 8.

8. **Phase commit.**

   ```bash
   git add -- . ":(exclude).agent-loop"
   git commit -m "phase <current_phase>: <phase title from phases.json>"
   ```

   Show the commit hash to the user.

9. **Phase review.**

   `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" phase-review --run <run_id> --phase <current_phase>`
   → JSON `{decision, phase, review_path, severity_counts, carry_forward, consecutive_needs_changes}`.

10. **Branch on phase-review decision:**

    - **`APPROVE`** →
      `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" advance-phase --run <run_id>`
      → JSON `{previous_phase, current_phase, is_last_phase}`.
      - If `is_last_phase: true`: call `finalize`. END.
      - Else: announce phase advance and loop back to step 1 for the new phase.

    - **`NEEDS_CHANGES`** →
      **Auto-promote check** (treat as APPROVE if ALL hold):
      1. `severity_counts.high == 0`
      2. Every item in `carry_forward` contains only minor-signal words: "style", "nit", "minor", "optional", "cosmetic", "formatting"

      If all hold → treat as APPROVE (step above).

      **Supervisor judgment override**: may treat as APPROVE when: phase objective is met, flagged items are not blockers, tests pass. Before overriding, append rationale to `shared/knowledge.md` under `## Supervisor override — Phase <N> NEEDS_CHANGES → APPROVE (<date>)`.

      **User escalation** when either:
      - `consecutive_needs_changes >= 3`, OR
      - Supervisor cannot construct a defensible rationale.

      Otherwise: dispatch fix round(s). After implementation + verification pass:
      ```bash
      git add -- . ":(exclude).agent-loop"
      git commit -m "phase <current_phase>: fix <one-line summary>"
      ```
      Re-run `phase-review`. Repeat from step 9.
```

- [ ] **Step 2: Remove the old APPROVE / PHASE_COMPLETE / NEEDS_CHANGES branch section**

Delete (or replace) the old `## Round loop` step 7 branch section that referenced `review-round`, `APPROVE`, `PHASE_COMPLETE`, and `NEEDS_CHANGES` at round level. The new step 10 above is the replacement.

- [ ] **Step 3: Update the On continue section**

In `## On continue`, update the `advance_to_review` and `write_review` actions to map to `phase-review` instead of `review-round` when the phase commit exists. Add this case to the action list:

```markdown
- `phase_review_pending` → a phase commit was made but `phase-review` has not run yet.
  Check that `git log --oneline -1` shows a phase commit. Then:
  `Bash: "${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" phase-review --run <run_id> --phase <current_phase>`
  Branch on decision (step 10 of round loop).
```

- [ ] **Step 4: Verify SKILL.md reads consistently**

Read through the full updated SKILL.md and confirm:
- No references to `review-round` remain in the round loop (it can still appear in internal references section).
- Phase commit git command is present.
- `phase-review` subcommand is called with correct arguments.
- `advance-phase` is called after APPROVE (not `finalize` directly).

- [ ] **Step 5: Commit**

```
git add skills/agent-loop/SKILL.md
git commit -m "feat(skill): replace per-round review-round with phase-level review loop"
```

---

## Self-Review

**Spec coverage:**
- ✅ `plan-round` emits `phase_complete_signal` — Task 2
- ✅ Supervisor phase-complete judgment — Task 4 (SKILL.md step 7)
- ✅ `git add + git commit` at phase completion — Task 4 (SKILL.md step 8)
- ✅ `phase-review` subcommand — Task 3
- ✅ APPROVE → advance-phase — Task 4 (SKILL.md step 10)
- ✅ NEEDS_CHANGES → fix round → re-commit → re-review — Task 4 (SKILL.md step 10)
- ✅ 3× consecutive NEEDS_CHANGES → escalate — Task 4 (SKILL.md step 10) + RunState helper Task 1
- ✅ Backward compat (`phase_reviews` default empty) — Task 1 test_phase_reviews_load_backward_compat
- ✅ `review-round` subcommand kept for compat — not removed, just not called in round loop

**Gap noted:** `resume.py` / `determine_resume_action` does not yet handle `phase_review_pending` state. SKILL.md step 3 documents the manual continue path; a full resume.py update is a follow-on task.

**Placeholder scan:** No TBD or TODO in code blocks. All test assertions use concrete values.

**Type consistency:** `phase_reviews` list[dict] used consistently across RunState, cli.py handler, and tests.
