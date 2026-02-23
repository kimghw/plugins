---
allowed-tools: Bash, Read, Write, Edit, Task, Glob, Grep, WebFetch, WebSearch, mcp__codex-agent__codex, mcp__codex-agent__codex-reply, mcp__gemini__ask-gemini
---

# PDF → 청크 JSON 변환 시스템 (공유 큐)

PDF 파일들을 구조화된 청크 JSON으로 변환하는 통합 커맨드입니다.
디렉토리 기반 공유 큐를 사용하여 여러 Claude Code 인스턴스에서 동시에 작업할 수 있습니다.

## 경로 설정

경로는 `.claude/pdf-queue.env`에 정의되며, `config.sh`가 이를 로드하고 파생 변수를 설정합니다.
```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
echo "PDF: $PDF_DIR"
echo "OUT: $MD_DIR"
echo "큐: $QUEUE_DIR"
echo "로그: $LOG_DIR"
echo "인스턴스: $INSTANCE_ID"
```

> **로그 디렉토리**: `$LOG_DIR` (기본값: `$MD_DIR/.logs/`)에 각 에이전트의 전체 작업 로그가 저장됩니다.
> 로그 파일명 규칙: `[파일명].log`

## 실행 로직 (자동 상태 판단)

`$ARGUMENTS`가 `init`, `start`, `status`, `recover`, `reset`, `migrate` 중 하나이면 해당 명령을 직접 실행한다.

**`$ARGUMENTS`가 비어있거나 위 명령이 아닌 경우**, 아래 자동 판단 로직을 실행한다:

### 0단계: 상태 확인

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
```

다음 3가지 조건을 순서대로 확인한다:

**조건 A: 큐가 초기화되지 않은 경우** (`$QUEUE_DIR/pending` 디렉토리가 없음)
→ `init` 실행 후 `start` 로직으로 진행

**조건 B: 대기 작업이 있고 이 인스턴스의 작업중이 0개인 경우**
→ `start` 로직 실행 (사용자에게 개수/범위 물어봄)

**조건 C: 이 인스턴스에 작업중인 것이 있는 경우**
→ 현재 상태를 보여주고, 추가 작업을 할당할지 물어봄 (next-batch 로직)

**조건 D: 대기 작업이 0개인 경우**
→ "모든 작업이 완료되었습니다" 메시지 출력, status 표시

---

## 명시적 명령어

### init 명령

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
bash "$QUEUE_SCRIPT" init
```

- 큐 디렉토리 생성 (pending/, processing/, done/, failed/)
- 미변환 PDF를 pending/에 .task 파일로 등록
- 이미 변환된 PDF는 done/으로 기록

### start 명령

**1단계: 사용자에게 처리 방식 확인**

먼저 현재 큐 상태를 보여주고, AskUserQuestion으로 다음 세 가지를 **하나의 AskUserQuestion에 4개 질문**으로 물어본다:

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
bash "$QUEUE_SCRIPT" status
```

질문 1 — **동시 실행할 에이전트 수**
- header: "병렬 수"
- options: 10개(권장), 5개, 3개

질문 2 — **이번 세션에서 처리할 총 개수**
- header: "처리 범위"
- options: 전체(대기 중인 모든 PDF)(권장), 50개, 10개
- 사용자가 Other로 특정 범위(예: "0101~0200만") 또는 숫자를 지정할 수 있음

질문 3 — **이미지 분석 (Stage 1.5)**
- header: "이미지 분석"
- options: 끄기(권장), 켜기
- 켜면 `IMAGE_DESCRIPTION=true` 설정 → Stage 1.5 실행

질문 4 — **검증 모델 (Stage 2)**
- header: "검증 모델"
- options: Codex gpt-5.3-codex(권장), Gemini gemini-3-pro-preview, 끄기(Stage 2 스킵)
- 선택값을 `REVIEW_MODEL` 변수로 설정 (codex / gemini / off)

**1.5단계: MCP 사전 체크** (REVIEW_MODEL이 off가 아닐 때)

```bash
bash "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/setup_mcp.sh" --check-only "$REVIEW_MODEL"
```

실패(exit 1) 시 → "MCP 설정이 필요합니다. `/pdf-chunker:setup`을 먼저 실행하세요." 안내 후 중단.

**2단계: 작업 할당**

사용자 응답에 따라:

- 개수 지정 시:
  ```bash
  RESULT=$(bash "$QUEUE_SCRIPT" claim ${동시에이전트수})
  ```

- 범위 지정 시:
  pending/ 목록에서 해당 범위의 파일만 필터링하여 개수를 계산한 뒤 claim한다.
  ```bash
  # pending 목록에서 범위 내 파일 확인
  bash "$QUEUE_SCRIPT" list pending
  # 범위 내 파일 수를 COUNT로 설정 후 claim
  RESULT=$(bash "$QUEUE_SCRIPT" claim ${동시에이전트수})
  ```

RESULT의 첫 줄이 `CLAIMED:N`이면 이후 줄들이 작업 이름입니다.
`NO_TASKS_AVAILABLE`이면 큐가 비었습니다.

**3단계: 에이전트 실행 (총량 제한)**

claim된 작업에 대해 Task 도구로 백그라운드 에이전트를 실행합니다.
동시 병렬은 사용자가 선택한 수, 총 처리량이 `TOTAL_LIMIT`에 도달하면 **더 이상 claim하지 않고 멈춘다.**

### status 명령

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
bash "$QUEUE_SCRIPT" status
```

