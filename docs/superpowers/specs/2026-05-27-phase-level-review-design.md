# Phase-Level Review & Commit 설계

## 배경 및 문제

현재 agent-loop는 **라운드마다 Codex 리뷰**를 실행한다. 이 구조에서 세 가지 문제가 발생한다.

1. **Codex가 diff를 제대로 추적 못 함** — 신규 파일은 untracked 상태라 `git diff HEAD`에 나타나지 않음. `.agent-loop/` 아티팩트 파일들이 `git status` 노이즈를 만들어 Codex가 실제 변경사항을 식별하기 어려움.

2. **커밋 단위가 너무 작음** — 라운드마다 커밋 또는 스테이징을 하면 단편적인 작업 단위가 되어 의미 없는 커밋 히스토리가 생성됨.

3. **Codex 리뷰 누적 비효율** — 라운드마다 Codex를 호출하면 비용/지연이 누적되고, 라운드별 리뷰는 맥락이 부족해 전체 품질을 평가하기 어려움.

## 목표

- Codex 리뷰를 **페이즈 단위**로만 수행
- git commit을 **페이즈 완료 시점**에만 찍어 의미 있는 커밋 단위 확보
- Codex가 페이즈 전체 diff를 한 번에 보고 품질 판단
- 라운드는 순수 구현 + 검증 사이클로만 동작

---

## 새 아키텍처

### 페이즈 내 흐름

```
Phase N 시작
  │
  ├─ Round 1
  │    ├─ plan-round (Codex: 다음 할 일 + 모델 선정)
  │    ├─ capture-baseline
  │    ├─ 구현 subtask 실행
  │    ├─ verification subtask 실행
  │    ├─ record-diff + mark-worker-done
  │    └─ supervisor 판단: 페이즈 완료? → NO → Round 2
  │
  ├─ Round 2 ... Round K (동일 구조 반복)
  │
  └─ supervisor 판단: 페이즈 완료 → YES
       ├─ git add -- . :(exclude).agent-loop
       ├─ git commit -m "phase N: <phase title>"
       ├─ phase-review (Codex: 페이즈 전체 diff 검토)
       │    ├─ APPROVE → advance-phase (또는 finalize)
       │    └─ NEEDS_CHANGES → fix round(s) → 재커밋 → 재검토
       └─ (반복)
```

### 현재 vs 변경 후

| 항목 | 현재 | 변경 후 |
|------|------|---------|
| Codex 리뷰 빈도 | 매 라운드 | 페이즈 완료 시만 |
| git commit 시점 | APPROVE 라운드 | 페이즈 완료 시 |
| diff 추적 방식 | untracked 합성 패치 | git add 후 `git diff HEAD~1` |
| 라운드 루프 결정자 | Codex (APPROVE/NEEDS_CHANGES/PHASE_COMPLETE) | Supervisor (verification 결과 기반) |
| 재작업 단위 | 라운드 | 페이즈 내 추가 라운드 |

---

## 상세 설계

### 1. `plan-round` 출력 스키마 변경

`phase_complete_signal` 필드 추가. Codex가 "이 라운드 완료 후 페이즈 목표 달성 가능성 높음"을 supervisor에게 신호.

```json
{
  "round_plan": {
    "round": 3,
    "worker_model": "sonnet",
    "worker_model_reason": "...",
    "reasoning_effort": "medium",
    "phase_complete_signal": true,
    "subtasks": [...]
  },
  ...
}
```

- `phase_complete_signal: true` → Codex 판단상 이 라운드가 끝나면 페이즈 목표 달성
- `phase_complete_signal: false` → 더 작업 필요
- 기존 `commit_message` 필드: 스키마에서 제거됨 (커밋은 페이즈 단위로 supervisor가 직접 실행)

### 2. 라운드 루프에서 `review-round` 제거

기존 SKILL.md round loop:
```
verification PASS → review-round(Codex) → APPROVE/NEEDS_CHANGES/PHASE_COMPLETE
```

새 round loop:
```
verification PASS → supervisor 페이즈 완료 판단 → 완료 아님: 다음 라운드
                                                → 완료: phase-commit + phase-review
```

### 3. Supervisor 페이즈 완료 판단 기준

Supervisor(Claude)가 다음 **두 조건을 모두** 충족하면 페이즈 완료 선언:

1. **verification PASS** — 현재 라운드의 모든 verification subtask가 pass
2. **acceptance_criteria 충족** — plan-round가 내린 acceptance_criteria 항목이 test 결과 또는 grep 명령으로 확인됨

`phase_complete_signal: true`는 판단 보조 신호 (필수 조건 아님). 두 주요 조건을 충족하면 signal 없이도 페이즈 완료 선언 가능.

