# Claude-Entry Pivot — Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pivot agent-loop from "Codex plugin orchestrating Claude via SDK" to "Claude Code plugin where the main interactive Claude session is the supervisor, dispatches worker subagents via Task tool, and calls `codex exec --json` subprocess for planning + review."

**Architecture:**
- Supervisor = main Claude Code interactive session (subscription, lean context — only reads filenames + tiny status JSON)
- Planner/Reviewer = Codex CLI via `codex exec --json "<prompt>"` subprocess (subscription, headless-OK officially supported)
- Worker = Claude subagent via Task tool (subscription, fresh context per round, writes results to disk)
- Disk = `.agent-loop/runs/<id>/` (same as v1; memory persistence via `memo.md`, `shared/`, `progress.md`)

**Tech Stack:** Python 3.11+, `subprocess` (no SDK), `pytest`, existing modules (run_state, diff_capture, result_parser, progress_parser, shared_io, safety, payload, resume, scout, prompt_render). Removing `claude-agent-sdk` dependency. No OpenAI library — `codex` CLI does auth via subscription.

**Spec:** v1 spec at `docs/superpowers/specs/2026-05-22-agent-loop-codex-plugin-design.md` is superseded by this pivot. Update Section 2 (Architecture) of the spec or write a delta note at top — see Task 6.1 below.

## Policy Constraint (do not violate)

- **Claude Code subscription**: only used in interactive sessions. **No programmatic Claude calls** (`claude -p`, `claude-agent-sdk`, etc.). Task tool subagents inside an interactive session are OK — they're part of normal interactive use.
- **Codex CLI subscription**: `codex exec --json` headless mode is **officially supported** for automation. Use it via subprocess.
- Net effect: zero marginal API cost (both subscriptions); both interactive-shell ToS clean.

## Current State (assume as starting point)

- Repo: `/Users/juno/dev/my_auto_agent/`, git remote `pluruel/ClaudeXCodex`
- 56 tests passing under `python/.venv`
- Structure (current): `.codex-plugin/plugin.json`, `skills/agent-loop/*.md` (8 files), `skills/references/*.md` (5 files), `config/defaults.toml`, `python/agent_loop/*` (12 modules)
- All Python modules listed in Module Map of `python/README.md`
- `.github/workflows/ci.yml` exists (will need small update)

## Subagent-driven note

Many tasks below are independent (especially Phase 1 + Phase 3 markdown rewrites + Phase 4). The executor should dispatch concurrent subagents where the plan marks `[parallel-safe]`. Tasks marked `[sequential]` depend on earlier ones landing first.

---

## Phase 0 — Cleanup (sequential, must land first)

### Task 0.1: Delete dead SDK-based code  [sequential]

**Files to delete:**
- `python/agent_loop/sdk_runner.py`
- `python/tests/test_sdk_runner.py`
- `python/tests/test_cli_dispatch_continue.py` (replace with smaller `test_cli_continue.py` later — see Task 2.5)

**Files to modify:**
- `python/agent_loop/cli.py` — remove the `_cmd_dispatch` function (the entire `@register("dispatch")` block, including all its imports inside the function body)
- `python/agent_loop/cli.py` — remove the `"dispatch"` subparser from `build_parser()` (the block: `p = sub.add_parser("dispatch", help="invoke Claude SDK for current round")` and its 3 add_argument lines)
- `python/pyproject.toml` — remove `"claude-agent-sdk>=0.1.0"` from `dependencies` list (since we no longer use the SDK)

**Steps:**

- [ ] Step 1: Read `python/agent_loop/cli.py` and identify exact start/end lines of the `_cmd_dispatch` function. Delete the entire function body.
- [ ] Step 2: In `build_parser()` of the same file, delete the dispatch subparser block.
- [ ] Step 3: Delete `python/agent_loop/sdk_runner.py`.
- [ ] Step 4: Delete `python/tests/test_sdk_runner.py`.
- [ ] Step 5: Delete `python/tests/test_cli_dispatch_continue.py`.
- [ ] Step 6: Edit `python/pyproject.toml`: remove the `claude-agent-sdk` line from `dependencies`. Keep `[project.optional-dependencies] dev` block as-is.
- [ ] Step 7: Re-install package to drop the SDK dep:
  ```bash
  cd /Users/juno/dev/my_auto_agent/python
  .venv/bin/pip uninstall -y claude-agent-sdk
  .venv/bin/pip install -e ".[dev]"
  ```
- [ ] Step 8: Run remaining tests:
  ```bash
  source .venv/bin/activate
  pytest -q
  ```
  Expected: ~47 passed (56 − 2 from sdk_runner − 7 from cli_dispatch). If anything else breaks, investigate.
- [ ] Step 9: Commit:
  ```bash
  cd /Users/juno/dev/my_auto_agent
  git add -A python/
  git commit -m "chore: drop SDK-based dispatch (pivot to Claude-entry architecture)"
  ```

---

### Task 0.2: Delete Codex-plugin layout  [sequential, after 0.1]

**Files/dirs to delete:**
- `.codex-plugin/plugin.json` (will be replaced by `.claude-plugin/plugin.json` in Task 3.1)
- The `.codex-plugin/` directory entirely

**Steps:**

- [ ] Step 1: `rm -rf .codex-plugin`
- [ ] Step 2: Don't commit yet — Task 3.1 creates the replacement and commits together.

(Leaving `skills/` and `config/` in place; those move *into* the Claude plugin layout in Phase 3 but actually stay where they are since Claude Code uses the same `skills/<name>/SKILL.md` convention.)

---

## Phase 1 — Codex Client Module (parallel-safe)

### Task 1.1: `codex_client.py` — subprocess wrapper for `codex exec --json`  [parallel-safe]

**Files:**
- Create: `python/agent_loop/codex_client.py`
- Create: `python/tests/test_codex_client.py`

Strict TDD.

#### Step 1: Tests at `python/tests/test_codex_client.py`

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_loop.codex_client import (
    CodexCallError,
    CodexResult,
    call_codex,
)


def _fake_runner_yielding(events: list[dict]):
    """Return a runner that pretends `codex exec --json` emitted these events."""
    def _run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = "\n".join(json.dumps(e) for e in events) + "\n"
            stderr = ""
        return R()
    return _run


def test_call_codex_extracts_final_assistant_message() -> None:
    runner = _fake_runner_yielding([
        {"type": "thinking", "content": "hmm"},
        {"type": "tool_use", "name": "write_file"},
        {"type": "assistant_message", "content": "FINAL OUTPUT BODY"},
    ])
    res = call_codex("hello", runner=runner)
    assert isinstance(res, CodexResult)
    assert res.final_text == "FINAL OUTPUT BODY"
    assert res.events  # raw events preserved
    assert res.exit_code == 0


def test_call_codex_raises_on_nonzero_exit() -> None:
    def _bad_runner(cmd, **kwargs):
        class R:
            returncode = 2
            stdout = ""
            stderr = "auth required"
        return R()
    with pytest.raises(CodexCallError) as exc:
        call_codex("x", runner=_bad_runner)
    assert "auth required" in str(exc.value)


def test_call_codex_handles_no_assistant_message() -> None:
    runner = _fake_runner_yielding([
        {"type": "thinking", "content": "..."},
    ])
    with pytest.raises(CodexCallError) as exc:
        call_codex("x", runner=runner)
    assert "no assistant" in str(exc.value).lower()


