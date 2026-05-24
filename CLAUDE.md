# CLAUDE.md — ClaudeXCodex Plugin Repository

This repository is the source for the Claude Code plugin `ClaudeXCodex`. The installed copy is cloned into the user's plugin cache (`~/.claude/plugins/cache/claudexcodex/ClaudeXCodex/<version>/`), and the `skills/`, `bin/`, `python/`, and `config/` directories are deployed as-is.

## Slash Command Naming

The slash command exposed by this plugin takes the form:

```
/ClaudeXCodex:agent-loop [goal]
```

The part before `:` is the **plugin name** (`name = "ClaudeXCodex"` in `.claude-plugin/plugin.json`); the part after is the **skill name** (`name = "agent-loop"` in `skills/agent-loop/SKILL.md` frontmatter). This follows Claude Code's `plugin:skill` namespacing convention.

(Previously the plugin name was `agent-loop`, making the slash command `/agent-loop:agent-loop` with the same word repeated. In 0.3.x the plugin name was changed to `ClaudeXCodex` to eliminate the duplication. The skill name, CLI binary name (`bin/agent-loop`), and artifact directory (`.agent-loop/`) remain unchanged.)

## Name Classification (don't confuse these)

| Kind | Value | Location | Impact if changed |
| --- | --- | --- | --- |
| Marketplace name | `claudexcodex` | `.claude-plugin/marketplace.json` `name` | `/plugin marketplace add/remove/update <this name>` |
| Plugin name | `ClaudeXCodex` | `.claude-plugin/plugin.json` `name`, `marketplace.json` `plugins[0].name` | Slash command prefix, `/plugin install <this name>@claudexcodex`, cache path `cache/claudexcodex/ClaudeXCodex/` |
| Skill name | `agent-loop` | `skills/agent-loop/SKILL.md` frontmatter `name`, directory name | Slash command suffix |
| CLI binary | `bin/agent-loop` | File path | `${CLAUDE_PLUGIN_ROOT}/bin/agent-loop` invocation |
| Python package | `agent_loop` | `python/agent_loop/` | `python -m agent_loop` |
| Artifact directory | `.agent-loop/runs/<id>/` | Inside the target repo | Path users see for results |

## Key Files

- Plugin manifest: `.claude-plugin/plugin.json` (`name = "ClaudeXCodex"`)
- Marketplace: `.claude-plugin/marketplace.json` (`name = "claudexcodex"`)
- Main skill: `skills/agent-loop/SKILL.md`
- CLI entry point: `bin/agent-loop` → `python/agent_loop/__main__.py`
- Artifact root: `<target_repo>/.agent-loop/runs/<run_id>/`

## Working Notes

- When editing skill content (`SKILL.md`), edit this repository (`C:/dev/ClaudeXCodex/skills/agent-loop/SKILL.md`), not the installed cache copy. Refresh the cache with `/plugin marketplace update claudexcodex` + `/plugin install ClaudeXCodex@claudexcodex`.
- Paths inside SKILL.md use the `${CLAUDE_PLUGIN_ROOT}` template, so they automatically follow cache location or plugin name changes. Do not hardcode absolute paths.
- If the plugin name is changed again, update `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, slash command examples in SKILL.md/resume-run.md, install commands in README, and the release tarball name in `.github/workflows/ci.yml`.