### recover 명령

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
bash "$QUEUE_SCRIPT" recover
```

### reset 명령

processing에 있는 작업을 조건 판단 없이 pending으로 되돌린다.
기본은 현재 세션의 작업만, `--all`이면 전체.

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
bash "$QUEUE_SCRIPT" reset         # 내 세션 것만
bash "$QUEUE_SCRIPT" reset --all   # 전체 (다른 세션 포함)
```

### migrate 명령

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
bash "$QUEUE_SCRIPT" migrate
```

---

## 에이전트 프롬프트

각 작업은 **서브 에이전트 1개**가 Stage 1→2→3 전 과정을 처리합니다.
프롬프트는 `$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/prompts/` 디렉토리에 분리되어 있습니다.

### Task prompt 템플릿

각 작업에 대해 Task 도구를 호출할 때 아래 내용을 prompt로 전달합니다:

```
PDF 파일 '[파일명].pdf'을 청크 JSON으로 변환하세요.

설정값:
- PLUGIN_DIR: $CLAUDE_PLUGIN_DIR
- PDF_DIR: $PDF_DIR
- MD_DIR: $MD_DIR
- IMG_DIR: $IMG_DIR
- LOG_DIR: $LOG_DIR
- PDF_FILE: [파일명].pdf
- REVIEW_MODEL: $REVIEW_MODEL
- IMAGE_DESCRIPTION: $IMAGE_DESCRIPTION

먼저 에이전트 프롬프트를 Read로 읽으세요:
$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/prompts/agent.md

위 프롬프트의 지시에 따라 각 Stage 프롬프트를 순서대로 Read로 읽고 실행하세요.
프롬프트 내 {{PLUGIN_DIR}}, {{PDF_DIR}}, {{MD_DIR}} 등의 플레이스홀더는 위 설정값으로 대체하세요.
```

### 에이전트 실행 흐름

각 작업에 대해:
1. 로그 디렉토리 확인: `mkdir -p "$LOG_DIR"` (첫 작업 시 1회)
2. 통합 에이전트를 **백그라운드**로 실행 (Stage 1→2→3 전 과정 처리)
3. 에이전트 완료 알림 수신 시:
   - `OK`이면 → 다음 작업 claim + 에이전트 실행
   - `FAIL`이면 → 로그 파일(`$LOG_DIR/[파일명].log`)을 Read로 읽어 에러 원인 확인 → 다음 작업 claim + 에이전트 실행

**중요**: 에이전트가 `complete` 또는 `fail`을 호출해야 작업 상태가 즉시 업데이트됩니다.
로그 파일은 `$LOG_DIR/`에 저장되며, FAIL 시에만 코디네이터가 로그를 확인합니다.

---

## 자동 연속 실행 (총량 제한 적용)

에이전트 완료 알림을 받으면:
1. 지금까지 완료(complete + fail)된 작업 수를 카운트
2. 완료 수 + 현재 processing 수 < `TOTAL_LIMIT`이면:
   - `bash "$QUEUE_SCRIPT" claim 1`로 다음 작업 할당
   - 에이전트 실행
3. `TOTAL_LIMIT`에 도달하면:
   - **더 이상 claim하지 않고 멈춤**
   - "지정한 N개 처리 완료" 메시지 출력
4. 동시 병렬은 사용자가 선택한 수 유지

**완료 알림 응답 규칙**: 에이전트 완료 알림을 받으면 사용자에게 한 줄로만 보고한다. 예: `0881-0890 OK 16chunks 3img (3/10)`. FAIL인 경우 로그 파일에서 읽은 에러 원인을 간략히 추가한다. 예: `0881-0890 FAIL (verify: split_total 불일치)`. 전체 배치 완료 시 요약 테이블을 출력하며, FAIL 건이 있으면 로그 경로도 함께 안내한다.

---

## 멀티 인스턴스 동시 사용

여러 터미널에서 동시에 작업할 수 있습니다. 각 인스턴스는 PID 기반 고유 ID로 구분되며, `mv` 명령의 원자성으로 동일 작업이 중복 할당되지 않습니다.

- **큐 초기화**: 한 터미널에서 이미 실행했다면, 다른 터미널에서는 `/pdf-chunker`만 실행 (자동으로 start 진행)
- **세션 종료**: 각 인스턴스의 Stop 후크가 미완료 작업을 pending/으로 자동 반환
- **stale 복구**: `claim` 시 30분 초과 작업을 자동 복구하므로 별도 조치 불필요

---

## 필요 권한

settings.local.json에 다음 권한이 필요합니다 (`/pdf-chunker:setup`으로 자동 설정):

```json
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)",
      "Task(*)",
      "Glob(*)",
      "Grep(*)",
      "mcp__codex-agent__codex",
      "mcp__codex-agent__codex-reply",
      "mcp__gemini__ask-gemini"
    ]
  }
}
```