def test_call_codex_skips_malformed_lines() -> None:
    def _runner(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = (
                '{"type": "thinking", "content": "ok"}\n'
                "not-json-garbage\n"
                '{"type": "assistant_message", "content": "DONE"}\n'
            )
            stderr = ""
        return R()
    res = call_codex("x", runner=_runner)
    assert res.final_text == "DONE"
```

#### Step 2: Run, expect ModuleNotFoundError

```bash
cd /Users/juno/dev/my_auto_agent/python
source .venv/bin/activate
pytest tests/test_codex_client.py -q
```

#### Step 3: Implement `python/agent_loop/codex_client.py`

```python
"""Wrapper around `codex exec --json` for headless invocation.

Usage:
    from agent_loop.codex_client import call_codex
    result = call_codex("Write a haiku about parsers.")
    print(result.final_text)

The default subprocess runner uses `subprocess.run(["codex", "exec", "--json", prompt])`.
Tests inject a fake runner to avoid the real CLI dependency.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class CodexCallError(RuntimeError):
    """Raised when `codex exec` fails or returns unusable output."""


@dataclass
class CodexResult:
    final_text: str
    events: list[dict[str, Any]] = field(default_factory=list)
    exit_code: int = 0
    stderr: str = ""


SubprocessRunner = Callable[..., Any]


def _default_runner(cmd: list[str], **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def call_codex(
    prompt: str,
    *,
    timeout: Optional[float] = None,
    extra_args: Optional[list[str]] = None,
    runner: Optional[SubprocessRunner] = None,
) -> CodexResult:
    """Invoke `codex exec --json` headless and return the final assistant message.

    Args:
        prompt: Prompt text to send to Codex.
        timeout: Optional subprocess timeout (seconds).
        extra_args: Extra args appended after `--json` (e.g., ``["--sandbox", "read-only"]``).
        runner: Override for the subprocess.run callable (used in tests).

    Returns:
        CodexResult with the final assistant text + raw events.

    Raises:
        CodexCallError: if the process exits non-zero or no assistant message is emitted.
    """
    run = runner or _default_runner
    cmd = ["codex", "exec", "--json"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(prompt)

    result = run(cmd, timeout=timeout) if timeout else run(cmd)
    exit_code = getattr(result, "returncode", 0)
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""

    if exit_code != 0:
        raise CodexCallError(
            f"codex exec exited {exit_code}: {stderr.strip() or '<no stderr>'}"
        )

    events: list[dict[str, Any]] = []
    final_text: Optional[str] = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue  # tolerate stray non-JSON lines
        events.append(evt)
        if evt.get("type") == "assistant_message":
            content = evt.get("content", "")
            if isinstance(content, str):
                final_text = content

    if final_text is None:
        raise CodexCallError(
            "codex exec produced no assistant message; "
            f"saw {len(events)} events."
        )

    return CodexResult(
        final_text=final_text,
        events=events,
        exit_code=exit_code,
        stderr=stderr,
    )
```

#### Step 4: Run, expect 4 passed

#### Step 5: Commit

```bash
git add python/agent_loop/codex_client.py python/tests/test_codex_client.py
git commit -m "feat(codex_client): subprocess wrapper for `codex exec --json`"
```

**Notes for the executor:**
- The `assistant_message` event type is a best guess based on documentation patterns. If the actual `codex exec --json` output uses different event names, ADJUST `call_codex` to match. The test fakes can be updated to mirror real shape. To check real format, run once manually: `echo "hi" | codex exec --json 2>&1 | head -20`.
- If the real format uses `{"type": "message", "role": "assistant", "content": "..."}` or similar, change the parser accordingly.

---

## Phase 2 — CLI Commands (sequential within, depends on Phase 1)

### Task 2.1: `cli.py` add `plan-init` subparser + handler  [sequential, after 1.1]

**Purpose:** On `/agent-loop start "<goal>"`, after `init-run`, supervisor calls `agent-loop plan-init --run X` once. Internally invokes Codex to draft the initial big plan and write `plan.md`. Returns a tiny JSON.

**Files modified:**
- `python/agent_loop/cli.py`
- `python/tests/test_cli_plan_init.py` (new)

#### Step 1: Test at `python/tests/test_cli_plan_init.py`

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch


def _run(args, cwd, env_overrides=None):
    import os
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False, env=env)


def test_plan_init_writes_plan_md(tmp_repo: Path, monkeypatch) -> None:
    # First, init a run
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "smoke"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]

    # Stub codex CLI: write a fake script that emits a single assistant_message
    bin_dir = tmp_repo / "fake_bin"
    bin_dir.mkdir()
    fake = bin_dir / "codex"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo \'{"type":"assistant_message","content":"# Plan\\n\\n## Tasks\\n1. [ ] do thing"}\'\n'
    )
    fake.chmod(0o755)
    new_path = f"{bin_dir}:" + __import__("os").environ["PATH"]

    r2 = _run(
        ["plan-init", "--run", run_id],
        cwd=tmp_repo,
        env_overrides={"PATH": new_path},
    )
    assert r2.returncode == 0, r2.stderr
    js = json.loads(r2.stdout)
    assert js["plan_path"].endswith("plan.md")
    plan_md = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    assert plan_md.exists()
    assert "# Plan" in plan_md.read_text()
```

#### Step 2: Run, expect failure (no `plan-init` subcommand)

#### Step 3: Modify `python/agent_loop/cli.py`

Inside `build_parser()`, add this subparser (somewhere among the others):
```python
    # plan-init
    p = sub.add_parser("plan-init", help="ask Codex to draft initial plan.md")
    _add_common(p)
    p.add_argument("--run", required=True)
```

Then add the handler near the others:

```python
@register("plan-init")
def _cmd_plan_init(args) -> int:
    from agent_loop.codex_client import call_codex, CodexCallError
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    goal = (run_dir / "goal.md").read_text().strip()
    meta_prompt = (
        "You are drafting the initial implementation plan for the following goal. "
        "Output ONLY a markdown document with two sections: \n\n"
        "# Plan\n\n## Tasks\n1. [ ] <first concrete task>\n2. [ ] ...\n\n"
        "## Notes\n<short strategic notes>\n\n"
        "Aim for 3-7 tasks, each completable in one round. No prose outside these sections.\n\n"
        f"## Goal\n{goal}\n"
    )
    try:
        res = call_codex(meta_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1
    plan_path = run_dir / "plan.md"
    plan_path.write_text(res.final_text)
    _emit({"plan_path": str(plan_path), "summary": "plan drafted"})
    return 0
```

#### Step 4: Re-install package (entry point already in place; no need but tests may rely on fresh `.venv/bin/agent-loop` — it's symlinked, no reinstall needed). Run:

```bash
cd python && source .venv/bin/activate && pytest tests/test_cli_plan_init.py -q
```

Expected: 1 passed.

#### Step 5: Commit

```bash
git add python/agent_loop/cli.py python/tests/test_cli_plan_init.py
git commit -m "feat(cli): plan-init subcommand drafts plan.md via codex exec"
```

---

### Task 2.2: `cli.py` add `plan-round` subparser + handler  [sequential, after 2.1]

**Purpose:** Per-round prompt generation. Codex reads goal + plan + memo + last review-payload (if any), drafts the Claude-prompt body for round N, writes to `rounds/NN/claude-prompt.md`, registers the round via `init-round`-equivalent logic.

**Files modified:**
- `python/agent_loop/cli.py`
- `python/tests/test_cli_plan_round.py` (new)

#### Step 1: Test

```python
from __future__ import annotations

import json
import subprocess
import os
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False, env=env)


def _stub_codex(repo: Path, payload: str) -> str:
    bin_dir = repo / "fake_bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "codex"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f"echo '{{\"type\":\"assistant_message\",\"content\":\"{payload}\"}}'\n"
    )
    fake.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}"


def test_plan_round_creates_round_dir_and_prompt(tmp_repo: Path) -> None:
    _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id_out = _run(["status"], cwd=tmp_repo)
    run_id = json.loads(run_id_out.stdout)["state"]["run_id"]
    # write a fake plan first
    plan = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    plan.write_text("# Plan\n\n## Tasks\n1. [ ] do A\n2. [ ] do B\n")

    path = _stub_codex(tmp_repo, "## Task\\nImplement A")
    r = _run(
        ["plan-round", "--run", run_id],
        cwd=tmp_repo,
        env_overrides={"PATH": path},
    )
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["round_n"] == 1
    pr = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01" / "claude-prompt.md"
    assert pr.exists()
    assert "Implement A" in pr.read_text()
```

#### Step 2: Run, expect failure

#### Step 3: Implement

Add to `build_parser()`:
```python
    # plan-round
    p = sub.add_parser("plan-round", help="ask Codex to draft next round prompt")
    _add_common(p)
    p.add_argument("--run", required=True)
```

Add handler:

```python
@register("plan-round")
def _cmd_plan_round(args) -> int:
    from agent_loop.codex_client import call_codex, CodexCallError
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    next_n = (rs.rounds[-1].n + 1) if rs.rounds else 1

    goal = (run_dir / "goal.md").read_text().strip()
    plan = (run_dir / "plan.md").read_text() if (run_dir / "plan.md").exists() else "(no plan.md)"
    memo = (run_dir / "memo.md").read_text() if (run_dir / "memo.md").exists() else ""
    prev_round = next_n - 1
    last_payload = ""
    if prev_round >= 1:
        ppath = run_dir / "rounds" / f"{prev_round:02d}" / "review-payload.json"
        if ppath.exists():
            last_payload = ppath.read_text()

    meta_prompt = f"""You are drafting the Claude worker prompt for round {next_n}.

Write ONLY the prompt body (markdown). It MUST include these sections:
- ## Carry-Forward From Previous Round
- ## Goal
- ## Task (this round)
- ## Required Reading (read these first, in order)
- ## Suggested Reading (only if needed)
- ## Out of Scope (do not Read/Edit/Write)
- ## External References
- ## Mandatory Outputs (progress.md, claude-result.md schema, shared/* discipline)
- ## Reading List Discipline
- ## Forbidden Actions
- ## claude-result.md schema

Use the goal, plan, memo, and previous review payload (if any) to fill these in.
Keep Required Reading to <= 4 paths. Out of Scope must cover unrelated top-level dirs.

## Goal
{goal}

## Plan
{plan}

## Memo So Far
{memo or "(empty — first round)"}

## Previous Review Payload (round {prev_round})
{last_payload or "(none — first round)"}
"""
    try:
        res = call_codex(meta_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1

    rd = run_dir / "rounds" / f"{next_n:02d}"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "claude-prompt.md").write_text(res.final_text)
    rs.start_round(n=next_n, started_at=_dt.datetime.utcnow().isoformat())
    rs.save(run_dir / "state.json")
    _emit({"round_n": next_n, "prompt_path": str(rd / "claude-prompt.md"),
           "summary": f"round {next_n} prompt drafted"})
    return 0
```

#### Step 4: Run tests
#### Step 5: Commit

```bash
git add python/agent_loop/cli.py python/tests/test_cli_plan_round.py
git commit -m "feat(cli): plan-round subcommand drafts per-round Claude prompt via codex"
```

---

### Task 2.3: `cli.py` add `review-round` subparser + handler  [sequential, after 2.2]

**Purpose:** Codex reviews a finished round. Reads result.md + diff + memo + payload, calls Codex to decide APPROVE/NEEDS_CHANGES/STOP_FOR_USER + write review body. Updates state.json and emits TINY decision JSON.

**Files modified:**
- `python/agent_loop/cli.py`
- `python/tests/test_cli_review_round.py` (new)

#### Step 1: Test

```python
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False, env=env)


def _stub_codex(repo: Path, content: str) -> str:
    bin_dir = repo / "fake_bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "codex"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f"echo '{{\"type\":\"assistant_message\",\"content\":{json.dumps(content)}}}'\n"
    )
    fake.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}"


def test_review_round_emits_decision(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    rd = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rd.mkdir(parents=True)
    (rd / "claude-prompt.md").write_text("hi")
    (rd / "claude-result.md").write_text(
        "# Claude Result\n\n## Summary\ndid stuff\n\n## Test Outcome\npass\n\n## Decision Hint\ncompleted\n\n## Requires User\nfalse\n"
    )
    (rd / "diff.patch").write_text("")
    # state needs round 1 registered
    state_p = tmp_repo / ".agent-loop" / "runs" / run_id / "state.json"
    state = json.loads(state_p.read_text())
    state["rounds"].append({"n":1,"phase":"claude_completed","decision":None,
                            "memo_lines":None,"started_at":"t","ended_at":None})
    state["current_round"] = 1
    state_p.write_text(json.dumps(state))

    fake_body = (
        "# Codex Review — Round 1\\n\\n"
        "## Decision\\nAPPROVE\\n\\n"
        "## Findings\\n- none\\n"
    )
    path = _stub_codex(tmp_repo, fake_body)
    r = _run(["review-round", "--run", run_id, "--round", "1"],
             cwd=tmp_repo, env_overrides={"PATH": path})
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["decision"] == "APPROVE"
    # review file written
    assert (rd / "codex-review.md").exists()
    # state updated
    state2 = json.loads(state_p.read_text())
    assert state2["rounds"][-1]["decision"] == "APPROVE"
    assert state2["rounds"][-1]["phase"] == "reviewed"
```

#### Step 2: Run, expect failure
#### Step 3: Implement

Add to `build_parser()`:
```python
    # review-round
    p = sub.add_parser("review-round", help="ask Codex to review a finished round")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)
```

Add handler:

```python
@register("review-round")
def _cmd_review_round(args) -> int:
    import re
    from agent_loop.codex_client import call_codex, CodexCallError
    from agent_loop.diff_capture import capture_baseline, capture_diff, compute_stats
    from agent_loop.payload import build_review_payload
    from agent_loop.result_parser import parse_result, ClaudeResult
    from agent_loop.safety import SafetyConfig, classify_diff_size
    from agent_loop.shared_io import snapshot_sizes, extract_delta, SharedDelta
    import tomllib

    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rd = run_dir / "rounds" / f"{args.round:02d}"

    cfg_path = repo / ".agent-loop" / "config.toml"
    if not cfg_path.exists():
        cfg_path = _Path(__file__).resolve().parents[2] / "config" / "defaults.toml"
    safety_cfg_data = tomllib.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    safety = SafetyConfig(
        bash_block_patterns=safety_cfg_data.get("safety", {}).get("bash_block", {}).get("patterns", []),
        sensitive_path_patterns=safety_cfg_data.get("safety", {}).get("sensitive_paths", {}).get("patterns", []),
        diff_warn_files=safety_cfg_data.get("safety", {}).get("diff_size", {}).get("warn_files", 15),
        diff_warn_lines=safety_cfg_data.get("safety", {}).get("diff_size", {}).get("warn_lines", 600),
    )

    # parse diff already on disk (the worker subagent should have left it; if not, capture)
    diff_path = rd / "diff.patch"
    if not diff_path.exists():
        # if missing, supervisor never captured baseline — produce empty
        diff_path.write_text("")
    diff = diff_path.read_text()
    stats = compute_stats(diff, sensitive_patterns=safety.sensitive_path_patterns)
    (rd / "diff-stats.json").write_text(_json.dumps(stats.__dict__, indent=2))

    safety_flags: list[str] = ["diff_has_sensitive"] if stats.sensitive_hits else []
    safety_flags += classify_diff_size(files=stats.files_changed,
                                       lines=stats.insertions + stats.deletions, cfg=safety)

    result_path = rd / "claude-result.md"
    if result_path.exists():
        result = parse_result(result_path)
    else:
        result = ClaudeResult(summary="(no claude-result.md found)")
        safety_flags.append("missing_claude_result")

    delta = SharedDelta()
    goal_summary = (run_dir / "goal.md").read_text().strip().splitlines()[0]
    payload = build_review_payload(
        out_path=rd / "review-payload.json",
        round_n=args.round,
        goal_summary=goal_summary,
        result=result,
        stats=stats,
        shared_delta=delta,
        artifact_paths={
            "result": str(result_path.relative_to(repo)) if result_path.exists() else "",
            "diff": str(diff_path.relative_to(repo)),
            "test_log": str((rd / "test-log.txt").relative_to(repo)) if (rd / "test-log.txt").exists() else "",
            "messages": "",
        },
        safety_flags=safety_flags,
    )

    memo = (run_dir / "memo.md").read_text() if (run_dir / "memo.md").exists() else ""

    meta_prompt = f"""You are reviewing one round of Claude's work.

Output a markdown review body following this schema EXACTLY:

# Codex Review — Round {args.round}

## Decision
APPROVE | NEEDS_CHANGES | STOP_FOR_USER

## Goal Alignment
<1-2 sentences>

## Findings
- [severity: high|med|low] <file:line if known> — <issue>

## Verification
- Tests: pass|fail|missing — <specifics>

## Risks
- <if any>

## Carry-Forward For Next Round
- <bullet, <= 3 items, quoted verbatim into next prompt>

## Final Notes
<optional>

Decision rules:
- STOP_FOR_USER if safety_flags non-empty, OR result.requires_user true, OR you see ambiguity needing human judgement.
- APPROVE if goal satisfied this round + tests pass + no flags.
- NEEDS_CHANGES otherwise (default).

## Payload For This Round
{_json.dumps(payload, indent=2)}

## Accumulated Memo So Far
{memo or "(empty)"}

## Claude's Result Report
{result_path.read_text() if result_path.exists() else "(missing)"}
"""
    try:
        res = call_codex(meta_prompt)
    except CodexCallError as e:
        print(f"codex error: {e}", file=sys.stderr)
        return 1

    (rd / "codex-review.md").write_text(res.final_text)

    # extract decision from review body (first APPROVE|NEEDS_CHANGES|STOP_FOR_USER on a line after "## Decision")
    m = re.search(r"##\s+Decision\s*\n\s*(APPROVE|NEEDS_CHANGES|STOP_FOR_USER)\s*",
                  res.final_text, re.IGNORECASE)
    decision = m.group(1).upper() if m else "STOP_FOR_USER"

    rs = RunState.load(run_dir / "state.json")
    rs.set_round_decision(args.round, decision)
    rs.set_round_phase(args.round, "reviewed")
    rs.save(run_dir / "state.json")

    _emit({
        "decision": decision,
        "review_path": str(rd / "codex-review.md"),
        "round": args.round,
        "safety_flags": safety_flags,
    })
    return 0
```

#### Step 4: Run tests
#### Step 5: Commit

```bash
git add python/agent_loop/cli.py python/tests/test_cli_review_round.py
git commit -m "feat(cli): review-round subcommand reviews via codex exec + emits decision JSON"
```

---

### Task 2.4: `cli.py` add `record-diff` subparser (worker hook)  [sequential, after 2.3]

**Purpose:** Worker subagent at end of its work calls `agent-loop record-diff --run X --round N --baseline <sha>` so the diff.patch is captured under the round dir (consistent across subagent termination paths). Optional but cleaner than relying on the worker's own bash.

**Files:**
- `python/agent_loop/cli.py`
- `python/tests/test_cli_record_diff.py`

#### Step 1: Test

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(args, cwd):
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False)


def test_record_diff_captures_and_writes(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    rd = tmp_repo / ".agent-loop" / "runs" / run_id / "rounds" / "01"
    rd.mkdir(parents=True)

    baseline = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_repo,
                              capture_output=True, text=True).stdout.strip()
    (tmp_repo / "added.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)

    r = _run(["record-diff", "--run", run_id, "--round", "1",
              "--baseline", baseline], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    diff = (rd / "diff.patch").read_text()
    assert "added.txt" in diff
```

#### Step 2: Run, expect failure
#### Step 3: Implement

Add subparser:
```python
    # record-diff
    p = sub.add_parser("record-diff", help="worker hook: capture diff for a round")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--baseline", required=True)
```

Handler:
```python
@register("record-diff")
def _cmd_record_diff(args) -> int:
    from agent_loop.diff_capture import capture_diff
    repo = _Path(args.repo).resolve()
    rd = _run_dir(repo, args.run) / "rounds" / f"{args.round:02d}"
    rd.mkdir(parents=True, exist_ok=True)
    diff = capture_diff(repo, args.baseline)
    (rd / "diff.patch").write_text(diff)
    _emit({"diff_path": str(rd / "diff.patch"), "size_bytes": len(diff)})
    return 0
```

#### Step 4: Tests pass
#### Step 5: Commit

```bash
git add python/agent_loop/cli.py python/tests/test_cli_record_diff.py
git commit -m "feat(cli): record-diff worker hook captures diff against baseline"
```

---

### Task 2.5: `cli.py` add `capture-baseline` helper  [parallel-safe after 2.4]

**Purpose:** Before dispatching the worker subagent, supervisor captures the baseline HEAD sha. The worker uses it later when calling `record-diff`.

**Files:**
- `python/agent_loop/cli.py`
- `python/tests/test_cli_capture_baseline.py`

#### Step 1: Test

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(args, cwd):
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False)


def test_capture_baseline_returns_sha(tmp_repo: Path) -> None:
    r = _run(["capture-baseline"], cwd=tmp_repo)
    assert r.returncode == 0
    js = json.loads(r.stdout)
    assert len(js["baseline"]) == 40
```

#### Step 2: Run, expect failure
#### Step 3: Implement

Add subparser:
```python
    # capture-baseline
    p = sub.add_parser("capture-baseline", help="emit current HEAD sha for the worker to use later")
    _add_common(p)
```

Handler:
```python
@register("capture-baseline")
def _cmd_capture_baseline(args) -> int:
    from agent_loop.diff_capture import capture_baseline
    repo = _Path(args.repo).resolve()
    sha = capture_baseline(repo)
    _emit({"baseline": sha})
    return 0
```

#### Step 4: Test passes
#### Step 5: Commit

```bash
git add python/agent_loop/cli.py python/tests/test_cli_capture_baseline.py
git commit -m "feat(cli): capture-baseline emits current HEAD sha for the round"
```

---

### Task 2.6: `cli.py` update `continue` handler resume map (no `dispatched` phase anymore)  [sequential, after 2.3]

**Purpose:** Old phase machine had `dispatched → claude_completed` because the SDK was synchronous within `dispatch`. New architecture: supervisor calls `plan-round` (phase `init`), then dispatches subagent (no Python-side phase shift during subagent run), then `review-round` (phase → `reviewed`). The `dispatched` and `claude_completed` phases become a single "worker_running" phase semantically OR can be retained but never persisted.

**Simpler:** keep `phases` list as-is in `run_state.py` (no schema break) but the new flow only uses:
- `planned` → `init` (plan-round writes prompt, calls `start_round`)
- `init` → (worker runs, no CLI call from supervisor's perspective until done)
- `claude_completed` → set by a new `mark-worker-done` subcommand (Task 2.7)
- `reviewed` → set by review-round
- `memo_written`, `completed` → set by append-memo (already in code)

Update `resume.py` to handle these gracefully (existing `dispatched` branch becomes mostly unreachable but kept for safety). No code change required if existing `resume.py` is permissive enough. Just verify tests still pass.

**Steps:**
- [ ] Step 1: Inspect `resume.py`. Existing test cases cover phases that still exist. No change needed.
- [ ] Step 2: Run `pytest tests/test_resume.py -q`. Expected: 5 passed.
- [ ] Step 3: If passing, no commit. If failing, fix and commit.

---

### Task 2.7: `cli.py` add `mark-worker-done` subcommand  [parallel-safe after 2.4]

**Purpose:** Worker subagent's final Bash call. Flips phase `init → claude_completed` so resume knows the worker finished.

**Files:**
- `python/agent_loop/cli.py`
- `python/tests/test_cli_mark_worker_done.py`

#### Step 1: Test

```python
import json
import subprocess
from pathlib import Path


def _run(args, cwd):
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False)


def test_mark_worker_done_flips_phase(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "g", "--slug", "s"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    # stub plan-round by directly registering round 1 in state
    from agent_loop.run_state import RunState
    state_p = tmp_repo / ".agent-loop" / "runs" / run_id / "state.json"
    rs = RunState.load(state_p)
    rs.start_round(n=1, started_at="t0")
    rs.save(state_p)

    r = _run(["mark-worker-done", "--run", run_id, "--round", "1"], cwd=tmp_repo)
    assert r.returncode == 0
    rs2 = RunState.load(state_p)
    assert rs2.rounds[-1].phase == "claude_completed"
```

#### Step 2: Run, expect failure
#### Step 3: Implement

Subparser:
```python
    p = sub.add_parser("mark-worker-done", help="worker hook: flip phase to claude_completed")
    _add_common(p)
    p.add_argument("--run", required=True)
    p.add_argument("--round", type=int, required=True)
```

Handler:
```python
@register("mark-worker-done")
def _cmd_mark_worker_done(args) -> int:
    repo = _Path(args.repo).resolve()
    run_dir = _run_dir(repo, args.run)
    rs = RunState.load(run_dir / "state.json")
    rs.set_round_phase(args.round, "claude_completed")
    rs.save(run_dir / "state.json")
    _emit({"round": args.round, "phase": "claude_completed"})
    return 0
```

#### Step 4: Tests pass (run full suite to confirm: `pytest -q`)
#### Step 5: Commit

```bash
git add python/agent_loop/cli.py python/tests/test_cli_mark_worker_done.py
git commit -m "feat(cli): mark-worker-done worker hook flips phase to claude_completed"
```

---

## Phase 3 — Plugin Layout for Claude Code (parallel-safe)

### Task 3.1: `.claude-plugin/plugin.json`  [sequential — must land before others reference it]

**Files:**
- Create: `.claude-plugin/plugin.json`

Content:

```json
{
  "name": "agent-loop",
  "displayName": "Agent Loop",
  "version": "0.2.0",
  "description": "Claude-supervised review loop with Codex (subscription-headless) as planner/reviewer and Claude subagents as workers",
  "author": {
    "name": "agent-loop authors"
  },
  "license": "MIT",
  "homepage": "https://github.com/pluruel/ClaudeXCodex",
  "repository": {
    "type": "git",
    "url": "https://github.com/pluruel/ClaudeXCodex.git"
  },
  "keywords": ["agent", "loop", "review", "codex", "automation"]
}
```

(Skills are auto-discovered by Claude Code from `skills/<name>/SKILL.md` relative to plugin root — no explicit listing needed in plugin.json.)

Commit after Task 3.2 lands together for clean diff.

---

### Task 3.2: Rewrite `skills/agent-loop/SKILL.md`  [parallel-safe after 3.1]

Full new content (replace existing file):

````markdown
---
name: agent-loop
description: When the user types `/agent-loop start "<goal>"` (or `/agent-loop continue`), this skill turns the current Claude session into the supervisor of a bounded review loop. Codex CLI (headless `codex exec --json`) does planning and review; Claude subagents (Task tool) do implementation; the supervisor (this Claude session) only reads tiny status JSON. Artifacts in `.agent-loop/runs/<id>/`.
---

# agent-loop — Claude Supervisor Skill

You are the supervisor of a bounded review loop. Your context must stay lean. The heavy thinking lives in Codex subprocess calls and in worker subagents; you only see filenames and tiny status JSON.

## Required reading on first invocation per session

- `references/claude-prompt-template.md` — what Codex drafts for each round
- `references/claude-result-schema.md` — what the worker writes back
- `references/review-payload-schema.md` — what Codex sees when reviewing

You do NOT need to re-read these every invocation; trust the schemas.

## Context discipline (mandatory)

- You never read full diffs, test logs, claude-result.md, claude-prompt.md, or codex-review.md.
- You only ingest the small JSON each CLI subcommand emits.
- For details, you can run `agent-loop inspect --round N --file X --lines a-b` to extract a slice.
- You never call `codex exec` or `codex` directly — always via `agent-loop plan-init|plan-round|review-round`.

## Loop protocol — On `start "<goal>"`

1. `Bash: agent-loop init-run --goal "<goal>" --slug "<short-slug>"`
   → JSON `{run_id, run_dir}`. Remember `run_id`.
2. `Bash: agent-loop plan-init --run <run_id>`
   → JSON `{plan_path, summary}`. (Codex drafted plan.md on disk.)
3. Enter round loop (next section).

## Round loop (repeat until APPROVE / STOP_FOR_USER)

For each round N (starting at 1):

1. `Bash: agent-loop plan-round --run <run_id>`
   → JSON `{round_n, prompt_path, summary}`. (Codex drafted the worker prompt.)
2. `Bash: agent-loop capture-baseline`
   → JSON `{baseline}`. Save the sha.
3. **Dispatch worker subagent via Task tool.** The subagent prompt:

   ```
   Task tool (general-purpose):
     description: "Worker round N for <run_id>"
     prompt: |
       Read .agent-loop/runs/<run_id>/rounds/NN/claude-prompt.md and implement
       what it specifies. Strict rules:
       - Follow the Required Reading list in that prompt. Do NOT read Out of Scope.
       - Append a line to .agent-loop/runs/<run_id>/rounds/NN/progress.md
         at each meaningful step ([done] / [doing] / [planned]).
       - Append durable facts to .agent-loop/runs/<run_id>/shared/knowledge.md.
       - Append design decisions to .agent-loop/runs/<run_id>/shared/decisions.md.
       - Append open questions to .agent-loop/runs/<run_id>/shared/open-questions.md.
       - At the end, write .agent-loop/runs/<run_id>/rounds/NN/claude-result.md
         following the schema in your prompt.
       - Run: `agent-loop record-diff --run <run_id> --round N --baseline <baseline>`
       - Run: `agent-loop mark-worker-done --run <run_id> --round N`
       - Forbidden: git commit, git push, rm -rf, sudo, db migrations,
         writes to .env / secrets / migrations.
       - Reply to the supervisor with ONE concise paragraph summarizing
         what changed (file count + brief outcome). Do NOT paste the full
         result.md or diff into your reply.
   ```

4. After Task tool returns, run: `Bash: agent-loop review-round --run <run_id> --round N`
   → JSON `{decision, review_path, safety_flags}`. Decision is one of APPROVE / NEEDS_CHANGES / STOP_FOR_USER.
5. `Bash: agent-loop append-memo --run <run_id> --round N --memo-file <path>` — supply a 5-10 line memo derived from the codex-review.md (you may briefly read codex-review.md if needed, but prefer using just the JSON decision and your own brief notes; remember context discipline).
6. Branch on `decision`:
   - `APPROVE` → `Bash: agent-loop finalize --run <run_id>`. Tell the user the run completed; point them at `final-report.md`. END.
   - `STOP_FOR_USER` → Tell the user the loop paused; show `safety_flags` and point at `codex-review.md`. END.
   - `NEEDS_CHANGES` → Loop back to step 1 (next round).

## Loop protocol — On `continue`

1. `Bash: agent-loop continue` (optionally `--run <id>`)
   → JSON `{action, notes, options, run_id, current_round}`.
2. Interpret `action`:
   - `plan_round` → start a fresh round at step 1 of the round loop
   - `claude_completed` (worker done but no review yet) → go straight to step 4 (review-round)
   - `reviewed` → step 5 (append-memo) and then branch
   - `user_confirm` → tell the user the options and wait

## Forbidden actions

- Never run `git commit`, `git push`, or any destructive command yourself.
- Never read full diff/result/log files into your context. Use `inspect` with narrow `--lines` only when the JSON status is insufficient.
- Never invent CLI behavior — if a subcommand's JSON doesn't match what you expected, stop and report to the user.

## File path conventions

- Run root: `<target_repo>/.agent-loop/runs/<run_id>/`
- Round dir: `<run_root>/rounds/NN/`
- Shared memory: `<run_root>/shared/`
````

---

### Task 3.3-3.9: Rewrite remaining sub-skill markdowns from supervisor perspective  [parallel-safe after 3.1]

Each one is rewritten. Below are the full bodies — overwrite the existing files.

#### Task 3.3: `skills/agent-loop/plan-from-goal.md`

This sub-skill is no longer used (the supervisor calls `agent-loop plan-init` which delegates to Codex). DELETE this file:

```bash
rm skills/agent-loop/plan-from-goal.md
```

#### Task 3.4: `skills/agent-loop/plan-from-review.md`

Also delegated to Codex (`agent-loop plan-round`). DELETE:

```bash
rm skills/agent-loop/plan-from-review.md
```

#### Task 3.5: `skills/agent-loop/round-review.md`

Delegated to Codex (`agent-loop review-round`). DELETE:

```bash
rm skills/agent-loop/round-review.md
```

#### Task 3.6: `skills/agent-loop/round-memo.md` (KEEP, simplify)

Supervisor still writes the memo (a few lines, derived from codex-review's decision and a short reflection). Rewrite:

````markdown
---
name: round-memo
description: Format for the 5-10 line memo the supervisor appends after each round via `agent-loop append-memo`.
---

# round-memo

After `agent-loop review-round` returns its decision, the supervisor writes a short memo and appends via `agent-loop append-memo --memo-file <tmp>`.

## Format (hard limits, total <= 10 lines)

```text
## Round N — <DECISION>
- Goal progress: <single line>
- Top risks: <up to 3 short bullets>
- Carry forward: <up to 3 short bullets, will be in next round's prompt>
- Sensitive: <"none" or one line>
- Diff size: <files=N, +X/-Y>
```

## Where to get the content

- Decision: from `agent-loop review-round` JSON (`decision` key).
- Goal progress / risks / carry forward: you may read `codex-review.md` for ONE quick pass if needed. Avoid re-reading it later — the memo is your compressed handoff.
- Diff size: from the review-round JSON (`safety_flags` mentions size flags; you can also get exact numbers from `agent-loop status` if needed).

## Rules

- <= 10 lines. <= 80 chars per bullet.
- "Carry forward" matters most: those bullets get quoted verbatim into the next prompt by `plan-round`.
- Do not quote findings verbatim — compress.

## Save destination

Write to a temp file (e.g., `<run_dir>/.tmp-memo.md`), then:

`Bash: agent-loop append-memo --run <run_id> --round N --memo-file <tmp_path>`

Delete the temp file after success.
````

#### Task 3.7: `skills/agent-loop/shared-knowledge.md` (KEEP, simplify)

Supervisor rarely touches shared/, but the file documents the rules. Rewrite:

````markdown
---
name: shared-knowledge
description: Read/append discipline for `<run_dir>/shared/` (the cross-round knowledge area). Mostly used by workers; the supervisor reads it only via `agent-loop inspect` if needed.
---

# shared-knowledge

`shared/` lives at `<run_dir>/shared/` and holds three append-only files:

- `knowledge.md` — facts about the target repo
- `decisions.md` — design decisions across rounds
- `open-questions.md` — unresolved questions; resolutions can be appended later

## Who writes

- **Workers (subagents)** append to all three during their rounds.
- **Codex** sees them indirectly: `agent-loop plan-round` and `review-round` may include slices when relevant.
- **You (supervisor)** rarely write. If you do (e.g., recording a strategic call you made yourself), use `Edit` to append a single line — do NOT overwrite.

## When to read

You almost never read these. If reasoning about a stale-looking pattern in a later round, you may run:

```
agent-loop inspect --run <id> --round 1 --file ../../shared/knowledge.md --lines 1-50
```

But default to trusting the round payload + memo.

## Format conventions

- `knowledge.md`: `- <one-line fact>`
- `decisions.md`: `- [<source>] <decision> (<short reason>)` where `<source>` is `round-N` or `codex-round-N` or `supervisor-round-N`.
- `open-questions.md`: `- <question>` (resolutions: indented `  - Resolved (round N): <answer>`).
````

#### Task 3.8: `skills/agent-loop/resume-run.md` (KEEP, lightly updated)

Rewrite to reflect new phase actions:

````markdown
---
name: resume-run
description: Interpret the JSON from `agent-loop continue` and resume the loop at the right step.
---

# resume-run

Invoked when the user types `/agent-loop continue [--run <id>]`.

## Step 1 — call the CLI

`Bash: agent-loop continue [--run <id>]`

Output JSON: `{action, notes, options, run_id, current_round}`.

## Step 2 — dispatch on `action`

| action | what to do |
|---|---|
| `plan_round` | Start a fresh round at SKILL.md round-loop step 1. |
| `dispatch` | Phase machine still says `init`. Re-dispatch the worker subagent (round dir + prompt are on disk). |
| `advance_to_review` | Worker finished but no review yet. Jump straight to `agent-loop review-round`. |
| `write_review` | Same as `advance_to_review`. |
| `write_memo` | Review is on disk but memo not appended. Compose memo, call `append-memo`. |
| `branch_decision` | Decision recorded, just branch (APPROVE / STOP_FOR_USER / NEEDS_CHANGES). |
| `finalize` | Call `agent-loop finalize`. |
| `user_confirm` | Show options to the user; act on their choice. |

## `user_confirm` (worker interrupted)

Tell the user:

> "Round N's worker did not complete. Pick one:
> - **redispatch** — re-dispatch a fresh worker subagent with the existing prompt
> - **abandon-round** — proceed to review with whatever exists on disk
> - **abort-run** — mark the run aborted"

Then:
- `redispatch` → return to SKILL.md round-loop step 2 (capture-baseline) then step 3 (Task tool dispatch)
- `abandon-round` → write a stub claude-result.md if missing, then `agent-loop review-round`
- `abort-run` → `agent-loop abort --run <id>` and stop

## Heartbeat

If `agent-loop continue` warns of a recent `last_heartbeat`, another session may be running. Ask the user before doing anything.
````

#### Task 3.9: `skills/agent-loop/safety-rules.md` (KEEP, updated)

Rewrite to remove SDK-hook language and reflect supervisor-side safety:

````markdown
---
name: safety-rules
description: Safety guardrails enforced by `agent-loop review-round` (post-dispatch scan) — what triggers them and how the supervisor reacts.
---

# safety-rules (supervisor-side reference)

Safety is enforced in two places:

1. **Worker subagent prompt** — the supervisor instructs the subagent NEVER to run `git commit/push`, `rm -rf`, `sudo`, DB migrations, or writes to sensitive paths. (No technical block; trust the subagent.)
2. **Post-dispatch scan** — `agent-loop review-round` reads the diff, computes stats, and emits `safety_flags` in its JSON output.

## Flags that `review-round` can emit

| Flag | Meaning |
|---|---|
| `diff_has_sensitive` | Diff includes paths matching `config/defaults.toml` `[safety.sensitive_paths]` patterns. |
| `diff_too_many_files` | Files changed > `safety.diff_size.warn_files` (default 15). |
| `diff_too_many_lines` | Lines changed > `safety.diff_size.warn_lines` (default 600). |
| `missing_claude_result` | Worker didn't write `claude-result.md`. |

## Supervisor reaction matrix

| Decision (from review-round JSON) | What to do |
|---|---|
| Any `safety_flags` non-empty | Treat as STOP_FOR_USER even if `decision == APPROVE` (defense in depth). |
| `STOP_FOR_USER` | Tell user, point at codex-review.md, end loop. |
| `APPROVE` (no flags) | `agent-loop finalize`. |
| `NEEDS_CHANGES` (no flags) | Next round. |

## What you (supervisor) must never do

- Run `git commit`, `git push`, or any destructive command yourself.
- Edit target repo source files. That's the worker's job.
- Read the user's full diff/result/test-log into context — use `agent-loop inspect` for narrow slices only.

## Repo-specific override

If `<target_repo>/.agent-loop/config.toml` exists, the Python core uses its values. You don't need to read this file; trust the payload's flags.
````

---

### Task 3.10: Reference docs — small updates  [parallel-safe]

Reference markdown in `skills/references/` is mostly stable. Update only:

#### `skills/references/review-payload-schema.md`

Already correct — the schema doesn't change.

#### `skills/references/claude-prompt-template.md`

Already correct.

#### `skills/references/claude-result-schema.md`

Already correct.

#### `skills/references/claude-progress-schema.md`

Already correct.

#### `skills/references/shared-knowledge-schema.md`

Already correct.

No file changes needed. Skip.

---

### Task 3.11: Commit plugin layout changes  [sequential, after 3.1–3.10]

```bash
cd /Users/juno/dev/my_auto_agent
git add .claude-plugin/ skills/
git rm -f --ignore-unmatch skills/agent-loop/plan-from-goal.md skills/agent-loop/plan-from-review.md skills/agent-loop/round-review.md
git commit -m "feat(plugin): pivot to Claude Code plugin layout + rewritten supervisor SKILL.md"
```

---

## Phase 4 — CI / Docs (parallel-safe)

### Task 4.1: Update `.github/workflows/ci.yml`  [parallel-safe]

Replace the `validate-plugin` job to look for `.claude-plugin/plugin.json` instead of `.codex-plugin/`:

```yaml
  validate-plugin:
    name: Validate Claude Code plugin layout
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Check required files exist
        run: |
          test -f .claude-plugin/plugin.json
          test -f skills/agent-loop/SKILL.md
          test -d skills/references
          test -f config/defaults.toml
          echo "Plugin layout OK"

      - name: Validate plugin.json is JSON
        run: |
          python -c "import json; json.load(open('.claude-plugin/plugin.json'))"

      - name: List skill files
        run: find skills -name '*.md' | sort
```

Release job's `tar --include` list should swap `.codex-plugin` → `.claude-plugin`:

```yaml
          tar --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
              --exclude='*.egg-info' --exclude='.agent-loop' --exclude='.pytest_cache' \
              --exclude='dist' \
              -czf dist/agent-loop-${{ github.ref_name }}.tar.gz \
              .claude-plugin skills config python docs README.md
```

Commit:

```bash
git add .github/workflows/ci.yml
git commit -m "ci: update validation + release tarball to use .claude-plugin layout"
```

---

### Task 4.2: Update root `README.md`  [parallel-safe]

Update the **Install** section to reflect Claude Code plugin and the subscription-only workflow.

Replace the entire Install section with:

```markdown
## Install

### Claude Code plugin (skills)

```bash
claude plugin marketplace add pluruel/ClaudeXCodex
```

### Python core (CLI tool, required)

```bash
git clone https://github.com/pluruel/ClaudeXCodex.git
cd ClaudeXCodex/python
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
export PATH="$PWD/.venv/bin:$PATH"
```

### Authentication (both subscription-based; no API keys needed)

```bash
claude login        # if you haven't already
codex login         # subscription headless requires this
```

Do NOT set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` if you want subscription auth.
```

Update **Quick usage** section to say:

```markdown
## Quick usage

In your target repo:

```
$ claude
> /agent-loop start "<your goal>"
```

The supervisor (this Claude session) will then call `codex exec` for planning/review and dispatch worker subagents (Task tool) for implementation. All artifacts in `.agent-loop/runs/<id>/`.

Resume after interruption:

```
> /agent-loop continue
```
```

Commit:

```bash
git add README.md
git commit -m "docs: README reflects Claude-entry architecture + subscription-only auth"
```

---

### Task 4.3: Update `docs/superpowers/specs/2026-05-22-agent-loop-codex-plugin-design.md`  [parallel-safe]

Prepend a delta note at the top of the file (after the existing date/author header). Use `Edit` to insert:

```markdown
> **2026-05-22 update — superseded for v2 by Claude-entry pivot.** See `docs/superpowers/plans/2026-05-22-claude-entry-pivot.md`. The original Codex-as-orchestrator + Claude-via-SDK design in this spec is no longer the implementation. Reason: Anthropic's June 14 restrictions on programmatic Claude (`claude -p` / SDK from outside) make the original design unworkable for subscription-only users. The pivot: Claude Code interactive session is the supervisor; Codex CLI (`codex exec --json`) does planning + review headlessly (officially supported under ChatGPT Plus); worker subagents come from Claude's Task tool inside the supervisor's interactive session.
```

Commit:

```bash
git add docs/superpowers/specs/2026-05-22-agent-loop-codex-plugin-design.md
git commit -m "docs(spec): note Claude-entry pivot supersedes original design"
```

---

## Phase 5 — Integration smoke test (sequential, after all)

### Task 5.1: End-to-end smoke test  [sequential, last]

**Files:**
- Create: `python/tests/test_integration_smoke_v2.py`
- (Optional) Delete: `python/tests/test_integration_smoke.py` (the old SDK-based version) — replace, since the SDK flow no longer exists.

```python
"""End-to-end: init-run → plan-init (stub codex) → plan-round (stub codex) → 
simulate worker artifacts on disk → review-round (stub codex) → append-memo → finalize.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _run(args, cwd, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(["agent-loop", *args], cwd=cwd, capture_output=True,
                          text=True, check=False, env=env)


def _stub_codex(repo: Path, content: str) -> str:
    bin_dir = repo / "fake_bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "codex"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f"echo '{{\"type\":\"assistant_message\",\"content\":{json.dumps(content)}}}'\n"
    )
    fake.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}"


