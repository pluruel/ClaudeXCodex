# agent-loop — Claude Code plugin for review loops with Codex

A Claude Code plugin where the interactive Claude session is the supervisor, dispatching worker subagents via the Task tool and using Codex CLI (headless `codex exec --json`) for planning and review. Durable artifacts go to `.agent-loop/runs/<id>/`; compact mode removes diff stats, progress logs, and diff patches after a clean review.

## Repo layout

- `.claude-plugin/plugin.json` — Claude Code plugin manifest
- `bin/` — plugin executables added to the Bash tool's `PATH` while the plugin is enabled
- `skills/` — plugin skills (`agent-loop/`, `references/`)
- `config/` — packaged plugin defaults (e.g. `defaults.toml`)
- `python/` — Python core (`python -m agent_loop` CLI, codex subprocess wrapper, state, safety)

## Artifact modes

Default compact mode keeps the human-facing record small:

- `goal.md`, `plan.md`, `memo.md`, `state.json`, `final-report.md`
- per round: `claude-prompt.md`, `claude-result.md`, `codex-review.md`, `review-payload.json`

Debug mode additionally preserves intermediate files such as `diff.patch`,
`diff-stats.json`, and worker `progress.md`. Enable it per target repo:

```toml
# .agent-loop/config.toml
[artifacts]
mode = "debug"
```

## Install

### Claude Code plugin (skills)

In Claude Code, run these slash commands in order:

```
/plugin marketplace add pluruel/ClaudeXCodex
/plugin install agent-loop@claudexcodex
/reload-plugins
```

After this, `/agent-loop <goal>` (start a new run; quotes optional) and `/agent-loop continue` (or just `/agent-loop` to resume the most recent run) become available.

#### Updating to the latest version

The local marketplace clone is cached. When upstream changes, refresh it with:

```
/plugin marketplace update claudexcodex
/plugin install agent-loop@claudexcodex
/reload-plugins
```

If `update` is unavailable or doesn't take effect, remove and re-add:

```
/plugin marketplace remove claudexcodex
/plugin marketplace add pluruel/ClaudeXCodex
/plugin install agent-loop@claudexcodex
```

#### Uninstall

```
/plugin uninstall agent-loop@claudexcodex
/plugin marketplace remove claudexcodex
```

#### Local development install (testing un-pushed changes)

Point the marketplace at your working tree instead of GitHub:

```
/plugin marketplace add c:\path\to\ClaudeXCodex
/plugin install agent-loop@claudexcodex
```

Any edits in your working tree are picked up on the next `/plugin install` or `/plugin marketplace update`.

### Python runtime (only requirement)

You just need Python 3.11+ on PATH. The CLI ships **inside the plugin** as a plain Python module and is exposed by the plugin's `bin/agent-loop` wrapper. The skill invokes `"${CLAUDE_PLUGIN_ROOT}/bin/agent-loop" ...` directly, so it does not depend on Bash `PATH`. No `pip install`, manual PATH setup, or separate clone is required.

(If you ARE working on the code locally and want to run the test suite, the optional dev install is:

```bash
git clone https://github.com/pluruel/ClaudeXCodex.git
cd ClaudeXCodex/python
python -m venv .venv
.venv/bin/pip install -e ".[dev]"            # Linux/Mac
.\.venv\Scripts\pip.exe install -e ".[dev]"  # Windows
.venv/bin/pytest -q                           # Linux/Mac
.\.venv\Scripts\pytest.exe -q                 # Windows
```

The editable install registers the `agent_loop` package on the venv's `sys.path`. Tests invoke `python -m agent_loop ...` directly; plugin runtime goes through `bin/agent-loop`.)

### Authentication (both subscription-based; no API keys needed)

```bash
claude login        # if you haven't already
codex login         # subscription headless requires this
```

Do NOT set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` if you want subscription auth.

## Quick usage

In your target repo:

```
$ claude
> /agent-loop <your goal here, quotes optional>
```

The supervisor (this Claude session) will then call `codex exec` for planning/review and dispatch worker subagents (Task tool) for implementation. All artifacts in `.agent-loop/runs/<id>/`.

Resume after interruption (no goal arg → resume most recent run):

```
> /agent-loop
```

## How it works

Three actors, three context budgets:

- **Codex** (`codex exec --json`, headless subprocess) — does the heavy planning and the per-round review. Each invocation is a fresh process; nothing accumulates.
- **Worker subagents** (Claude via Task tool) — do the implementation. Each dispatch is a fresh subagent context that only sees the round's `claude-prompt.md` plus what it chooses to read on disk. Workers reply to the supervisor with **exactly one line**: `OK` on success or `FAIL: <one sentence>` on failure. No summaries, no file lists.
- **Supervisor** (your interactive Claude session) — only sees small JSON blobs from CLI subcommands. The supervisor never reads `codex-review.md`, `claude-result.md`, full diffs, or test logs. Round memos (used as carry-forward into the next round's prompt) are auto-composed by `review-round` from Codex's structured review markdown — the supervisor just calls the subcommand.

This keeps the supervisor's per-turn token cost roughly constant regardless of how large the artifacts are or how many rounds you run.

### Per-round flow

For each round N, the supervisor runs (in order):

1. `plan-round` — Codex drafts `rounds/NN/claude-prompt.md`
2. `capture-baseline` — record HEAD sha
3. `mark-dispatched` — record that the worker handoff is starting, so interrupted runs can resume accurately
4. **Dispatch worker subagent** via Task tool — worker reads the prompt, implements, runs `record-diff` + `mark-worker-done`, replies `OK` / `FAIL`
5. `review-round` — Codex reviews the diff + result; auto-parses Goal Alignment / Risks / Carry-Forward sections; appends the round memo to `memo.md`; transitions phase through `reviewed → memo_written → completed` in a single call
6. Branch on `decision`:
   - `APPROVE` → `finalize`, point user at `final-report.md`
   - `STOP_FOR_USER` → pause, surface `safety_flags`
   - `NEEDS_CHANGES` → loop back to step 1

`append-memo` is a manual override and is no longer part of the normal flow.

## Status

v2 — Claude-entry architecture. The supervisor is Claude; Codex is invoked as a subprocess for planning + review. Both run on subscription (Pro/Max for Claude; ChatGPT Plus for Codex headless).

Recent: per-round memos are now auto-composed by `review-round` (no supervisor reads of review artifacts), and worker replies are constrained to one line — both changes hold supervisor token usage flat across long runs.
