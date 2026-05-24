# Plan Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/ClaudeXCodex:plan` skill that lets users refine a plan through open conversation with Claude before handing it off to the existing agent-loop execution pipeline.

**Architecture:** Three layers of change — (1) CLI adds `--plan-file` to `init-run` and skips the Codex plan-draft call in `plan-init` when `plan.md` already exists, (2) a new `skills/plan/SKILL.md` drives the Claude-side planning conversation and writes the authorized plan file, (3) `skills/agent-loop/SKILL.md` gains a `--plan <file>` invocation path that checks the `authorized: CLAUDE_X_CODEX_PLAN` frontmatter token before entering the execution loop.

**Tech Stack:** Python 3.11+, pytest, argparse (existing CLI pattern), Markdown frontmatter (YAML subset), Claude Code SKILL.md skill system

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `python/agent_loop/cli.py` | `init-run --plan-file`; `plan-init` skip-draft logic |
| Create | `python/tests/test_init_run_plan_file.py` | Tests for `--plan-file` flag |
| Modify | `python/tests/test_cli_plan_init.py` | Tests for skip-draft behaviour |
| Create | `skills/plan/SKILL.md` | New `/ClaudeXCodex:plan` skill |
| Modify | `skills/agent-loop/SKILL.md` | `--plan <file>` invocation grammar + token check |

---

## Task 1: `init-run --plan-file` argument

**Files:**
- Modify: `python/agent_loop/cli.py:27-31` (init-run arg parser block)
- Modify: `python/agent_loop/cli.py:730-743` (`_cmd_init_run` function)
- Create: `python/tests/test_init_run_plan_file.py`

- [ ] **Step 1: Write the failing tests**

```python
# python/tests/test_init_run_plan_file.py
from __future__ import annotations
import json
from pathlib import Path
from tests.conftest import run_cli


def test_init_run_copies_plan_file(tmp_repo: Path) -> None:
    plan_file = tmp_repo / "my-design.md"
    plan_file.write_text("---\nauthorized: CLAUDE_X_CODEX_PLAN\n---\n# Design\n", encoding="utf-8")

    r = run_cli(
        ["init-run", "--goal", "smoke", "--slug", "smoke", "--plan-file", str(plan_file)],
        cwd=tmp_repo,
    )
    assert r.returncode == 0, r.stderr
    run_id = json.loads(r.stdout)["run_id"]
    plan_md = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    assert plan_md.exists()
    assert "CLAUDE_X_CODEX_PLAN" in plan_md.read_text(encoding="utf-8")


def test_init_run_without_plan_file_leaves_no_plan_md(tmp_repo: Path) -> None:
    r = run_cli(["init-run", "--goal", "smoke", "--slug", "smoke"], cwd=tmp_repo)
    assert r.returncode == 0, r.stderr
    run_id = json.loads(r.stdout)["run_id"]
    plan_md = tmp_repo / ".agent-loop" / "runs" / run_id / "plan.md"
    assert not plan_md.exists()


def test_init_run_missing_plan_file_errors(tmp_repo: Path) -> None:
    r = run_cli(
        ["init-run", "--goal", "smoke", "--slug", "smoke", "--plan-file", str(tmp_repo / "nonexistent.md")],
        cwd=tmp_repo,
    )
    assert r.returncode == 1
    assert "plan-file" in r.stderr.lower() or "not found" in r.stderr.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd python && pytest tests/test_init_run_plan_file.py -v
```
Expected: 3 FAILs (argument not yet recognised)

- [ ] **Step 3: Add `--plan-file` to the arg parser**

In `build_parser()`, find the `# init-run` block (line ~27) and add:

```python
    # init-run
    p = sub.add_parser("init-run", help="create new run directory")
    _add_common(p)
    p.add_argument("--goal", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--plan-file", default=None,
                   help="path to an already-authorized plan file; copied to plan.md in the run dir")
```

- [ ] **Step 4: Handle `--plan-file` in `_cmd_init_run`**

Replace the current `_cmd_init_run` body (lines 731-743):

