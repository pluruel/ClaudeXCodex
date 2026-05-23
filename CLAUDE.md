# CLAUDE.md — ClaudeXCodex 플러그인 저장소

이 저장소는 Claude Code 플러그인 `ClaudeXCodex`의 소스다. 설치본은 사용자의 플러그인 캐시(`~/.claude/plugins/cache/claudexcodex/ClaudeXCodex/<version>/`)에 복제되며, 이 저장소의 `skills/`, `bin/`, `python/`, `config/`가 그대로 배포된다.

## 슬래시 명령 네이밍

플러그인이 노출하는 슬래시 명령은 다음 형태다:

```
/ClaudeXCodex:agent-loop [goal]
```

`:` 앞은 **플러그인 이름**(`.claude-plugin/plugin.json`의 `name = "ClaudeXCodex"`), 뒤는 **스킬 이름**(`skills/agent-loop/SKILL.md`의 frontmatter `name = "agent-loop"`)이다. Claude Code의 `plugin:skill` 네임스페이싱 규약을 따른다.

(과거에는 플러그인 이름이 `agent-loop`였고 슬래시 명령이 `/agent-loop:agent-loop`로 같은 단어가 반복돼 보였다. 0.3.x에서 플러그인 이름을 `ClaudeXCodex`로 바꿔 중복을 해소했다. 스킬 이름과 CLI 바이너리 이름(`bin/agent-loop`), 산출물 디렉토리(`.agent-loop/`)는 그대로 유지된다.)

## 이름 분류 (헷갈리지 말 것)

| 종류 | 값 | 위치 | 변경 시 영향 |
| --- | --- | --- | --- |
| 마켓플레이스 이름 | `claudexcodex` | `.claude-plugin/marketplace.json` `name` | `/plugin marketplace add/remove/update <이 이름>` |
| 플러그인 이름 | `ClaudeXCodex` | `.claude-plugin/plugin.json` `name`, `marketplace.json` `plugins[0].name` | 슬래시 명령 prefix, `/plugin install <이 이름>@claudexcodex`, 캐시 경로 `cache/claudexcodex/ClaudeXCodex/` |
| 스킬 이름 | `agent-loop` | `skills/agent-loop/SKILL.md` frontmatter `name`, 디렉토리명 | 슬래시 명령 suffix |
| CLI 바이너리 | `bin/agent-loop` | 파일 경로 | `${CLAUDE_PLUGIN_ROOT}/bin/agent-loop` 호출 |
| Python 패키지 | `agent_loop` | `python/agent_loop/` | `python -m agent_loop` |
| 산출물 디렉토리 | `.agent-loop/runs/<id>/` | 타깃 저장소 안 | 사용자가 보는 결과물 경로 |

## 핵심 파일

- 플러그인 매니페스트: `.claude-plugin/plugin.json` (`name = "ClaudeXCodex"`)
- 마켓플레이스: `.claude-plugin/marketplace.json` (`name = "claudexcodex"`)
- 메인 스킬: `skills/agent-loop/SKILL.md`
- CLI 진입점: `bin/agent-loop` → `python/agent_loop/__main__.py`
- 산출물 루트: `<target_repo>/.agent-loop/runs/<run_id>/`

## 작업 시 유의

- 스킬 본문(`SKILL.md`)을 고칠 때는 설치본이 아닌 이 저장소(`C:/dev/ClaudeXCodex/skills/agent-loop/SKILL.md`)를 편집한다. 캐시본은 `/plugin marketplace update claudexcodex` + `/plugin install ClaudeXCodex@claudexcodex`로 다시 받는다.
- SKILL.md 안의 경로는 `${CLAUDE_PLUGIN_ROOT}` 템플릿이라 캐시 위치/플러그인 이름이 바뀌어도 자동으로 따라간다. 절대 경로를 새로 박지 말 것.
- 플러그인 이름을 또 바꾸면 `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, SKILL.md/resume-run.md의 슬래시 명령 예시, README의 설치 명령, `.github/workflows/ci.yml`의 릴리스 tarball 이름까지 함께 갱신해야 한다.
