---
name: pdf-chunker
description: PDF 파일에서 구조화된 청크 JSON을 직접 생성합니다. 규칙/규정 문서를 검색 가능한 단위로 구조화할 때 사용합니다.
disable-model-invocation: true
---

# PDF to Chunk JSON Converter

PDF 파일에서 구조화된 청크 JSON을 직접 생성합니다.
11페이지 이상의 PDF는 자동으로 10페이지씩 분할합니다.

## 작업 단계

### 0단계: PDF 분할 (11페이지 이상인 경우)

`$ARGUMENTS`가 폴더 경로이면 해당 폴더 내 모든 PDF를, 파일 경로이면 해당 파일을 대상으로 합니다.

각 PDF의 페이지 수를 확인하여 11페이지 이상이면 10페이지씩 분할합니다:

```bash
python3 "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/split_pdf.py" "$ARGUMENTS"
```

분할 결과:
- `원본파일명_0001-0010.pdf`, `원본파일명_0011-0020.pdf`, ...
- 분할된 파일은 원본과 같은 디렉토리에 저장
- 10페이지 이하인 파일은 그대로 유지

### 1단계: PDF 읽기 → 청크 JSON 직접 생성

1. Read 도구로 PDF 파일을 읽습니다 (분할된 경우 각 분할 파일을 순서대로)
2. PDF 내용을 분석하여 [chunk-schema.md](chunk-schema.md) 기반 청크 JSON을 직접 생성합니다:

**텍스트 변환 규칙 (청크 text 필드 내):**
   - 제목 계층은 `section_path`로 구조화
   - 용어 정의는 `**용어**` 형식으로 굵게 표시
   - 목록은 `-` 또는 숫자 목록 사용
   - 표는 마크다운 표 문법 사용
   - 이미지는 `![설명](images/파일명.png)` 형식

