# Agent-Loop Codex Plugin — Design Spec

날짜: 2026-05-22
저자: brainstorming session output
선행 문서: `claude-codex-review-loop-ideas.md`

## 1. Purpose & Scope

Codex CLI에 로드되는 플러그인을 만든다. Codex가 이 플러그인을 통해:

- 사용자 goal을 받아 한 세션 안에서 Claude Code를 worker로 반복 dispatch
- 각 라운드 결과를 review하고, 필요한 경우 다음 라운드 prompt를 생성
- 라운드 산출물을 디스크에 audit 가능한 형태로 남김
- 종료 시 사람이 검토·머지할 수 있는 final report 생성

**핵심 제약**

- **Codex 토큰 최소화**: target repo 파일을 직접 안 읽고 (scout JSON 신호만), raw diff/log를 컨텍스트에 끌어오지 않음
- **Claude 잉여 컨텍스트 최소화**: Codex가 reading list를 curate해서 prompt에 박음. Claude는 광범위 탐색 금지 — 좁게 정해진 set만 Read
- **공통 메모리**: `shared/`를 통해 Codex와 Claude가 라운드 가로질러 지식 누적
- **세션 중단 복원**: 토큰 끊김·인터럽트 후 `/agent-loop continue`로 디스크에서 복원
- **점진적 저장**: Claude는 실행 중 progress.md·shared/에 계속 push — 라운드 끝에서만 기록하지 않음
- 자동 모드: 라운드 사이 사용자 개입 없음. 종료는 Codex 결정(APPROVE / STOP_FOR_USER) 또는 사용자 인터럽트
- Worker 측은 Claude Agent SDK(Python)로 호출
- 안전선: 자동 commit/push/migration/destructive 명령 일체 차단
- v1에 max_rounds 강제 cap 없음 (안전선 trip만이 자동 정지 트리거)

## 2. Architecture

세 층으로 분리:

**Codex (orchestration / reasoning)**
- Codex CLI 세션에 플러그인 로드
- 역할: goal 파싱, 라운드 컨트롤, review 추론, round-memo 작성
- target repo 파일 직접 안 읽음 — Python core가 추출해서 작은 JSON으로 전달

**Python core (`agent_loop/`)**
- Claude Agent SDK 호출, `.agent-loop/runs/...` 상태/IO, git diff 캡처, prompt 렌더링, safety check
- Codex가 Bash로 호출하는 CLI 엔트리포인트 제공
- 모든 명령은 작은 JSON을 stdout에 — 무거운 출력은 디스크에만 기록하고 경로만 반환

**Claude (worker)**
- `claude_agent_sdk`로 매 라운드 새 세션
- 라운드별로 enabled skills/plugins, allowed_tools, permission_mode, cwd 지정
- 작업 끝나면 정해진 스키마로 `claude-result.md` 작성

**경계 규칙**
- Codex ↔ Python: JSON only (라운드당 1–2KB 목표)
- Python ↔ Claude: SDK 메시지 + 디스크 파일 (Codex 안 봄)
- Codex가 raw diff/log 필요하면 `agent-loop inspect`로 좁은 쿼리만 허용

## 3. Plugin Layout

```text
agent-loop/
  plugin.json
  skills/
    agent-loop/
      SKILL.md                       # 메인: /agent-loop "<goal>" 흐름
      plan-from-goal.md              # Round 1 prompt 생성 (goal → task decomposition)
      plan-from-review.md            # Round N+1 prompt 생성 (review + remaining plan)
      round-review.md                # review 단계 규율
      round-memo.md                  # 라운드 끝 압축 메모 규율
      shared-knowledge.md            # shared/ 영역 read/write 규율 (Codex 측)
      resume-run.md                  # /agent-loop continue 복원 로직
      safety-rules.md                # diff 크기·민감 경로·정지 조건
    references/
      claude-prompt-template.md
      claude-result-schema.md
      claude-progress-schema.md      # rounds/NN/progress.md 형식
      shared-knowledge-schema.md     # shared/ 파일 형식
      review-payload-schema.md
  python/
    .venv/                           # 개발용 (gitignore)
    agent_loop/
      __init__.py
      cli.py                         # `agent-loop` 엔트리포인트
      run_state.py                   # state.json read/write (phase 추적 포함)
      resume.py                      # 인터럽트된 run 감지·복원
      scout.py                       # target repo 신호 추출 (파일트리, grep, 헤더) → JSON
      shared_io.py                   # shared/ 영역 read/append helpers
      sdk_runner.py                  # claude_agent_sdk 호출 (progress hook 포함)
      diff_capture.py                # git diff → diff.patch + diff-stats.json
      prompt_render.py               # 템플릿 + context → claude-prompt.md
      result_parser.py               # claude-result.md → 요약 필드
      progress_parser.py             # progress.md tail → phase 추정
      payload.py                     # review-payload.json 빌더
      safety.py                      # diff 크기·민감 경로 검사·hook 정의
    pyproject.toml                   # 의존성: claude-agent-sdk
    README.md                        # `.venv` 설치 안내
  config/
    defaults.toml                    # 안전 패턴, diff 임계치
```

