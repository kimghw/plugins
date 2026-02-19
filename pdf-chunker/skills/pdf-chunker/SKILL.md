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

**청크 생성 규칙 (chunk-schema.md v0.4):**
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
   - 숫자 테이블은 `tables_data`에 구조화 (columns, rows), 없으면 null
   - 수식/기호 정의는 `equations` 배열로 구조화, 없으면 null

3. Write 도구로 `output/`에 저장합니다:
   - `[파일명].chunks.json` — 청크 JSON

### 2단계: 이미지 추출

extract_images.py로 이미지를 추출합니다 (조각 자동 합침, 벡터 포함, 캡션 인식):
```bash
python3 "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/extract_images.py" "<PDF경로>" -o "$MD_DIR/images" -v
```

### 3단계: 검증 (별도 에이전트)

**컨텍스트 손실 방지를 위해 검증은 별도 에이전트(Stage 2)에서 실행합니다.**

`verify_chunks.py`가 3가지를 한 번에 검증합니다:

```bash
python3 "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/verify_chunks.py" "<PDF경로>" "<JSON경로>" -v
```

| 검증 항목 | 내용 |
|-----------|------|
| **스키마** | 모든 필수 필드 존재 여부, chunk_type 유효성, locators.spans 구조, split/continue 구조, references 구조 |
| **구조** | chunk_seq 유일성/연속성, section_id별 split_total 일관성, split_index 완전성, section_index 일관성 |
| **커버리지** | PDF 원문 텍스트 trigram ↔ chunks.text trigram 매칭 (90%+ 목표) |

스키마만 검증 (PDF 없이):
```bash
python3 "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/verify_chunks.py" --schema-only "<JSON경로>" -v
```

### 4단계: 수정 및 재검증 (필요시)

검증 실패 시 Stage 2 에이전트가 자동으로 수정합니다:
1. **스키마 에러** → 누락 필드 추가, 잘못된 타입 수정
2. **구조 에러** → chunk_seq 재부여, split 정합성 수정
3. **커버리지 누락** → PDF 원문을 다시 읽고 빠진 텍스트를 해당 청크에 추가
4. 수정 후 `verify_chunks.py` 재실행으로 확인
5. 재검증도 실패 시 작업을 fail 처리

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

### 배치 실행 (2단계 에이전트)
1. AskUserQuestion으로 다음 두 가지를 물어본다 (하나의 AskUserQuestion에 2개 질문):
   - **동시 실행할 에이전트 수** (옵션: 10개(권장), 5개, 3개)
   - **이번 세션에서 처리할 총 개수** (옵션: 전체(대기 중인 모든 PDF)(권장), 50개, 10개) — 사용자가 Other로 특정 범위(예: "0101~0200만")를 지정할 수도 있음
2. 큐에서 N개 할당: `bash "$QUEUE_SCRIPT" claim N` (N = 동시 에이전트 수)
3. 각 작업을 **2단계**로 실행:
   - **Stage 1 (생성)**: PDF 읽기 → 청크 JSON 생성 → 저장 → 이미지 추출
   - **Stage 2 (검증)**: verify_chunks.py 실행 → 에러 시 수정 → 재검증 → complete/fail
4. Stage 2 완료 시 다음 작업 할당. 총 처리 개수에 도달할 때까지 반복

### stale 복구
- `claim` 시 30분 초과 작업을 자동 감지하여 pending으로 반환

## 지원 파일

### 스크립트 (scripts/)
- [split_pdf.py](scripts/split_pdf.py): PDF 분할 스크립트 (11페이지 이상 → 10페이지씩)
- [extract_images.py](scripts/extract_images.py): 이미지 추출 스크립트 (조각 합침, 벡터 포함, 캡션 인식)
- [verify_chunks.py](scripts/verify_chunks.py): 청크 JSON 통합 검증 (스키마+구조+커버리지)
- [verify_markdown.py](scripts/verify_markdown.py): PDF-마크다운 텍스트 커버리지 검증 (레거시)
- [queue_manager.sh](scripts/queue_manager.sh): 공유 큐 관리 스크립트

### 설정
- [config.sh](config.sh): 경로 설정 (새 프로젝트에서 이 파일만 수정)

### 문서
- [reference.md](reference.md): 시스템 상세 레퍼런스 (디렉토리 구조, 후크, 변환 규칙 등)
- [chunk-schema.md](chunk-schema.md): 청크 스키마 정의 (Documents/Chunks 구조, 분할/병합 규칙, 토큰 기준)