연속으로 `NEEDS_CHANGES`가 3회 이상이면 user에게 에스컬레이션 (기존 논리 유지).

### 4. 새 subcommand: `phase-review`

**호출 시점**: 페이즈 커밋 직후

**입력**:
- `--run <run_id>`
- `--phase <phase_n>`

**동작**:
1. `git diff HEAD~1` 로 페이즈 전체 diff 수집 (커밋 단위이므로 깔끔)
2. 페이즈 목표 문서(`phases/phase-NN.md`) 로드
3. `shared/test-results.md`, `shared/decisions.md`, `shared/knowledge.md` 로드
4. Codex 호출 — 페이즈 전체 diff + 페이즈 목표 기준으로 품질 검토
5. 결정: `APPROVE | NEEDS_CHANGES`
6. `state.json`에 phase review 결과 기록
7. 메모 추가

**Codex에게 전달하는 리뷰 프롬프트 구조**:
```
# Phase Review — Phase N

## Phase Objective
<phases/phase-NN.md 내용>

## Phase Diff (git diff HEAD~1)
<diff 내용 — 페이즈 커밋 전체>

## Test Results
<shared/test-results.md>

## Shared Context
<decisions.md, knowledge.md>

## Decision Rules
- APPROVE: 페이즈 목표 완전 달성, 테스트 통과, 심각한 이슈 없음
- NEEDS_CHANGES: 목표 미달성 또는 high-severity 이슈 존재
```

**출력 JSON**:
```json
{
  "decision": "APPROVE | NEEDS_CHANGES",
  "phase": 1,
  "review_path": ".agent-loop/runs/<id>/phases/phase-01-review.md",
  "severity_counts": {"high": 0, "med": 1, "low": 2},
  "carry_forward": ["..."],
  "memo_appended": true
}
```

### 5. APPROVE 흐름 변경

기존 APPROVE (라운드 단위):
```bash
git add -A && git commit -m "<commit_message>"
finalize
```

새 APPROVE (phase-review 후):
```
phase-review → APPROVE
→ advance-phase (또는 finalize if last phase)
```

마지막 페이즈 APPROVE → `finalize` (커밋은 이미 페이즈 커밋으로 완료됨)

### 6. NEEDS_CHANGES 흐름 (phase-review 후)

```
phase-review → NEEDS_CHANGES
→ Supervisor: carry_forward 내용으로 fix round 계획
→ fix round 실행 (구현 + verification)
→ git add + git commit --amend OR 새 커밋
  (amend vs 새 커밋: severity high가 있으면 새 커밋, minor면 amend 허용)
→ phase-review 재실행
→ 3회 연속 NEEDS_CHANGES → user 에스컬레이션
```

### 7. `record-diff` 변경 (선택적)

현재 untracked 파일 합성 패치 방식은 유지. 페이즈 커밋 후에는 `git diff HEAD~1`이 권위 있는 소스가 되므로 `diff.patch`는 보조 아티팩트로 격하.

---

## 파일/모듈 변경 목록

| 파일 | 변경 내용 |
|------|----------|
| `python/agent_loop/cli.py` | `phase-review` subcommand 추가; `_parse_round_plan`에서 `phase_complete_signal` 파싱 추가; `commit_message` 제거 |
| `python/agent_loop/run_state.py` | phase review 결과 저장 필드 추가 (`phase_review_decision`, `phase_commit_sha`) |
| `python/agent_loop/cli.py` — `plan-round` prompt | `phase_complete_signal` 필드 요청, `commit_message` 제거 |
| `skills/agent-loop/SKILL.md` | 라운드 루프 재작성: review-round 제거, supervisor 판단 로직, phase-review 호출 추가 |
| `config/defaults.toml` | phase-review 관련 설정 항목 추가 (필요 시) |

---

## 마이그레이션 고려사항

- 기존 진행 중인 run이 있다면 `continue` 시 review-round 기반 흐름으로 처리 (resume.py에서 구버전 state 감지)
- `review-round` subcommand는 내부 유지 (phase-review가 내부적으로 재사용)
- 테스트: `test_review_round_*` → `test_phase_review_*` 업데이트 필요

---

## 성공 기준

1. 라운드 루프가 Codex 리뷰 없이 verification pass/fail로만 흐름 결정
2. 페이즈 완료 시 `git diff HEAD~1`이 깔끔한 페이즈 단위 diff 제공
3. `phase-review` 호출 시 Codex가 전체 페이즈 맥락 기반으로 APPROVE/NEEDS_CHANGES 결정
4. APPROVE 후 git log가 페이즈 단위 커밋 히스토리 보여줌
5. 기존 run continue 호환성 유지