설치: `cd python && python -m venv .venv && .venv/bin/pip install -e .`

Sub-skill 분할 이유: SKILL.md 통째로 매번 로드하면 토큰 낭비. review/memo/safety는 필요한 시점에만 참조.

## 4. Run Lifecycle & On-Disk Layout

```text
<target-repo>/
  .agent-loop/
    config.toml                          # repo별 오버라이드
    runs/
      2026-05-22-add-auth-middleware/
        goal.md
        state.json
        plan.md                          # 초기 task decomposition (plan-from-goal 산출)
        memo.md                          # 누적 round-memo (append-only)
        shared/                          # 공통 메모리 (Codex + Claude 모두 read/write)
          knowledge.md                   # target repo 사실·구조·컨벤션 (append-only)
          decisions.md                   # 라운드 가로지르는 설계 결정 (append-only)
          open-questions.md              # 미해결 질문 + 상태
        rounds/
          01/
            claude-prompt.md
            progress.md                  # Claude 실행 중 점진적 append (체크포인트)
            claude-result.md
            test-log.txt
            diff.patch
            diff-stats.json
            codex-review.md
            review-payload.json
          02/
            ...
        final-report.md                  # finish 시 작성
```

**공통 메모리 영역 (`shared/`)**

라운드 가로질러 살아남는 지식 저장소. 둘 다 자유롭게 read·append (overwrite 금지로 충돌 회피):

- `knowledge.md`: target repo에 관한 사실 — 파일 위치, 컨벤션, 의존성, gotcha. 발견 즉시 append.
- `decisions.md`: 설계 결정 — "JWT 선택 (session 대신, 이유: ...)". 결정 시점에 append.
- `open-questions.md`: 답 못 한 질문 — 추후 답이 생기면 같은 파일에 resolution append.

**왜 분리하나**
- 라운드별 산출물(claude-result.md 등)은 한 라운드의 *완결된 보고서*. 라운드 끝나면 그 라운드 컨텍스트.
- `shared/`는 *프로젝트 전체 지식 누적*. 라운드 N에서 Claude가 발견한 것이 라운드 N+5에서도 유효해야 함.
- Codex가 review·plan 단계에서 shared/를 매번 참조 → 라운드를 거듭할수록 학습된 컨텍스트로 prompt 품질 상승.

**Claude 실행 중 점진적 저장 (`rounds/NN/progress.md`)**

Claude가 작업 *진행 중* append하는 체크포인트 로그. 형식 (worker system_prompt가 강제):

```text
- [done] 2026-05-22T10:15:03 — src/auth/ 구조 파악 (session.py가 기존 middleware)
- [done] 2026-05-22T10:16:42 — shared/knowledge.md에 인증 구조 append
- [doing] 2026-05-22T10:17:10 — src/auth/middleware.py 작성 시작
- [planned] JWT verify 함수 + 만료 처리
- [planned] tests/auth/test_middleware.py
```

- 각 의미 있는 step마다 한 줄 append
- `[doing]`은 항상 0~1개 (현재 진행)
- 토큰 끊김·인터럽트 시 마지막 `[done]` + `[doing]`이 어디까지 진행됐는지 알려줌 → resume 결정 근거

**state.json (얇게 유지, resume 가능)**

