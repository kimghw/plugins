---
allowed-tools: Bash, Read, Write, Edit, Task, Glob, Grep, WebFetch, WebSearch
---

# PDF → 청크 JSON 변환 시스템 (공유 큐)

PDF 파일들을 구조화된 청크 JSON으로 변환하는 통합 커맨드입니다.
디렉토리 기반 공유 큐를 사용하여 여러 Claude Code 인스턴스에서 동시에 작업할 수 있습니다.

## 경로 설정

모든 경로는 `$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh`에서 관리합니다.
```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
echo "PDF: $PDF_DIR"
echo "OUT: $MD_DIR"
echo "큐: $QUEUE_DIR"
echo "인스턴스: $INSTANCE_ID"
```

## 실행 로직 (자동 상태 판단)

`$ARGUMENTS`가 `init`, `start`, `status`, `recover`, `migrate` 중 하나이면 해당 명령을 직접 실행한다.

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

먼저 현재 큐 상태를 보여주고, AskUserQuestion으로 다음 세 가지를 **하나의 AskUserQuestion에 3개 질문**으로 물어본다:

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

### migrate 명령

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
bash "$QUEUE_SCRIPT" migrate
```

---

## 에이전트 프롬프트 템플릿

각 작업은 **2단계 에이전트**로 실행합니다. 컨텍스트 손실을 방지하기 위해 생성과 검증을 분리합니다.

### Stage 1: 생성 에이전트

```
PDF 파일에서 구조화된 청크 JSON을 직접 생성하세요.

PDF: $PDF_DIR/[파일명].pdf
청크 JSON 저장: $MD_DIR/[파일명].chunks.json
청크 스키마: $CLAUDE_PLUGIN_DIR/skills/pdf-chunker/chunk-schema.md

작업:
1. Read로 PDF 읽기
2. 청크 스키마(chunk-schema.md)를 Read로 읽기
3. 청크 JSON 직접 생성 (chunk-schema.md v0.7):
   - ### 최하위 헤딩 단위로 청킹, 각 청크에 section_id 부여
   - 섹션 도입부(공통 정의/적용조건)는 chunk_type: "intro"로 분리
   - 500토큰 초과 시 **(1)**/(가) 경계에서 분할, split.group_id 부여 ({section_id}|{parent_label})
   - 50토큰 미만은 chunk_type: "micro", 표는 통째 chunk_type: "table"
   - 2000토큰 초과 표는 table_oversized: true
   - 각 청크에: section_id, section_path, context_prefix, images[], tables[], references[], keywords(5개)
   - images[].description: 빈 문자열 ""로 설정 (Stage 1.5에서 채움)
   - references에 target_norm (정규화 구조) 포함. null 키 금지 — 해당 키만 포함. external이면 빈 객체 {}
   - references에 relation 필드 추가: 초기값 null (후처리에서 채움)
   - text에는 본문만 (헤더 반복 금지), 원문 그대로 — 요약/생략 금지
   - text 내 표는 마크다운 표 문법, 용어는 **볼드** 유지
   - section_index(섹션 등장 순번) + chunk_seq(문서 전체 유일 순번) 모두 기입
   - page_start/end는 locators.spans에서 파생: page_start=min(doc_page_start), page_end=max(doc_page_end)
   - locators.spans에 pdf_page_start/end(분할 PDF 내) + doc_page_start/end(전체 문서 절대 페이지) 기록
   - prev_chunk_id / next_chunk_id로 순차 연결 (첫 청크 prev=null, 마지막 next=null)
   - 숫자 테이블(계산표/허용값표)은 tables_data에 구조화 (columns, rows). 없으면 빈 객체 {}
   - 수식/기호 정의는 equations 배열에 적극 구조화 (name, symbol, expression, variables). 없으면 빈 배열 []
   - embedding 필드 없음 (별도 컬렉션으로 분리)
   - KG 확장 필드(domain_entities, applicability, normative_values)는 청킹 시 생성하지 않음 (후처리에서 채움)
   - null 사용 금지: tables_data는 {}, equations는 [], images/tables/references는 [] 사용
4. Write로 저장: [파일명].chunks.json
5. 이미지 추출:
   Bash: python3 "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/extract_images.py" "$PDF_DIR/[파일명].pdf" -o "$IMG_DIR" -v

결과 보고는 반드시 아래 한 줄 형식으로만 반환하세요:
GENERATED [파일명] 이미지N개 청크N개
또는
FAIL [파일명] 에러사유
```

### Stage 1.5: 이미지 분석 에이전트 (옵션)

Stage 1 완료 후, 이미지가 있는 경우에만 실행합니다. `IMAGE_DESCRIPTION` 옵션이 켜져 있을 때만 실행됩니다.

```
추출된 이미지의 내용을 분석하여 chunks.json의 images[].description을 채우세요.

청크 JSON: $MD_DIR/[파일명].chunks.json
이미지 디렉토리: $IMG_DIR/[파일명]/