**청크 생성 규칙 (chunk-schema.md v0.7):**
   - `###` 최하위 헤딩 단위로 청킹
   - 500토큰 초과 시 `**(1)**`, `(가)` 등 하위 경계에서 분할 → `split` + `logical_range`
   - 50토큰 미만 → `chunk_type: "micro"` (병합하지 않음)
   - 표 → 통째 유지, `chunk_type: "table"`
   - 각 청크에 메타데이터: `section_path`, `context_prefix`, `images[]`, `tables[]`, `references[]`, `keywords`(5개)
   - `text`에는 본문만 (헤더 반복 금지)
   - 섹션 도입부(공통 정의/적용조건)는 `chunk_type: "intro"`로 별도 청크
   - 각 청크에 `section_id` (### 섹션 식별자, 분할 여부 무관)
   - 2000토큰 초과 표는 `table_oversized: true`
   - `locators.spans`에 `pdf_page_start/end` + `doc_page_start/end` 모두 기록
   - `prev_chunk_id` / `next_chunk_id`로 순차 연결
   - 숫자 테이블은 `tables_data`에 구조화 (columns, rows), 없으면 빈 객체 `{}`
   - 수식/기호 정의는 `equations` 배열로 구조화, 없으면 빈 배열 `[]`

3. Write 도구로 `output/`에 저장합니다:
   - `[파일명].chunks.json` — 청크 JSON

### 2단계: 이미지 추출

extract_images.py로 이미지를 추출합니다 (조각 자동 합침, 벡터 포함, 캡션 인식):
```bash
python3 "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/extract_images.py" "<PDF경로>" -o "$MD_DIR/images" -v
```

### 3단계: 검증 — Codex/Gemini MCP (Stage 2)

**서브 에이전트가 Codex/Gemini MCP를 직접 호출**하여 검증합니다.
하나의 MCP 세션에서 PDF→MD 변환 + chunks.json 검증 + ontology 키워드 추출을 모두 처리합니다.

| 검증 항목 | 내용 |
|-----------|------|
| **커버리지** | MD에 있는데 chunks text에 없는 텍스트 → coverage_issues |
| **환각 체크** | chunks text에 있는데 MD에 없는 내용 → hallucination_suspects |
| **ontology 키워드** | 각 청크에서 7가지 entity type 키워드 추출 → ontology_keywords |

검증 모델은 start 시 사용자가 선택: Codex (gpt-5.3-codex) / Gemini (gemini-3-pro-preview) / 끄기

### 4단계: 검증 결과 반영 + 최종 검증 (Stage 3)

동일한 서브 에이전트가 review.json을 읽고 직접 판단합니다:
1. **coverage_issues** → PDF를 다시 읽어 누락 확인 후 text에 추가
2. **hallucination_suspects** → 검토 후 실제 환각이면 삭제
3. **ontology_keywords** → chunks.json 각 청크에 필드 추가
4. `verify_chunks.py` 실행하여 스키마/구조 최종 검증
5. 에러 시 수정 후 재검증, 실패 시 fail 처리

## 출력

작업 완료 후 다음을 보고합니다:
- 분할된 PDF 파일 수 (분할한 경우)
- 생성된 청크 JSON 파일 경로 및 청크 수
- 추출된 이미지 개수 (있는 경우)
- 검증 결과 (텍스트 커버리지 %, 청크 검증 통과 여부, 누락 의심 항목 수)

## 큐 기반 배치 처리 (공유 큐)

여러 Claude Code 인스턴스가 동시에 작업할 수 있는 디렉토리 기반 공유 큐입니다.
동일 PC의 다른 터미널, 또는 클라우드 저장소를 통한 다른 PC에서도 병렬 작업이 가능합니다.

### 멀티 인스턴스 실행 방법

```bash
# 터미널 A (최초): 큐 초기화 + 배치 시작
/pdf-chunker init
/pdf-chunker start

# 터미널 B (추가): 초기화 없이 바로 배치 시작
/pdf-chunker start
```

- **큐 초기화(`init`)는 최초 1회만** 실행합니다. 이후 추가 터미널에서는 생략하고 바로 `start` 실행
- `init`을 다시 실행해도 기존 상태가 유지되고 신규 PDF만 추가 등록됩니다
- 각 인스턴스는 `hostname_pid-$$`로 고유 식별되어 작업 충돌이 발생하지 않습니다

### 큐 구조
```
/home/kimghw/kgc/.queue/
├── pending/       ← 대기 (.task 파일)
├── processing/    ← 작업 중 (mv로 원자적 할당)
├── done/          ← 완료
└── failed/        ← 실패
```

### 큐 관리 스크립트
모든 큐 작업은 `queue_manager.sh`를 통해 수행합니다:
```bash
bash "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/queue_manager.sh" <command>
```

| 명령 | 설명 |
|------|------|
| `init` | 미변환 PDF를 pending/에 등록 |
| `claim N` | N개 작업을 원자적으로 할당 |
| `complete name` | 작업 완료 처리 |
| `fail name msg` | 작업 실패 처리 |
| `release name` | 작업 반환 (pending으로) |
| `recover` | stale 작업 자동 복구 (30분 초과) |
| `status` | 전체 현황 출력 |
| `migrate` | 레거시 pdf-queue.txt 이전 |

### 컨텍스트 관리

**context 사용량이 80%를 넘어가면 즉시 `/compact`를 실행하여 컨텍스트를 압축한다.** 배치 작업은 대량의 PDF를 반복 처리하므로 컨텍스트 소진이 빠르다. 80% 도달 전에 선제적으로 compact하여 세션 중단을 방지한다.

### 배치 실행 (통합 에이전트)
1. AskUserQuestion으로 4가지를 물어본다:
   - **동시 실행할 에이전트 수** (옵션: 10개(권장), 5개, 3개)
   - **이번 세션에서 처리할 총 개수** (옵션: 전체(권장), 50개, 10개)
   - **이미지 분석** (끄기(권장) / 켜기)
   - **검증 모델** (Codex gpt-5.3-codex(권장) / Gemini gemini-3-pro-preview / 끄기)
2. 큐에서 N개 할당: `bash "$QUEUE_SCRIPT" claim N` (N = 동시 에이전트 수)
3. 각 작업을 **서브 에이전트 1개**가 전 과정 처리:
   - **Stage 1**: PDF 읽기 → 청크 JSON 생성 → 이미지 추출
   - **Stage 2**: Codex/Gemini MCP로 MD 변환 + 검증 + ontology 키워드 추출
   - **Stage 3**: 검증 결과 반영 → verify_chunks.py → complete/fail
   - **Stage 4**: 이미지 분석 (선택) → images[].description 채움
4. 에이전트 완료 시 다음 작업 할당. 총 처리 개수에 도달할 때까지 반복

### stale 복구
- `claim` 시 30분 초과 작업을 자동 감지하여 pending으로 반환

## 지원 파일

### 프롬프트 (prompts/)

서브 에이전트가 Read로 읽어 실행하는 Stage별 프롬프트 파일입니다.

- [agent.md](prompts/agent.md): 서브에이전트 메인 프롬프트 (실행 순서, stage 파일 경로, 결과 보고 형식)
- [stage1-structure.md](prompts/stage1-structure.md): Stage 1 — PDF→chunks.json 구조화 규칙
- [stage4-image.md](prompts/stage4-image.md): Stage 4 — 이미지 분석 (선택, Stage 3 이후)
- [stage2-codex.md](prompts/stage2-codex.md): Stage 2 — Codex MCP 검증 (Step 1 MD변환 + Step 2 검증+ontology)
- [stage2-gemini.md](prompts/stage2-gemini.md): Stage 2 — Gemini MCP 검증
- [stage3-review.md](prompts/stage3-review.md): Stage 3 — 검증 결과 반영 + verify + complete/fail

### 스크립트 (scripts/)
- [split_pdf.py](scripts/split_pdf.py): PDF 분할 스크립트 (11페이지 이상 → 10페이지씩)
- [extract_images.py](scripts/extract_images.py): 이미지 추출 스크립트 (조각 합침, 벡터 포함, 캡션 인식)
- [verify_chunks.py](scripts/verify_chunks.py): 청크 JSON 통합 검증 (스키마+구조+커버리지)
- [verify_markdown.py](scripts/verify_markdown.py): PDF-마크다운 텍스트 커버리지 검증 (레거시)
- [queue_manager.sh](scripts/queue_manager.sh): 공유 큐 관리 스크립트
- [setup_mcp.sh](scripts/setup_mcp.sh): MCP 서버 자동 설정 (Codex/Gemini 등록, 로그인, 권한)

### 설정
- [config.sh](config.sh): 경로 설정 (새 프로젝트에서 이 파일만 수정)

### 문서
- [reference.md](reference.md): 시스템 상세 레퍼런스 (디렉토리 구조, 후크, 변환 규칙 등)
- [chunk-schema.md](chunk-schema.md): 청크 스키마 정의 (Documents/Chunks 구조, 분할/병합 규칙, 토큰 기준)