```python
@register("init-run")
def _cmd_init_run(args) -> int:
    import shutil as _shutil
    repo = _Path(args.repo).resolve()
    run_id = _unique_run_id(repo, args.slug)
    run_dir = _run_dir(repo, run_id)
    (run_dir / "rounds").mkdir(parents=True, exist_ok=True)
    (run_dir / "shared").mkdir(parents=True, exist_ok=True)
    goal = _strip_routing_metadata(args.goal)
    (run_dir / "goal.md").write_text(goal + "\n", encoding="utf-8")
    (run_dir / "memo.md").write_text("# Round Memos\n\n", encoding="utf-8")

    plan_file = getattr(args, "plan_file", None)
    if plan_file is not None:
        src = _Path(plan_file)
        if not src.exists():
            print(f"plan-file not found: {plan_file}", file=sys.stderr)
            return 1
        _shutil.copy2(src, run_dir / "plan.md")

    rs = RunState.new(run_id=run_id, goal_path="goal.md", plan_path="plan.md")
    rs.save(run_dir / "state.json")
    _emit({"run_id": run_id, "run_dir": str(run_dir)})
    return 0
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd python && pytest tests/test_init_run_plan_file.py -v
```
Expected: 3 PASSes

- [ ] **Step 6: Verify existing init-run tests still pass**

```
cd python && pytest tests/test_cli_base.py tests/test_cli_handlers.py -v
```
Expected: all PASS

- [ ] **Step 7: Commit**

```
git add python/agent_loop/cli.py python/tests/test_init_run_plan_file.py
git commit -m "feat(init-run): add --plan-file to copy pre-authorized plan into run dir"
```

---

## Task 2: `plan-init` skip-draft when `plan.md` already exists

**Files:**
- Modify: `python/agent_loop/cli.py:762-843` (`_cmd_plan_init` function)
- Modify: `python/tests/test_cli_plan_init.py` (add two new tests)