작업:
1. chunks.json을 Read로 전체 읽기
2. images[]가 비어있지 않은 청크를 찾기
3. 각 이미지에 대해 **문맥 수집 후 분석**:
   a. 해당 청크의 text를 읽기 (이미지가 어떤 맥락에서 참조되는지 확인)
   b. prev_chunk_id / next_chunk_id로 인접 청크의 text도 읽기 (수치, 용어, 조건 등 보충 정보)
   c. 이미지 파일을 Read로 읽기
   d. 이미지 내용 + 청크 문맥을 종합하여 description 작성 (1~3문장)
4. description 작성 기준:
   - 플로우차트: 흐름, 판단 조건, 분기 결과 요약
   - 도해/다이어그램: 구조, 부호 규약, 방향 설명
   - 그래프: 축 의미, 곡선 종류, 허용값/경계값 수치 포함
   - 배치도: 구획/탱크 명칭, Frame 범위, 용도 구분
   - 구조도/단면도: 부재 명칭과 배치 설명
   - 데이터 테이블 이미지: 포함된 데이터 종류, 주요 수치 설명
5. 각 청크의 images[].description에 설명을 채워 Write로 저장

결과 보고는 반드시 아래 한 줄 형식으로만 반환하세요:
DESCRIBED [파일명] 이미지N개
또는
SKIP [파일명] 이미지없음
```

### Stage 2: 검증 에이전트

Stage 1 (또는 Stage 1.5) 완료 후 별도 에이전트로 실행합니다:

```
생성된 chunks.json을 검증하고, 문제가 있으면 수정하세요.

PDF: $PDF_DIR/[파일명].pdf
청크 JSON: $MD_DIR/[파일명].chunks.json
청크 스키마: $CLAUDE_PLUGIN_DIR/skills/pdf-chunker/chunk-schema.md

작업:
1. 스키마/구조 자동 검증:
   Bash: python3 "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/verify_chunks.py" "$MD_DIR/[파일명].chunks.json" -v
2. 스키마/구조 에러가 있으면:
   a. chunks.json을 Read로 읽고, 누락 필드 추가/수정 후 Write로 저장
   b. chunk_seq/split 정합성 수정
   c. 수정 후 다시 verify_chunks.py 실행하여 재검증
3. 커버리지 확인 (에이전트 직접 수행):
   a. PDF를 Read로 읽기
   b. chunks.json의 text들과 대조하여, PDF 원문에 있는데 chunks에 누락된 텍스트가 없는지 확인
   c. 누락이 있으면 해당 청크의 text에 추가하고 Write로 저장
4. 모든 검증 통과 시:
   Bash: bash "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/queue_manager.sh" complete "[파일명]"
   → OK 반환
5. 수정 불가능한 에러 시:
   Bash: bash "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/queue_manager.sh" fail "[파일명]" "에러 설명"
   → FAIL 반환

결과 보고는 반드시 아래 한 줄 형식으로만 반환하세요:
OK [파일명] 청크N개
또는
FAIL [파일명] 에러사유
```

### 에이전트 실행 흐름

각 작업에 대해:
1. Stage 1 에이전트를 **백그라운드**로 실행
2. Stage 1 완료 알림 수신 시:
   - `FAIL`이면 → 해당 작업을 fail 처리하고, 다음 작업 claim
   - `GENERATED`이면:
     - `IMAGE_DESCRIPTION=true`이고 이미지가 있으면 → Stage 1.5 실행
     - 그 외 → Stage 2 실행
3. Stage 1.5 완료 알림 수신 시:
   - → Stage 2 에이전트를 **백그라운드**로 실행
4. Stage 2 완료 알림 수신 시:
   - `OK`이면 → 다음 작업 claim + Stage 1 실행
   - `FAIL`이면 → 다음 작업 claim + Stage 1 실행

**중요**: Stage 2 에이전트가 `complete` 또는 `fail`을 호출해야 작업 상태가 즉시 업데이트됩니다.
Stage 1이 실패하면 코디네이터가 직접 `fail`을 호출합니다.

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

**완료 알림 응답 규칙**: 에이전트 완료 알림을 받으면 사용자에게 한 줄로만 보고한다. 예: `0881-0890 OK 16chunks 3img (3/10)`. 전체 배치 완료 시에만 요약 테이블을 출력한다.

---

## 멀티 인스턴스 동시 사용

여러 터미널에서 동시에 작업할 수 있습니다. 각 인스턴스는 PID 기반 고유 ID로 구분되며, `mv` 명령의 원자성으로 동일 작업이 중복 할당되지 않습니다.

- **큐 초기화**: 한 터미널에서 이미 실행했다면, 다른 터미널에서는 `/pdf-chunker`만 실행 (자동으로 start 진행)
- **세션 종료**: 각 인스턴스의 Stop 후크가 미완료 작업을 pending/으로 자동 반환
- **stale 복구**: `claim` 시 30분 초과 작업을 자동 복구하므로 별도 조치 불필요

---

## 필요 권한

settings.local.json에 다음 권한이 필요합니다:

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
      "Grep(*)"
    ]
  }
}
```
