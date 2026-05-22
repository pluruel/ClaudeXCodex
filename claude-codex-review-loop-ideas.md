# Claude-Codex Review Loop

## Purpose

Build a reusable workflow controller where Claude Code acts as the implementation worker and Codex acts as the independent reviewer, prompt compiler, and loop controller.

The goal is not to replace Claude Code or create a full agent harness. The goal is to make each worker round reviewable, auditable, and easy to continue.

## Core Roles

- User: owns the original goal and final approval.
- Claude Code: performs implementation work in the target repository.
- Codex: reviews Claude's result, inspects diffs and logs, identifies risks, and writes the next Claude instruction.
- Workflow tool: stores run state, artifacts, prompts, reviews, and final reports.

## High-Level Flow

```text
User gives goal
  -> Codex creates Claude prompt
  -> Claude Code performs work
  -> User or script saves Claude result and test log
  -> Codex reviews result log + git diff + test log
  -> Codex either approves or creates next Claude prompt
  -> Repeat up to a bounded limit
  -> User performs final approval
```

## MVP Direction

Start with a Markdown-first CLI. Do not call Claude Code automatically in the first version.

This keeps the first version reusable across Claude Code, web Claude, Anthropic API, or any future worker. It also avoids prematurely coupling the tool to a specific agent runtime.

## Initial Command Shape

```text
agent-loop start "<goal>"
agent-loop review
agent-loop next
agent-loop finish
```

Possible later aliases:

```text
aal start "<goal>"
aal review
aal next
aal finish
```

## Run Directory

Each target repository gets its own local run history.

```text
<target-repo>/
  .agent-loop/
    runs/
      2026-05-22-short-task-name/
        goal.md
        state.json
        claude-prompt-01.md
        claude-result-01.md
        test-log-01.txt
        diff-01.patch
        codex-review-01.md
        claude-prompt-02.md
        final-report.md
```

The `.agent-loop/` directory should usually be ignored by git because it contains local run logs and review artifacts.

## Review Inputs

Each Codex review round should use:

- `goal.md`: the original user intent and acceptance criteria.
- `claude-result-N.md`: Claude's summary of what it changed, what it tested, and what remains uncertain.
- `test-log-N.txt`: relevant command output or manual verification notes.
- `diff-N.patch`: captured repository diff after Claude's work.
- `state.json`: current round, max rounds, status, and artifact paths.

## Review Criteria

Codex should review every round against:

1. Goal satisfaction.
2. Behavioral bugs or regressions visible in the diff.
3. Missing or weak tests and verification.
4. Scope creep or unrelated changes.
5. Safety rules and repository-specific constraints.
6. Whether another Claude round is required.

## Safety Rules

- No automatic commit or push.
- No automatic database migration generation or application.
- No destructive commands.
- Default maximum of 3 review loops.
- Stop and ask the user if the diff is too large or touches sensitive areas.
- Preserve unrelated user changes.
- Final merge, commit, or release remains user-approved.

## Worker Prompt Template

```text
Task:
<specific work for this Claude round>

Context:
<repo context, prior review findings, relevant files>

Required Changes:
- <must do>

Do Not:
- <constraints and forbidden actions>

Verification:
- <tests or checks to run>
- <manual behavior to confirm>

Output:
Save or report:
- changed files
- commands run
- test results
- unresolved risks
```

## Claude Result Template

```text
Summary:

Changed Files:

Commands Run:

Test Results:

Notes / Risks:

Questions for Reviewer:
```

## Codex Review Template

```text
Decision:
APPROVE | NEEDS_CHANGES | STOP_FOR_USER

Findings:
- [severity] file:line - issue

Verification:
- passed checks
- missing checks

Next Claude Prompt:
<only if NEEDS_CHANGES>

Final Notes:
```

## First Implementation Scope

Include:

- Create `.agent-loop/runs/<task-id>/`.
- Write `goal.md`.
- Write `state.json`.
- Generate `claude-prompt-01.md`.
- Generate empty `claude-result-01.md` and `test-log-01.txt` templates.
- Capture `git diff` as `diff-N.patch`.
- Generate review files from the current artifacts.
- Generate the next Claude prompt when review finds needed changes.

Exclude for v1:

- Direct Claude Code execution.
- Anthropic API integration.
- OpenCode integration.
- Automatic test execution.
- Automatic commit, push, PR, or migration operations.

## Later Extensions

- Claude Code CLI adapter.
- Git worktree isolation per run.
- Automatic test command suggestions.
- Repo-specific policy files.
- Web dashboard for run history.
- Structured JSON review output.
- GitHub PR review mode.
- Multiple reviewer agents for high-risk changes.

## Difference From OpenCode / Oh My OpenAgent

OpenCode is an agent execution runtime. Oh My OpenAgent is a multi-agent harness that tries to get the agent team to finish work with less human involvement.

This project is intentionally different:

- It keeps Claude Code as the worker instead of replacing it.
- It makes Codex an external reviewer instead of another worker.
- It treats review artifacts as the primary product.
- It favors bounded loops and user approval over unbounded autonomy.
- It is runtime-neutral in v1.

## Recommended Next Step

Write a formal design spec, then implement the Markdown-first CLI in a standalone reusable repository.

The first version should optimize for trust and auditability, not maximum automation.