```json
{
  "run_id": "2026-05-22-add-auth-middleware",
  "goal_path": "goal.md",
  "plan_path": "plan.md",
  "current_round": 2,
  "status": "in_progress",
  "rounds": [
    {
      "n": 1,
      "phase": "completed",
      "decision": "NEEDS_CHANGES",
      "memo_lines": "3-7",
      "started_at": "2026-05-22T09:50:01",
      "ended_at": "2026-05-22T10:08:33"
    },
    {
      "n": 2,
      "phase": "dispatched",
      "decision": null,
      "memo_lines": null,
      "started_at": "2026-05-22T10:09:00",
      "ended_at": null
    }
  ],
  "safety_flags": [],
  "last_heartbeat": "2026-05-22T10:17:10"
}
```

**라운드 phase 머신**
```
planned → init → dispatched → claude_completed → reviewed → memo_written → completed
```
- 어떤 phase에서 인터럽트되든 `/agent-loop continue`가 이 값 + progress.md tail로 다음 step 결정
- `last_heartbeat`는 dispatch 중 Python core가 progress.md write 감지마다 갱신 → "정말 죽었나" 휴리스틱

**memo.md (핵심 토큰 절약 장치)**

append-only. 다음 라운드 시작 시 raw artifact는 안 불러오고 memo.md만 읽음. 라운드당 5–10줄:

```text
## Round 1 — NEEDS_CHANGES
- Goal progress: middleware skeleton 추가, JWT 검증 누락
- Top risks: token expiry 미처리, error path 미테스트
- Carry forward: JWT verify + error 케이스 테스트
- Sensitive: 없음
- Diff size: 4 files, +120 -8
```

**한 라운드의 Codex 시점 시퀀스**

```text
0a. (Round 1) Codex가 plan-from-goal 적용:
    - Bash: agent-loop scout --goal "<...>" --keywords "..."  → JSON {file_tree, grep_hits, headers}
    - Codex가 scout 결과 + shared/knowledge.md(있다면) 보고
      plan.md (task list) + Round 1 prompt 본문 + reading_curation 생성
0b. (Round N+1) Codex가 plan-from-review 적용:
    - 필요 시 Bash: agent-loop scout --goal "<remaining task>" --since-round N  (선택)
    - 이전 review-payload + memo.md + plan.md 남은 task + shared/ + scout(있다면) →
      다음 prompt 본문 + reading_curation
1. Bash: agent-loop init-round --prompt <stdin>    → JSON {round_n, prompt_path}
   (phase = init → dispatched)
2. Bash: agent-loop dispatch --round N             → JSON {result_summary, diff_summary, sensitive_flag, paths, shared_delta}
   (phase = dispatched → claude_completed; Claude는 실행 중 progress.md·shared/ 점진적 append)
3. Codex 읽기: memo.md + review-payload.json + claude-result.md + shared_delta
4. Codex 추론: decision + findings (round-review skill)
5. Bash: agent-loop write-review --decision X
   (phase = reviewed)
6. Codex 추론: round-memo 작성 (round-memo skill)
7. Bash: agent-loop append-memo
   (phase = memo_written → completed)
8. 분기:
   - APPROVE      → Bash: agent-loop finalize → 종료
   - STOP_FOR_USER → 사용자 대기 (다음 사용자 입력까지)
   - NEEDS_CHANGES → 0b로 복귀 (같은 세션, plan-from-review)
```