def test_e2e_claude_entry_flow(tmp_repo: Path) -> None:
    # 1. init-run
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "smoke"], cwd=tmp_repo)
    run_id = json.loads(r1.stdout)["run_id"]
    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id

    # 2. plan-init (stub codex → returns a plan)
    path1 = _stub_codex(tmp_repo,
        "# Plan\\n\\n## Tasks\\n1. [ ] thing\\n\\n## Notes\\nshort")
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo,
              env_overrides={"PATH": path1})
    assert r2.returncode == 0, r2.stderr
    assert (run_dir / "plan.md").exists()

    # 3. plan-round
    r3 = _run(["plan-round", "--run", run_id], cwd=tmp_repo,
              env_overrides={"PATH": path1})
    assert r3.returncode == 0, r3.stderr
    assert (run_dir / "rounds" / "01" / "claude-prompt.md").exists()

    # 4. capture-baseline
    r4 = _run(["capture-baseline"], cwd=tmp_repo)
    baseline = json.loads(r4.stdout)["baseline"]

    # 5. simulate worker doing work + record-diff + mark-worker-done
    (tmp_repo / "src.txt").write_text("hello\n")
    subprocess.run(["git", "add", "src.txt"], cwd=tmp_repo, check=True)
    rd = run_dir / "rounds" / "01"
    (rd / "claude-result.md").write_text(
        "# Claude Result\n\n## Summary\nadded src.txt\n\n"
        "## Changed Files\n- src.txt\n\n## Test Outcome\npass\n\n"
        "## Decision Hint\ncompleted\n\n## Requires User\nfalse\n"
    )
    _run(["record-diff", "--run", run_id, "--round", "1",
          "--baseline", baseline], cwd=tmp_repo)
    _run(["mark-worker-done", "--run", run_id, "--round", "1"], cwd=tmp_repo)

    # 6. review-round (stub codex → returns APPROVE)
    review_md = (
        "# Codex Review — Round 1\\n\\n## Decision\\nAPPROVE\\n\\n"
        "## Findings\\n- none\\n"
    )
    path2 = _stub_codex(tmp_repo, review_md)
    r6 = _run(["review-round", "--run", run_id, "--round", "1"],
              cwd=tmp_repo, env_overrides={"PATH": path2})
    assert r6.returncode == 0, r6.stderr
    assert json.loads(r6.stdout)["decision"] == "APPROVE"

    # 7. append-memo
    memo = tmp_repo / "m.md"
    memo.write_text(
        "## Round 1 — APPROVE\n- Goal progress: done\n- Top risks: none\n"
        "- Carry forward: n/a\n- Sensitive: none\n- Diff size: 1 file\n"
    )
    _run(["append-memo", "--run", run_id, "--round", "1",
          "--memo-file", str(memo)], cwd=tmp_repo)

    # 8. finalize
    r8 = _run(["finalize", "--run", run_id], cwd=tmp_repo)
    assert r8.returncode == 0, r8.stderr
    assert (run_dir / "final-report.md").exists()

    state = json.loads((run_dir / "state.json").read_text())
    assert state["status"] == "completed"