The second Codex call (phases generation) uses the plan text as context. When skipping the first call, pass the pre-existing `plan.md` content instead.

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/test_cli_plan_init.py`:

```python
def test_plan_init_skips_draft_when_plan_md_exists(tmp_repo: Path) -> None:
    """plan-init must NOT call Codex for the plan draft when plan.md is pre-existing."""
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "skip"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]

    run_dir = tmp_repo / ".agent-loop" / "runs" / run_id
    existing_plan = "---\nauthorized: CLAUDE_X_CODEX_PLAN\n---\n# Pre-existing Plan\n\n## Tasks\n1. [ ] pre task\n"
    (run_dir / "plan.md").write_text(existing_plan, encoding="utf-8")

    phases_json = json.dumps({"phases": [{"phase_n": 1, "title": "Impl", "objective": "Do it.", "content": "# Phase 1\n"}]})
    # Only one Codex response needed (phases call only); a two-call stub would fail
    # if the draft call is incorrectly made.
    stub_path = tmp_repo / "codex_one.py"
    stub_path.write_text(
        "import json, sys\n"
        f"print(json.dumps({{'type': 'assistant_message', 'content': {phases_json!r}}}))\n",
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    env = {"AGENT_LOOP_CODEX_BIN": f'"{py}" "{stub_path.as_posix()}"'}
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r2.returncode == 0, r2.stderr

    out = json.loads(r2.stdout)
    assert out.get("plan_source") == "pre-existing"
    # plan.md content must be unchanged
    assert "Pre-existing Plan" in (run_dir / "plan.md").read_text(encoding="utf-8")


def test_plan_init_reports_codex_source_when_no_plan_md(tmp_repo: Path) -> None:
    r1 = _run(["init-run", "--goal", "smoke", "--slug", "codexsrc"], cwd=tmp_repo)
    assert r1.returncode == 0, r1.stderr
    run_id = json.loads(r1.stdout)["run_id"]

    phases_json = json.dumps({"phases": [{"phase_n": 1, "title": "Impl", "objective": "Do it.", "content": "# Phase 1\n"}]})
    env = _two_response_stub(tmp_repo, "# Plan\n\n## Tasks\n1. [ ] do thing", phases_json)
    r2 = _run(["plan-init", "--run", run_id], cwd=tmp_repo, env_overrides=env)
    assert r2.returncode == 0, r2.stderr
    out = json.loads(r2.stdout)
    assert out.get("plan_source") == "codex"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd python && pytest tests/test_cli_plan_init.py::test_plan_init_skips_draft_when_plan_md_exists tests/test_cli_plan_init.py::test_plan_init_reports_codex_source_when_no_plan_md -v
```
Expected: 2 FAILs

- [ ] **Step 3: Implement skip-draft logic in `_cmd_plan_init`**

Replace the `_cmd_plan_init` body (everything from `goal = ...` down to the `_emit` call):

```python
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

    # Second Codex call: generate phase docs from plan content.
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
```

- [ ] **Step 4: Run new tests to verify they pass**

```
cd python && pytest tests/test_cli_plan_init.py -v
```
Expected: all PASS (including the original 2 tests)

- [ ] **Step 5: Commit**

```
git add python/agent_loop/cli.py python/tests/test_cli_plan_init.py
git commit -m "feat(plan-init): skip Codex plan draft when plan.md already exists"
```

---

## Task 3: New `/ClaudeXCodex:plan` skill

**Files:**
- Create: `skills/plan/SKILL.md`

This is a supervisor-side skill (no Python). The skill drives a Claude–user conversation, writes the confirmed plan with the authorization frontmatter, then seamlessly invokes agent-loop.

- [ ] **Step 1: Create `skills/plan/SKILL.md`**

```markdown
---
name: plan
description: Refine a goal into an authorized plan through open conversation, then hand off to agent-loop for execution
---

# plan — Interactive Planning Skill

You are a planning facilitator. Your job is to help the user turn a rough goal into
a clear, confirmed plan document, then hand it off to agent-loop for execution.

## Invocation grammar

- `/ClaudeXCodex:plan <goal text>` — start a new planning conversation
- `/ClaudeXCodex:plan --file <path>` — load an existing file as starting context

## Authorization token

A plan is "execution-ready" when it contains the frontmatter line:

```
authorized: CLAUDE_X_CODEX_PLAN
```

**Never insert this token yourself** until the user explicitly confirms the plan is
final. Once inserted, agent-loop will skip the planning conversation and go straight
to execution.

## On start

1. If `--file <path>` was given:
   - Read the file.
   - If it already has `authorized: CLAUDE_X_CODEX_PLAN` in the frontmatter, tell
     the user "This plan is already authorized. Hand it off to agent-loop?" and wait.
   - Otherwise, show a brief summary and ask what they'd like to refine.

2. If a plain goal text was given:
   - Draft an initial plan in this format:

     ```markdown
     # Plan: <short title>

     ## Goal
     <one paragraph restating the goal in concrete terms>

     ## Phases
     1. **<Phase name>** — <one sentence objective>
     2. ...

     ## Open Questions
     - <anything you're uncertain about>
     ```

   - Present the draft to the user.
   - Ask: "What would you like to change or clarify?"

## Conversation rules

- **Never pressure the user to decide.** If they want to explore an idea, explore it.
- **Never use AskUserQuestion with forced choices** for plan content — free text is fine.
- Ask one open question at a time. Don't list five follow-ups.
- When the user seems to be converging ("looks good", "let's go", "this is fine"),
  summarize the final plan and ask: "Ready to authorize and start execution?"
- Keep refining until the user says yes.

## On user confirmation

1. Compose the final plan markdown:

   ```markdown
   ---
   authorized: CLAUDE_X_CODEX_PLAN
   ---

   # Plan: <title>

   ## Goal
   <confirmed goal>

   ## Phases
   1. **<Phase name>** — <objective>
   ...

   ## Notes
   <any constraints, risks, or context worth preserving>
   ```

2. Write the plan to a temp file (use the Bash tool):

   ```bash
   # Write to the target repo root (or current dir if not in a repo)
   cat > .agent-loop-plan.md << 'EOF'
   <plan content>
   EOF
   ```

3. Run `init-run` with `--plan-file`:

   ```bash
   "<CLAUDE_PLUGIN_ROOT>/bin/agent-loop" init-run \
     --goal "<one-line goal>" \
     --slug "<short-slug>" \
     --plan-file .agent-loop-plan.md
   ```

   → JSON `{run_id, run_dir}`. Remember `run_id`.

4. Run `plan-init` (phases generation only — plan.md already exists):

   ```bash
   "<CLAUDE_PLUGIN_ROOT>/bin/agent-loop" plan-init --run <run_id>
   ```

   Expected output: `"plan_source": "pre-existing"` in the JSON.

5. Tell the user: "Plan confirmed and phases generated. Starting execution…"

6. Invoke the agent-loop skill via the Skill tool, passing `continue` so it resumes
   the run that was just initialized:

   ```
   Skill("ClaudeXCodex:agent-loop", args="continue --run <run_id>")
   ```

## Forbidden

- Do not insert `authorized: CLAUDE_X_CODEX_PLAN` before the user confirms.
- Do not run `plan-round` or dispatch workers — that is agent-loop's job.
- Do not commit, push, or delete files.
```

- [ ] **Step 2: Verify the skill file is well-formed**

```bash
python -c "
from pathlib import Path
text = Path('skills/plan/SKILL.md').read_text(encoding='utf-8')
assert 'authorized: CLAUDE_X_CODEX_PLAN' in text
assert 'name: plan' in text
print('OK')
"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```
git add skills/plan/SKILL.md
git commit -m "feat(plan-skill): add /ClaudeXCodex:plan interactive planning skill"
```

---

## Task 4: `--plan <file>` invocation in `skills/agent-loop/SKILL.md`

**Files:**
- Modify: `skills/agent-loop/SKILL.md`

Two additions: (1) new invocation form in the grammar section, (2) a "On start with --plan" section before the existing "On start" section.

- [ ] **Step 1: Add `--plan <file>` to the invocation grammar**

Find the **Invocation grammar** section in `skills/agent-loop/SKILL.md` and append:

```markdown
- `/ClaudeXCodex:agent-loop --plan <path>` — start execution using an existing plan
  file. Checks the authorization token before proceeding.
```

- [ ] **Step 2: Add the `--plan <file>` flow**

Insert a new section immediately before `## On start` in `skills/agent-loop/SKILL.md`:

```markdown
## On start with `--plan <file>`

1. Read the first 10 lines of `<file>` (use `inspect` or `head`) to check for:
   ```
   authorized: CLAUDE_X_CODEX_PLAN
   ```
   in the YAML frontmatter block (between `---` delimiters at the top of the file).

2. **Token absent** → Tell the user:
   > "This file doesn't have the `authorized: CLAUDE_X_CODEX_PLAN` token.
   > Run `/ClaudeXCodex:plan --file <path>` to review and authorize it first."
   END.

3. **Token present** → Proceed:
   ```bash
   "<CLAUDE_PLUGIN_ROOT>/bin/agent-loop" init-run \
     --goal "<extract Goal section from file, or use filename as fallback>" \
     --slug "<short-slug from filename>" \
     --plan-file "<path>"
   ```
   → JSON `{run_id, run_dir}`. Remember `run_id`.

4. ```bash
   "<CLAUDE_PLUGIN_ROOT>/bin/agent-loop" plan-init --run <run_id>
   ```
   Expected: `"plan_source": "pre-existing"` in JSON.

5. Enter the normal round loop (see **Round loop** section below).
```

- [ ] **Step 3: Verify SKILL.md still passes the skill_docs test**

```
cd python && pytest tests/test_skill_docs.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```
git add skills/agent-loop/SKILL.md
git commit -m "feat(agent-loop): support --plan <file> invocation with authorization token check"
```

---

## Task 5: Full flow smoke test

Manual verification (no new test file — this covers the integration path).

- [ ] **Step 1: Run the full test suite**

```
cd python && pytest -x -q
```
Expected: all pass, no regressions.

- [ ] **Step 2: Verify `plan_source` field in a real init-run + plan-init call**

```bash
# In a temp git repo:
mkdir /tmp/smoke-plan && cd /tmp/smoke-plan && git init -q && git commit --allow-empty -m "seed"

PLAN=".agent-loop-plan.md"
cat > $PLAN << 'EOF'
---
authorized: CLAUDE_X_CODEX_PLAN
---

# Plan: smoke test

## Goal
Verify the plan-skill handoff end to end.

## Phases
1. **Smoke** — run one no-op round and approve
EOF

"<CLAUDE_PLUGIN_ROOT>/bin/agent-loop" init-run --goal "smoke" --slug "smoke" --plan-file $PLAN
# capture run_id from JSON output

"<CLAUDE_PLUGIN_ROOT>/bin/agent-loop" plan-init --run <run_id>
# verify "plan_source": "pre-existing" in output
```

- [ ] **Step 3: Commit (if any fixups needed)**

```
git add -p
git commit -m "fix: plan-skill smoke test fixups"
```