**`shared_delta`**: dispatch 직후 Python이 shared/* 파일들의 이번 라운드 신규 append 부분만 추출해서 payload에 포함. Codex가 shared/ 전체를 매번 안 읽어도 됨.

## 5. Slash Commands

| Command | 역할 |
|---|---|
| `/agent-loop start "<goal>"` | 새 run 생성. goal.md, state.json 초기화. **자동으로 라운드 사이클 반복** until APPROVE/STOP_FOR_USER. |
| `/agent-loop continue [--run <id>]` | 인터럽트된 run 복원. state.json의 phase + progress.md tail 보고 적절한 step부터 재개. dispatch 중 죽었으면 사용자에게 "재dispatch / abandon-round / abort-run" 선택지. resume-run skill 본문 참조. |
| `/agent-loop status` | 현재/지정 run의 state.json + memo.md 마지막 N줄. dispatch 안 함. |
| `/agent-loop inspect --round N --file <name> [--lines a-b]` | 디스크 산출물 부분만 컨텍스트로. Codex 자신이 review 중 호출하기도, 사용자도 호출 가능. |
| `/agent-loop finish` | 강제 마무리(사용자가 수동 호출). 내부적으로 `agent-loop finalize` 실행 → final-report.md 작성, status=completed. APPROVE 시에는 Codex가 자동으로 같은 내부 명령 호출. |
| `/agent-loop abort` | 중단. 파일 보존, status=aborted. |

## 6. Claude SDK Invocation

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

options = ClaudeAgentOptions(
    cwd=target_repo,
    system_prompt=worker_system_prompt + AUTO_MODE_DIRECTIVE,
    permission_mode="bypassPermissions",
    allowed_tools=["Read","Edit","Write","Bash","Glob","Grep","TodoWrite","Task"],
    plugins=plugin_config_for_round,    # 라운드 task 성격에 맞춰 선택
    setting_sources=[],                  # 사용자 글로벌 설정 안 빨아옴
    max_turns=40,
    hooks=safety_hooks,
)

async with ClaudeSDKClient(options=options) as claude:
    await claude.query(prompt_text)
    async for msg in claude.receive_response():
        persist_message_to_disk(msg)
```

**`AUTO_MODE_DIRECTIVE` (worker system prompt 일부)**

```text
## Auto Mode Active
Work without stopping for clarifying questions. When you'd normally pause to check,
make the reasonable call and keep going. There is no human to ask; you are being
driven by an upstream controller (Codex) that will review your work after this round.
If something is genuinely blocked, document it in claude-result.md "open_questions"
and finish what you can.
```

**Codex가 curate하는 Reading List (prompt에 박힘)**

**왜**: 양방향 토큰 절약. (1) Codex는 target repo 본문을 안 봐도 됨 — scout 신호만 보고 결정. (2) Claude도 광범위 Glob/Grep으로 헤매지 않음 — Codex가 골라준 좁은 set만 Read해서 잉여 컨텍스트 없음. Codex의 의도와 Claude 실행이 정렬됨.

매 라운드 Claude prompt에는 다음 섹션이 포함됨 (plan-from-goal·plan-from-review가 생성):

```text
## Required Reading (read these first, in order)
- src/auth/session.py — 기존 middleware 패턴
- shared/knowledge.md  lines 1-40 — 인증 모듈 사실
- shared/decisions.md (entire) — 이전 결정 회상

## Suggested Reading (필요 시)
- tests/auth/ — 기존 테스트 패턴
- src/config/auth.toml

## Out of Scope (이 라운드에 건드리지 말 것)
- src/billing/, src/admin/, docs/legacy/

## References (외부 자료)
- pyjwt 공식 문서: token verify 부분
```

Codex가 scout 결과 + shared/knowledge.md를 보고 이 리스트를 짬. Claude는 자유 탐색 대신 이 가이드에 따름 — 헤매지 않고 토큰 절약, Codex의 의도와 정렬.

**Worker system prompt 핵심 조항**
- 작업 끝나면 `claude-result.md` 를 스키마대로 작성 (스키마 inline)
- **prompt의 Reading List를 따른다 (잉여 컨텍스트 금지)**:
  - Required는 작업 시작 전 모두 Read
  - Suggested는 필요 시
  - Out of Scope는 건드리지 않음 (Read·Edit·Write 모두)
  - **광범위 Glob/Grep 자제**: 코드베이스 전반을 훑는 식의 탐색 금지. Reading List 안의 디렉토리·파일을 좁게 다룰 때만 Glob/Grep 사용
  - 추가 탐색이 정말 필요하면 직접 읽지 말고 `claude-result.md`의 `requested_reading`에 기록 → 다음 라운드 Codex가 검토 후 Reading List에 추가
- 테스트/검증 명령은 직접 Bash로 실행, stdout/stderr를 `test-log.txt`에 append
- 커밋·푸시·migration·rm·destructive 금지 (hook으로도 이중 차단)
- 수정한 파일 목록을 result에 명시
- **점진적 진척 기록 (mandatory)**: 의미 있는 step(파일 탐색·결정·작성·테스트)마다 `rounds/<this_round>/progress.md`에 한 줄 append. `[done]` / `[doing]` / `[planned]` 마커 사용. `[doing]`은 항상 0~1개.
- **공통 메모리 활용 (mandatory)**:
  - target repo 구조·컨벤션·의존성 등 *이번 라운드 후에도 유효한* 사실은 발견 즉시 `shared/knowledge.md`에 append (사용자가 알려준 패턴, 라이브러리 버전, 디렉토리 의미 등)
  - 설계 결정 (대안 중 선택, trade-off)은 `shared/decisions.md`에 append
  - 답 못 한 의문은 `shared/open-questions.md`에 append; 추후 답이 생기면 같은 파일에 resolution append
  - 시작 시 항상 shared/* 를 먼저 Read — 이전 라운드 발견을 활용할 의무
- **너의 컨텍스트는 라운드 끝에 사라진다** — Codex가 다음 라운드를 위해 새 너를 띄울 때, 너만 알던 정보는 디스크에 없으면 잃어버린다. 의식적으로 외재화하라.

**라운드 간 carry-forward**

전 라운드 round-memo의 "Carry forward" 항목을 다음 라운드 worker system_prompt 머리에 박음. 라운드 간 Claude 컨텍스트는 공유 안 함(새 세션) — 압축 인계만.

**Output 캡처**
- SDK 메시지 스트림 → `claude-messages.jsonl` (디스크 only)
- `claude-result.md` (Claude 자작) → 스키마 파싱
- baseline `git rev-parse HEAD` 기록 → 끝나면 `git diff` → `diff.patch` + `diff-stats.json`

## 7. Review Payload & Token Discipline

**`review-payload.json` 스키마** (라운드당 1개, 2KB 이하)

```json
{
  "round": 2,
  "goal_summary": "Add JWT auth middleware with token expiry handling",
  "claude_decision_hint": "completed" | "incomplete" | "blocked",
  "result_summary": {
    "changed_files": ["src/auth/middleware.py", "tests/auth/test_middleware.py"],
    "commands_run": ["pytest tests/auth -x", "ruff check src/auth"],
    "test_outcome": "pass" | "fail" | "partial" | "not_run",
    "claude_notes": "JWT verify 추가, expiry 테스트 1건",
    "open_questions": ["refresh token 처리는 다음 라운드?"],
    "requested_reading": ["src/sessions/store.py", "tests/conftest.py"]
  },
  "diff_summary": {
    "files_changed": 2,
    "insertions": 87,
    "deletions": 4,
    "by_file": [
      {"path": "src/auth/middleware.py", "ins": 62, "del": 4, "sensitive": false},
      {"path": "tests/auth/test_middleware.py", "ins": 25, "del": 0, "sensitive": false}
    ],
    "sensitive_hits": []
  },
  "safety_flags": [],
  "artifact_paths": {
    "result": ".agent-loop/runs/<id>/rounds/02/claude-result.md",
    "diff": ".agent-loop/runs/<id>/rounds/02/diff.patch",
    "test_log": ".agent-loop/runs/<id>/rounds/02/test-log.txt",
    "messages": ".agent-loop/runs/<id>/rounds/02/claude-messages.jsonl"
  }
}
```

**Codex가 review 단계에서 받는 컨텍스트 (라운드당)**
- `round-review.md` skill 본문 (~1KB)
- `review-payload.json` (~2KB, shared_delta 포함)
- 누적 `memo.md` (라운드당 5–10줄)
- 이번 라운드 `claude-result.md` 본문 (~1–3KB, 통째로 받음 — review 추론 1차 입력)
- `shared_delta` (이번 라운드 shared/* append 부분만 — 보통 < 2KB)

**Codex가 plan-from-review 단계에서 추가로 받는 것**
- `plan.md`의 남은 task 섹션 (수 줄)
- `shared/decisions.md` 마지막 N개 (이전 라운드 결정 회상)

→ 라운드당 신규 컨텍스트 ~7–12KB / 약 4K tokens. 라운드 거듭해도 누적은 평탄(shared는 delta로, memo는 압축으로).

**Codex가 받지 않는 것 (디스크 only)**
- `diff.patch` 원본
- `test-log.txt` 원본
- `claude-messages.jsonl`
- 이전 라운드들의 raw 산출물
- `shared/*` 의 *전체 본문* — delta만 받고, 전체가 필요하면 `inspect`로 좁게

**`inspect` 사용**
Codex가 review 중 좁은 부분만 필요할 때:
```text
agent-loop inspect --round 2 --file diff.patch --path src/auth/middleware.py --lines 12-40
```

**round-memo 규율** (5–10줄 hard limit)
- Goal progress: 한 줄
- Top risks: 최대 3 bullet
- Carry forward: ≤3 bullet (다음 라운드 system_prompt에 박힘)
- Sensitive: 트립 여부
- Diff size: 한 줄

## 8. Safety Guardrails

3중 안전선:

| 층 | 무엇을 막나 | 위치 |
|---|---|---|
| 1. SDK options | allowed_tools 화이트리스트 | `sdk_runner.py` |
| 2. PreToolUse hook | destructive Bash/Edit/Write 차단 | `sdk_runner.py` hook |
| 3. Post-dispatch | diff 크기·민감 경로 → STOP_FOR_USER | `safety.py` |

**금지 명령 정규식 (defaults.toml)**

```toml
[safety.bash_block]
patterns = [
  "^\\s*git\\s+(commit|push|merge|rebase|reset\\s+--hard|clean\\s+-f)",
  "^\\s*rm\\s+-rf",
  "^\\s*sudo\\b",
  "alembic\\s+upgrade",
  "prisma\\s+migrate\\s+(deploy|reset)",
  "psql.*-c\\s+['\"]?(DROP|TRUNCATE|DELETE)",
  "^\\s*curl.*\\|\\s*(sh|bash)",
  "^\\s*npm\\s+publish",
  "^\\s*docker\\s+(push|rmi)",
]

[safety.sensitive_paths]
patterns = [
  "\\.env(\\..+)?$",
  "secrets/",
  "credentials\\.",
  "/migrations/",
  "/alembic/versions/",
  "ci/", ".github/workflows/",
  "Dockerfile", "docker-compose\\.",
  "package-lock\\.json$", "poetry\\.lock$", "uv\\.lock$",
]

[safety.diff_size]
warn_files = 15
warn_lines = 600
```

- Edit/Write가 sensitive path 건드림 → hard block (hook)
- Diff에 sensitive path hit → post-scan warning → safety_flags에 추가 → STOP_FOR_USER

**`STOP_FOR_USER` 트리거**
- safety_flags 비어있지 않음
- Codex review 결정이 STOP_FOR_USER
- SDK 호출 실패 (2회 retry 후)
- Claude가 `claude-result.md`에 `requires_user: true` 표기

**종료 흐름 (slash `/agent-loop finish` 또는 APPROVE 자동 — 둘 다 내부 `agent-loop finalize` 실행)**
1. `final-report.md` 작성 (memo.md 전체 + 최종 라운드 기반)
2. `state.json` status → `completed`
3. **git commit·push·PR 일체 안 함** — 사용자의 영역
4. 출력: 변경 파일 목록, 라운드별 decision, final-report 경로

**git/디스크 안전**
- `.agent-loop/`는 사용자에게 `.gitignore` 추가 *안내만* (자동 수정 안 함)
- baseline은 commit hash 기록 + `git diff <hash>` — stash·branch 안 만짐
- working tree에 영향 zero

**Sanity check (`/agent-loop start` 진입 시)**
- `git rev-parse --is-inside-work-tree`
- `.venv` 활성 확인 (개발모드)
- `claude_agent_sdk` import 가능

실패 시 친절한 에러로 abort.

## 8.5. Resume Semantics (`/agent-loop continue`)

토큰 끊김·세션 인터럽트·시스템 재시작 후 복원.

**감지**
- `agent-loop continue` 호출 시 `state.json.status == "in_progress"`인 가장 최근 run 선택 (또는 `--run <id>`)
- `last_heartbeat`와 현재 시각 비교: < 30초면 "다른 세션이 돌고 있을 수 있음" 경고 후 사용자 확인

**phase별 재개 지점**

| phase (마지막 round) | 재개 행동 |
|---|---|
| `planned` | plan-from-goal·plan-from-review부터 (prompt가 없거나 비어있음) |
| `init` | dispatch부터 (prompt는 이미 있음) |
| `dispatched` | progress.md tail 보고 결정 (아래 참조) |
| `claude_completed` | review부터 |
| `reviewed` | round-memo 작성부터 |
| `memo_written` | 분기 판정부터 (decision 보고 APPROVE/STOP/NEEDS_CHANGES) |

**`dispatched`에서 끊긴 경우 (가장 까다로움)**

progress.md tail 분석:
- `[doing]` 마커가 있고 `[done]` < N개 → Claude가 작업 시작 후 곧 죽음 → 사용자에게 "**재dispatch**(같은 prompt 처음부터) / **abandon-round**(빈 결과로 review로 진행) / **abort-run**" 제시
- `[doing]` 없고 `[done]` 많음 → 거의 끝났을 가능성, `claude-result.md` 존재 확인. 있으면 claude_completed로 phase 갱신하고 review로. 없으면 사용자 확인.
- `claude-result.md` 이미 있음 → 깔끔하게 review로 진행

**자동 결정 vs 사용자 confirm**
- v1은 안전을 위해 dispatched 인터럽트는 **항상 사용자 confirm**
- 자동 재개는 v2 옵션

**복원 시 컨텍스트 적재**
- state.json (전체, ~1KB)
- memo.md (전체, 누적분)
- shared/* 의 모든 파일 (이번엔 delta가 아니라 처음 복원이므로 전체) — 단 크기 제한 (각 < 10KB 권장, 초과 시 압축 안내)
- 현재 라운드 산출물 (있는 것만)

→ 복원 시 컨텍스트는 라운드 진행보다 더 무거움 (한 번뿐이라 OK).

**`resume-run.md` skill**

Codex가 continue 호출 시 이 skill 본문을 따름. 위 phase 머신을 그대로 박아둠 + 사용자 confirm 양식.

## 9. Implementation Approach

구현 단계에서 **`superpowers:subagent-driven-development`** 우선 사용. Plan 단계에서 task를 독립적·병렬 가능하게 분할 — 예시 분할:

- `python/agent_loop/run_state.py` (phase 머신 포함) + 단위 테스트 (독립)
- `python/agent_loop/diff_capture.py` + 단위 테스트 (독립)
- `python/agent_loop/result_parser.py` + 단위 테스트 (독립)
- `python/agent_loop/progress_parser.py` + 단위 테스트 (독립)
- `python/agent_loop/shared_io.py` (knowledge/decisions/open-questions append + delta 추출) + 단위 테스트 (독립)
- `python/agent_loop/scout.py` (file_tree·grep·header 신호 추출) + 단위 테스트 (독립)
- `python/agent_loop/safety.py` + 단위 테스트 (독립)
- `python/agent_loop/prompt_render.py` + 템플릿 (Reading List 섹션 포함, 독립)
- `python/agent_loop/payload.py` (result_parser·diff_capture·shared_io 의존)
- `python/agent_loop/resume.py` (run_state·progress_parser 의존)
- `python/agent_loop/sdk_runner.py` (safety·shared_io 의존, hook 등록)
- `python/agent_loop/cli.py` (전부 의존, 최후 통합)
- 플러그인 `skills/*.md` 본문 작성 — SKILL.md·plan-from-goal·plan-from-review·round-review·round-memo·shared-knowledge·resume-run·safety-rules (각 독립, 병렬 가능)
- `references/*.md` 스키마 본문 (각 독립)
- `config/defaults.toml` 작성 (독립)

Python 작업은 모두 `.venv`에서 (`feedback-python-venv` memory 참고). 테스트는 `.venv/bin/pytest`.

## 10. Out of Scope (v1)

- max_rounds cap (안전선 trip 외엔 무한 가능 — 사용자가 인터럽트)
- 라운드 간 컨텍스트 "잊기" 명시 규율 (자연스러운 패턴으로 충분한지 실측 후 추가)
- 자동 .gitignore 수정
- 자동 commit/push/PR 생성
- GitHub PR review 모드
- Web dashboard
- Multiple reviewer agents
- Worktree isolation per run

## 11. Future Extensions

- `--auto` 외 `--interactive` 모드 (라운드 사이 사용자 승인)
- 라운드 간 컨텍스트 위생 강제 규율
- 진전 휴리스틱 ("같은 finding 2회 → STOP" 자동화)
- 워크트리 기반 격리
- Multi-reviewer (high-risk diff은 추가 Codex 모델로 second opinion)
- GitHub PR mode (target이 PR 브랜치일 때)
- Codex 외 다른 reviewer LLM도 swap 가능하게

## 12. 디퍼런스 (재확인)

OpenCode·Oh My OpenAgent와 의도적으로 다른 지점:

- Claude Code를 worker로 유지 (대체 아님)
- Codex를 external reviewer로 (또 다른 worker 아님)
- Review 산출물이 primary product
- Bounded autonomy + safety trip — 무한 자동화 지향 아님
- v1은 Codex 플러그인 형태로 packaging, 그러나 Python core는 다른 컨트롤러로도 재사용 가능