```

Delete the old test:

```bash
rm python/tests/test_integration_smoke.py
```

Run:

```bash
cd python && source .venv/bin/activate && pytest tests/test_integration_smoke_v2.py -q
```

Expected: 1 passed.

Run full suite to confirm nothing else broke:

```bash
pytest -q
```

Commit:

```bash
git add python/tests/test_integration_smoke_v2.py
git rm python/tests/test_integration_smoke.py
git commit -m "test: e2e smoke for Claude-entry flow (plan-init → plan-round → worker stub → review-round → finalize)"
```

---

## Phase 6 — Push (sequential, last of all)

### Task 6.1: Final test pass + push

- [ ] Step 1: Full suite green:
  ```bash
  cd python && source .venv/bin/activate && pytest -q
  ```
  Expected: ~50 passed (count will be slightly lower than v1's 56 because we deleted some tests and added new ones).
- [ ] Step 2: Push:
  ```bash
  git push origin main
  ```
- [ ] Step 3: Check GH Actions tab for green build.

---

## Final verification checklist

- [ ] `.codex-plugin/` is gone
- [ ] `.claude-plugin/plugin.json` exists
- [ ] `sdk_runner.py` is gone
- [ ] `cli.py` has subcommands: init-run, init-round, plan-init, plan-round, capture-baseline, record-diff, mark-worker-done, review-round, write-review, append-memo, status, inspect, finalize, abort, continue, scout
- [ ] `cli.py` does NOT have `dispatch`
- [ ] `pyproject.toml` does NOT list `claude-agent-sdk` as a dep
- [ ] Full pytest pass
- [ ] GH Actions green on main
- [ ] README install instructions show `claude plugin marketplace add` and `claude login` + `codex login`

## Notes for the executor

- Some tasks above stub `codex` via a fake script in a temp `fake_bin/` dir + env PATH override. This is the cleanest way to test without invoking the real Codex CLI.
- The exact JSON event shape from `codex exec --json` is best-guess (`{"type": "assistant_message", "content": "..."}`). If different in practice, adjust `codex_client.py:_default_runner` + parser. Sanity test once manually: `echo "hi" | codex exec --json`.
- If `codex` is not on PATH during real use, `call_codex` will raise `FileNotFoundError` from subprocess — user should set up via `codex login` first.
- Subagent prompt in SKILL.md must be COMPLETE and self-contained — the worker subagent doesn't inherit the supervisor's context. Anything it needs to know must be in the prompt or in the `claude-prompt.md` file it reads.
- After this pivot lands, the v1 spec doc is annotated with the supersession note but the original design content stays for archival purposes.
