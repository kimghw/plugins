# Chunk Schema v0.7

PDF를 검색 가능한 청크 단위로 직접 구조화하기 위한 스키마 정의.
지식 그래프(KG) 구축을 위한 확장 필드와 별도 컬렉션 스펙을 포함.

## 파이프라인

```
PDF → 10p 분할 → 청크 JSON 직접 생성 → (계속) 병합 → 메타데이터 보강
                (Claude Read)         (후처리)      (키워드·참조 등)
```

---

## 1. Documents

문서 단위. 병합 완료된 논리적 문서 1개 = 1 레코드.

```jsonc
{
  "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "doc_id": "kr_rules_2025_v1",
  "title": "2025 선급 및 강선규칙",
  "source_pdf": "강선규칙.pdf",
  "json_dir": "pdf-source/output/",
  "page_total": 1070,
  "created_at": "2026-02-19T00:00:00Z",
  "source_pdf_sha256": "a1b2c3...",
  "pipeline_version": "chunk_v0.7",
  "chunking_config": {
    "target_tokens": 500,
    "hard_max_tokens": 900,
    "min_tokens": 50,
    "table_oversized_threshold": 2000
  },
  "effective_version": {
    "rule_edition": "2025",
    "effective_date": "2025-07-01",
    "amendment_no": null,
    "supersedes_doc_id": null
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | UUID v4 | PK. DB/API 참조용 |
| `doc_id` | string | 사람이 읽을 수 있는 고유 식별자 |
| `title` | string | 문서 제목 |
| `source_pdf` | string | 원본 PDF 경로 |
| `json_dir` | string | 청크 JSON 파일 저장 디렉토리 |
| `page_total` | int | 원본 총 페이지 수 |
| `created_at` | string | 생성 시각 (ISO 8601) |
| `source_pdf_sha256` | string | 원본 PDF SHA-256 해시. 변경 감지용 |
| `pipeline_version` | string | 변환 파이프라인 버전 (예: "chunk_v0.7") |
| `chunking_config` | object | 청킹 설정값 스냅샷 |
| `effective_version` | object \| null | 규정 시간축 정보. 아래 참조 |

**effective_version 상세:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `rule_edition` | string | 규칙 판(예: "2025") |
| `effective_date` | string \| null | 시행일 (ISO 8601 date). 미확인이면 null |
| `amendment_no` | string \| null | 개정 번호. 초판이면 null |
| `supersedes_doc_id` | string \| null | 이전 판의 doc_id. 초판이면 null |

---

## 2. TOC (목차)

문서의 전체 섹션 구조를 나타내는 목차. Documents 1개에 대해 TOC 항목 N개.

```jsonc
{
  "doc_id": "kr_rules_2025_v1",
  "toc": [
    {
      "level": 1,
      "path": ["1편 선급등록 및 검사"],
      "title": "1편 선급등록 및 검사",
      "page": 1,
      "chunk_ids": []
    },
    {
      "level": 2,
      "path": ["1편 선급등록 및 검사", "2장 선급검사"],
      "title": "2장 선급검사",
      "page": 30,
      "chunk_ids": []
    },
    {
      "level": 3,
      "path": ["1편 선급등록 및 검사", "2장 선급검사", "204."],
      "title": "선종별 추가요건",
      "page": 46,
      "chunk_ids": ["kr_2025_c0142_0", "kr_2025_c0142_1", "kr_2025_c0142_2"]
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `doc_id` | string | Documents FK |
| `toc[]` | array | 목차 항목 배열 |

**TOC 항목:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `level` | int | 헤딩 레벨. `#`=1, `##`=2, `###`=3 |
| `path` | string[] | 헤딩 계층 경로 (Chunks의 `section_path`와 동일 형식) |
| `title` | string | 헤딩 제목 텍스트 |
| `page` | int | 원본 PDF 절대 페이지 (1-based) |
| `chunk_ids` | string[] | 이 섹션에 해당하는 chunk_id 목록. 레벨 1~2는 직접 청크가 없으므로 빈 배열 |

- PDF의 헤딩 구조에서 자동 추출
- 레벨 1~2 항목은 청크를 직접 갖지 않지만 문서 구조 탐색에 사용
- 레벨 3 항목은 해당 `###` 아래의 모든 청크(분할 포함)를 `chunk_ids`로 연결

---

## 3. Chunks

검색 단위. 최하위 헤딩(`###`) 기준 분리, target_tokens 초과 시 분할.

```jsonc
{
  // --- 식별 ---
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "chunk_id": "kr_2025_c0142_1",
  "doc_id": "kr_rules_2025_v1",
  "section_index": 142,
  "chunk_seq": 0,
  "section_id": "kr_2025_sec_3편_부록3-1_5.1",
  "chunk_type": "section",

  // --- 위치 ---
  "section_path": ["1편 선급등록 및 검사", "2장 선급검사", "204."],
  "section_title": "선종별 추가요건",
  "page_start": 46,       // 파생: min(spans[].doc_page_start)
  "page_end": 55,         // 파생: max(spans[].doc_page_end)
  "locators": {           // 정본 (single source of truth)
    "spans": [
      {"source_pdf": "강선규칙_0041-0050.pdf", "pdf_page_start": 6, "pdf_page_end": 10, "doc_page_start": 46, "doc_page_end": 50},
      {"source_pdf": "강선규칙_0051-0060.pdf", "pdf_page_start": 1, "pdf_page_end": 5, "doc_page_start": 51, "doc_page_end": 55}
    ]
  },

  // --- 본문 ---
  "context_prefix": "1편 선급등록 및 검사 > 2장 선급검사 > 204. 선종별 추가요건",
  "text": "추가로 다음과 같이 가능한 범위에서 ...",

  // --- 분할 (target_tokens 초과 시) ---
  "split": {
    "group_id": "kr_2025_sec_1편_2장_204|3. 액화가스 산적운반선",
    "split_index": 1,
    "split_total": 7,
    "logical_range": {
      "parent_label": "3. 액화가스 산적운반선",
      "item_start": "(1)",
      "item_end": "(20)"
    }
  },

  // --- 순차 연결 ---
  "prev_chunk_id": null,
  "next_chunk_id": "kr_2025_c0142_2",

  // --- 참조 ---
  "images": [
    { "ref": "그림 3", "file": "images/강선규칙_1051-1060_p05_01.png", "description": "적하결정 플로우차트. (1) 각 체크포인트에 대한 M_S, F_S 계산 → 허용값 비교 → 적하변경 또는 격창적하 판단 → (2) F_C 계산 → 허용값 비교 → 적하결정" }
  ],
  "tables": [
    { "ref": "표 3", "summary": "정수중 종굽힘 모멘트 및 전단력 계산표" }
  ],
  "tables_data": {},
  "references": [
    { "target": "5.5", "type": "internal", "relation": "requires", "target_norm": {"article": "5.5"} },
    { "target": "규칙 7편 4장 1003.", "type": "cross_part", "relation": "requires", "target_norm": {"part": "7편", "chapter": "4장", "article": "1003."} }
  ],

  // --- 수식/기호 ---
  "equations": [
    {
      "name": "shearing_force",
      "symbol": "F_S",
      "expression": "(SS - ΣW) × 9800",
      "variables": {"SS": "BUOYANCY & LW 합계", "ΣW": "DEADWEIGHT 합계"}
    }
  ],

  // --- 키워드 ---
  "keywords": ["종굽힘모멘트", "전단력", "적하조정", "허용값", "격창전단력"],

  // --- KG 확장 (후처리 파이프라인에서 생성) ---
  "domain_entities": [
    { "mention": "액화가스 산적운반선", "canonical": "LNG_bulk_carrier", "type": "ship_type" },
    { "mention": "전단력", "canonical": "shearing_force", "type": "parameter" }
  ],
  "applicability": {
    "ship_types": ["LNG_bulk_carrier"],
    "size_conditions": [],
    "date_conditions": []
  },
  "normative_values": [
    { "parameter": "shearing_force", "symbol": "F_S", "value": null, "unit": "kN", "condition": "정수중" }
  ]
}
```

---

## 4. 필드 상세

### 식별

| 필드 | 역할 | 타입 | 설명 |
|------|------|------|------|
| `id` | **내부 PK** | UUID v4 | DB/API 기본키. 외부 노출용 |
| `chunk_id` | **안정 키** | string | `{doc_id}_c{section_index}_{split_index}`. 로그/디버깅/참조용. 재추출해도 동일 |
| `doc_id` | **FK** | string | Documents 외래키. 문서 소속 |
| `section_index` | **그룹 키** | int | `###` 섹션 순번 (0-based). 같은 섹션의 분할 조각들이 공유. 섹션 그룹핑에 사용 |
| `chunk_seq` | **정렬 키** | int | 문서 전체 청크 순번 (0-based, 유일, 연속). 인접 확장/정렬에 사용 |
| `section_id` | **섹션 식별** | string | `###` 섹션 식별자. 분할 여부와 무관하게 항상 존재. split.group_id의 접두사 |
| `chunk_type` | **분류** | enum | 청크 유형. 아래 참조 |

> **정렬**: `chunk_seq` 사용. **섹션 내 조회**: `section_id`로 필터. **조인**: `id` (UUID) 사용.

**chunk_type 값:**

| 값 | 설명 |
|----|------|
| `section` | 일반 텍스트 섹션 (기본값) |
| `table` | 표 전체를 포함하는 청크. 표가 hard_max_tokens를 초과해도 분할하지 않음 |
| `image_caption` | 이미지 + 캡션 중심 청크 |
| `micro` | min_tokens 미만의 짧은 청크. 물리 병합하지 않음, retrieval-time 인접 확장으로 처리 |
| `intro` | 섹션 도입부 (공통 정의/적용조건). section_id로 해당 섹션의 다른 조각과 연결 |

### 위치

| 필드 | 타입 | 설명 |
|------|------|------|
| `section_path` | string[] | 헤딩 계층. `#` → `##` → `###` 순서 |
| `section_title` | string | 최하위 헤딩의 제목 텍스트 |
| `page_start` | int | **파생**. `min(spans[].doc_page_start)`. 페이지 필터링 편의용 |
| `page_end` | int | **파생**. `max(spans[].doc_page_end)`. 페이지 필터링 편의용 |
| `locators` | object | **정본 (single source of truth)**. 원본 분할 PDF 내 위치. spans 배열로 다중 파일 지원 |

> `page_start/end`는 `locators.spans`에서 자동 도출. 두 값이 충돌하면 `locators`가 정답.

**locators 상세:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `spans` | array | 원본 PDF 위치 목록. 병합된 청크는 2개 이상의 span을 가짐 |

**span 항목:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `source_pdf` | string | 원본(분할된) PDF 파일명 |
| `pdf_page_start` | int | 해당 분할 PDF 내 시작 페이지 (1-based) |
| `pdf_page_end` | int | 해당 분할 PDF 내 끝 페이지 |
| `doc_page_start` | int | 원본 전체 문서 기준 절대 시작 페이지 (1-based) |
| `doc_page_end` | int | 원본 전체 문서 기준 절대 끝 페이지 |

### 본문

| 필드 | 타입 | 설명 |
|------|------|------|
| `context_prefix` | string | 섹션 경로 문자열. 임베딩 대상 아님. LLM 프롬프트 조립 시 text 앞에 붙임 |
| `text` | string | 본문 전용. 임베딩 대상. 헤더 반복 없음 |

**사용 방식:**
- 임베딩 생성: `text`만 대상
- LLM 프롬프트: `context_prefix + "\n" + text` 조립
- 검색 결과 표시: `context_prefix`를 breadcrumb으로 표시

### split (토큰 초과 분할)

하나의 `###` 섹션이 target_tokens를 초과할 때 분할. 초과하지 않으면 `null`.
split 객체 존재 여부로 분할 판단. null이면 미분할. section_id가 같은 조각들이 동일 섹션. group_id로 묶음 식별.

| 필드 | 타입 | 설명 |
|------|------|------|
| `group_id` | string | 분할 묶음 식별자. `{section_id}\|{parent_label}` 형식. 같은 분할 그룹의 모든 조각이 동일 값 |
| `split_index` | int | 이 조각의 순번 (0-based) |
| `split_total` | int | 원본 섹션의 총 조각 수 |
| `logical_range` | object \| null | 이 조각이 커버하는 항목 범위. 결정론적 자동 생성 |

**logical_range 상세:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `parent_label` | string \| null | 분할 내 상위 라벨 (예: "3. 액화가스 산적운반선"). 없으면 null |
| `item_start` | string | 이 조각의 첫 항목 라벨 (예: "(1)") |
| `item_end` | string | 이 조각의 마지막 항목 라벨 (예: "(20)") |

- 분할 알고리즘이 첫/마지막 항목 라벨을 파싱하여 자동 생성 (LLM 불필요)
- 항목 번호가 없는 문단 분할의 경우: `item_start`/`item_end`에 첫/마지막 문장의 앞 20자를 넣음

**분할 경계 우선순위:**

1. 볼드 넘버링 `**(1)**`, `**(2)**` ...
2. 하위 넘버링 `(가)`, `(나)` ...
3. 위 경계 없으면 target_tokens 근처 빈 줄(문단 끝)에서 자름

**분할 경계 탐지 규칙:**

라인 시작 앵커 필수. 본문 중간에 나오는 번호는 경계로 인정하지 않음.

```
허용 패턴 (라인 시작):
  ^\s*\*\*\(\d+\)\*\*     →  **(1)**
  ^\s*\(\d+\)              →  (1)
  ^\s*\d+\)                →  1)
  ^\s*[①②③④⑤⑥⑦⑧⑨⑩]    →  ①
  ^\s*\*\*\([가-힣]\)\*\*  →  **(가)**
  ^\s*\([가-힣]\)          →  (가)
  ^\s*[가-힣]\.            →  가.
  ^\s*\-\s+\([가-힣]\)     →  - (가)
```

**분할 제약:**

- 표(`|...|`)는 중간에서 자르지 않음
- 표가 hard_max_tokens를 초과하더라도 분할하지 않음 (chunk_type: "table"로 태그)
- 이미지 참조(`![...]()`)는 참조하는 텍스트와 같은 청크에 유지

### 순차 연결

| 필드 | 타입 | 설명 |
|------|------|------|
| `prev_chunk_id` | string \| null | 직전 청크의 chunk_id. 첫 청크이면 null |
| `next_chunk_id` | string \| null | 직후 청크의 chunk_id. 마지막 청크이면 null |

- chunk_seq 순서 기준으로 자동 설정
- 분할된 표의 조각들을 연결하거나, 인접 확장에 사용
- 동일 section_id 내에서만 연결하는 것이 아니라, 전체 문서 내 순서 기준

### 참조 메타데이터

| 필드 | 타입 | 추출 방법 |
|------|------|----------|
| `images[]` | `{ref, file, description}` | 정규식: `!\[(.+?)\]\((.+?)\)` + LLM이 이미지 내용을 텍스트로 설명 |
| `tables[]` | `{ref, summary}` | 표 존재: `\|` 패턴. `summary`는 LLM 생성 |
| `references[]` | `{target, type, target_norm, resolved_section_id}` | 패턴 매칭 + 정규화 |

### 표 구조화 데이터

| 필드 | 타입 | 설명 |
|------|------|------|
| `tables_data` | object | 표의 구조화된 데이터. chunk_type이 "table"이고 숫자 테이블인 경우 키-값 구조로 생성. 그 외 빈 객체 `{}` |

**`tables` vs `tables_data` 관계:**
- `tables[]`: 모든 표의 참조 메타데이터 (ref, summary). 표가 있으면 항상 존재
- `tables_data`: 숫자 테이블의 구조화 데이터 (rows, columns). 숫자 표에만 생성
- `tables[].ref`의 값이 `tables_data`의 키와 일치 (예: `tables[0].ref = "표 3"` → `tables_data["표 3"]`)
- 텍스트 전용 표: `tables[]`에 ref/summary만, `tables_data`는 빈 객체

`text`에는 마크다운 표가 그대로 유지되며 (LLM 컨텍스트용), `tables_data`는 정확한 계산/검증용 정답 원천.

```jsonc
"tables_data": {
  "표 4": {
    "title": "LONGITUDINAL STRENGTH DATA",
    "notes": ["EACH VALUE SHOWS (ACTUAL VALUE / 1,000)"],
    "columns": ["frame", "sf_base", "sf_cd", "sf_ct", "bm_base", "bm_cd", "bm_ct"],
    "column_labels": {
      "sf_base": "S.F. BASE VALUE",
      "sf_cd": "S.F. CORRECTION (DEPARTURE)",
      "sf_ct": "S.F. CORRECTION (ARRIVAL)",
      "bm_base": "B.M. BASE VALUE",
      "bm_cd": "B.M. CORRECTION (DEPARTURE)",
      "bm_ct": "B.M. CORRECTION (ARRIVAL)"
    },
    "rows": [
      {"frame": 99, "sf_base": 2.876, "sf_cd": 0.401, "sf_ct": -0.398, "bm_base": 18.730, "bm_cd": 2.903, "bm_ct": -3.078},
      {"frame": 94, "sf_base": 11.902, "sf_cd": 1.403, "sf_ct": -1.298, "bm_base": 181.011, "bm_cd": 23.039, "bm_ct": -22.151}
    ]
  }
}
```

- 숫자 테이블(계산표, 허용값표 등)에만 적용. 단순 텍스트 표는 text만으로 충분
- 프레임별/항목별 값 조회, 계산 자동화, 분할 표 병합에 사용
- `columns`: 데이터 컬럼 키 목록, `column_labels`: 원문 컬럼 제목 매핑
- `rows`: 각 행을 key-value 객체로 구조화

### 수식/기호 정의

| 필드 | 타입 | 설명 |
|------|------|------|
| `equations` | array | 청크 내 수식/기호 정의. 없으면 빈 배열 `[]` |

```jsonc
"equations": [
  {
    "name": "shearing_force",
    "symbol": "F_S",
    "expression": "(SS - ΣW) × 9800",
    "variables": {
      "SS": "BUOYANCY & LW 합계",
      "ΣW": "DEADWEIGHT 합계"
    }
  }
]
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `name` | string | 수식 식별명 (snake_case) |
| `symbol` | string | 수식 기호 (예: "F_S", "M_S") |
| `expression` | string | 수식 표현 (human-readable) |
| `variables` | object | 변수 → 설명 매핑 |

- "F_S가 뭐야?", "9800은 왜 곱해?" 같은 질의에 정확한 답변 가능
- 복수 수식이 있으면 배열에 모두 포함

**reference type:**

| type | 예시 |
|------|------|
| `internal` | `5.5`, `5.6` (같은 장 내 참조) |
| `cross_part` | `규칙 7편 4장 1003.`, `지침 3편 부록 3-2` |
| `external` | `SOLAS 74/06/17 Reg.II-1/20`, `MARPOL 부속서 I` |

**reference 확장 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `target` | string | 원문 그대로의 참조 텍스트 |
| `type` | enum | internal / cross_part / external |
| `relation` | enum \| null | 참조의 의미적 관계. 후처리에서 채움. 아래 참조 |
| `target_norm` | object | 정규화된 구조. 해당하는 키만 포함 (optional keys: `part`, `chapter`, `article`). external이면 빈 객체 `{}` |

> `target_norm`에서 null 키 사용 금지. `{"article": "5.5"}`처럼 해당 키만 포함한다.

**relation 값 (KG 엣지 타입):**

| 값 | 의미 | 예시 |
|----|------|------|
| `requires` | A는 B를 충족해야 한다 | "7편 규정에 따라야 한다" |
| `defines` | A가 B의 정의를 제공한다 | "이 장에서 '고장력강'이란..." |
| `restricts` | A가 B의 값을 제한한다 | "최소 두께는 표 X에 따른다" |
| `exempts` | A는 B의 적용을 면제한다 | "다만, 소형 선박은 면제할 수 있다" |
| `supplements` | A가 B를 보완한다 | "추가적으로 다음 사항을 확인한다" |
| `null` | 미분류 (초기 상태) | 후처리 전 기본값 |

- Stage 1(청킹)에서는 `null`로 생성
- 후처리 파이프라인(LLM 분류)에서 의미 분류 후 채움

### 표 초과

| 필드 | 타입 | 설명 |
|------|------|------|
| `table_oversized` | bool | 표 청크가 2000토큰 초과 시 true. LLM에 summary 우선 제공 판단용. 기본 false |

### 키워드

| 필드 | 타입 | 설명 |
|------|------|------|
| `keywords` | string[5] | 도메인 키워드 5개. LLM 생성 |

### KG 확장 필드 (후처리)

아래 필드들은 **청킹 단계(Stage 1)에서 생성하지 않는다.** 별도 후처리 파이프라인(NER, 관계 추출, 조건 파싱)에서 채운다.
청킹 시에는 이 필드들을 포함하지 않거나, 빈 기본값(`[]`, `null`)으로 둔다.

#### domain_entities (도메인 개념 태깅)

| 필드 | 타입 | 설명 |
|------|------|------|
| `domain_entities` | array | 청크 내 도메인 개념 엔티티. 후처리 NER에서 생성. 없으면 `[]` |

```jsonc
"domain_entities": [
  {
    "mention": "액화가스 산적운반선",   // text 내 원문 표현
    "canonical": "LNG_bulk_carrier",   // 정규화 식별자 (DomainOntology 참조)
    "type": "ship_type"                // ship_type | structural_member | equipment | material | inspection | load_condition | parameter
  },
  {
    "mention": "횡격벽",
    "canonical": "transverse_bulkhead",
    "type": "structural_member"
  }
]
```

**entity type 값:**

| 값 | 설명 | 예시 |
|----|------|------|
| `ship_type` | 선종 | 벌크선, LNG선, 컨테이너선 |
| `structural_member` | 구조 부재 | 횡격벽, 종통재, 외판, 이중저 |
| `equipment` | 장비/시스템 | 벤트장치, 가스탐지기, 하역장치 |
| `material` | 재료 | 고장력강, 알루미늄 합금 |
| `inspection` | 검사 유형 | 정기검사, 중간검사, 연차검사 |
| `load_condition` | 하중/조건 | 정수중, 파랑중, 항해상태 |
| `parameter` | 물리량/파라미터 | 종굽힘모멘트, 전단력, 최소 두께 |

#### applicability (적용 범위)

| 필드 | 타입 | 설명 |
|------|------|------|
| `applicability` | object \| null | 이 청크(규정)의 적용 범위. 후처리에서 생성. 미추출이면 `null` |

```jsonc
"applicability": {
  "ship_types": ["LNG_bulk_carrier", "LPG_carrier"],
  "size_conditions": [
    {"attribute": "length", "operator": ">=", "value": 90, "unit": "m"}
  ],
  "date_conditions": [
    {"attribute": "keel_laid", "operator": ">=", "value": "2020-01-01"}
  ]
}
```

- `ship_types`: 적용 대상 선종의 canonical ID 배열. DomainOntology 참조
- `size_conditions`: 크기/톤수 조건. `attribute`는 `length`, `gross_tonnage`, `deadweight` 등
- `date_conditions`: 시간 조건. `attribute`는 `keel_laid`, `delivery_date` 등
- `chunk_type: "intro"` 청크에서 우선 추출

#### normative_values (정량적 규정값)

| 필드 | 타입 | 설명 |
|------|------|------|
| `normative_values` | array | 청크 내 정량적 기준값. 후처리에서 추출. 없으면 `[]` |

```jsonc
"normative_values": [
  {
    "parameter": "minimum_thickness",  // 파라미터 canonical ID
    "symbol": "t_min",                 // 기호 (있으면)
    "value": 12.0,                     // 수치 (수식이면 null)
    "unit": "mm",                      // 단위
    "condition": "고장력강, 주갑판"     // 적용 조건 (자연어)
  }
]
```

- `equations[]`는 수식 정의 (F_S = ...), `normative_values[]`는 수치 기준 (t_min = 12mm)
- 설계 검증 자동화, 수치 비교 질의에 사용

### 운영 메타 (선택)

| 필드 | 타입 | 설명 |
|------|------|------|
| `token_count` | int \| null | 실측 토큰 수. 임베딩 모델 토크나이저 기준 |
| `text_hash` | string \| null | text 필드의 SHA-256. 증분 재인덱싱 시 변경 감지용 |
| `updated_at` | string \| null | 마지막 수정 시각 (ISO 8601). 재처리 범위 결정용 |

### 임베딩 (별도 저장)

임베딩 벡터는 청크 JSON에 포함하지 않는다. 모델 교체/재임베딩 시 청크 데이터를 건드리지 않기 위함.

별도 컬렉션/인덱스에 저장:
```jsonc
{
  "chunk_id": "kr_2025_c0142_1",
  "model": "text-embedding-3-large",
  "dimensions": 3072,
  "vector": [0.012, -0.034, ...],
  "created_at": "2026-02-19T00:00:00Z"
}
```

---

## 5. 토큰 기준

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `target_tokens` | 500 | 분할 목표 크기 |
| `hard_max_tokens` | 900 | 표 등 예외 허용 상한. 이 값을 초과하는 표는 chunk_type: "table"로 통째 유지 |
| `min_tokens` | 50 | 이하이면 chunk_type: "micro"로 태그 |

- 한국어 기준: 1토큰 ≈ 1~2글자 (토크나이저별 편차 있음)
- 실제 운영 전 사용할 임베딩 모델의 토크나이저로 반드시 실측
- 구현 시 설정 파일로 외부화 (스키마에서 하드코딩하지 않음)

---

## 6. 짧은 청크 처리 방침

50토큰 미만의 짧은 섹션은 **물리적으로 병합하지 않는다.**

- `chunk_type: "micro"`로 태그
- 검색에서 히트 시 같은 `section_path`의 직전/직후 청크를 함께 프롬프트에 포함 (adjacent expansion)
- 인용 경계를 명확하게 유지하고, 수정/재인덱싱 시 청크 경계 안정성 확보

---

## 7. 표 처리 방침

표는 중간에서 자르지 않는다.

- 표 전체를 하나의 청크에 포함, `chunk_type: "table"`로 태그
- 표가 hard_max_tokens를 초과하더라도 분할하지 않음
- 향후 검색 품질 문제 확인 시 행(row) 단위 인덱싱 추가 가능 (v0.3)

### 초대형 표 처리

표가 2000토큰을 초과하는 경우:
- `table_oversized: true` 플래그 추가
- LLM 컨텍스트 조립 시 `tables[].summary`를 먼저 제공, 사용자 요청 시 전체 text 제공
- 스키마에 추가 필드: `table_oversized` (bool, 기본 false)

---

## 8. 예시: 분할 없는 청크

```jsonc
{
  "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "chunk_id": "kr_2025_c0088_0",
  "doc_id": "kr_rules_2025_v1",
  "section_index": 88,
  "chunk_seq": 88,
  "section_id": "kr_2025_sec_3편_부록3-1_5.2",
  "chunk_type": "section",
  "section_path": ["3편 선체구조", "부록 3-1", "5.2"],
  "section_title": "정수중 종굽힘 모멘트 및 정수중 전단력의 허용기재예",
  "page_start": 1052,
  "page_end": 1052,
  "locators": {
    "spans": [
      {"source_pdf": "강선규칙_1051-1060.pdf", "pdf_page_start": 2, "pdf_page_end": 2, "doc_page_start": 1052, "doc_page_end": 1052}
    ]
  },
  "context_prefix": "3편 선체구조 > 부록 3-1 > 5.2 정수중 종굽힘 모멘트 및 정수중 전단력의 허용기재예",
  "text": "본선의 정수중 종굽힘모멘트 및 정수중 전단력의 허용값은 항해상태(at sea)와 항내상태(harbor)에 대하여 각각 다음과 같은 값이다.\n\n**항 해**\n\n| 출 력 점 | 정수중 굽힘모멘트 허용값 (+) | ...",
  "split": null,
  "prev_chunk_id": "kr_2025_c0087_0",
  "next_chunk_id": "kr_2025_c0089_0",
  "images": [
    { "ref": "전단력 및 굽힘모멘트 부호 규약", "file": "images/강선규칙_1051-1060_p02_01.png", "description": "선미~선수 방향 전단력 부호 규약(+/- 방향 화살표) 및 굽힘모멘트 부호 규약(호깅/새깅 +/- 표시) 도해" }
  ],
  "tables": [
    { "ref": "항해 허용값 표", "summary": "출력점별 정수중 굽힘모멘트/전단력 허용값 (항해/항내)" }
  ],
  "tables_data": {},
  "references": [],
  "equations": [],
  "keywords": ["종굽힘모멘트", "전단력", "허용값", "항해상태", "항내상태"]
}
```

## 9. 예시: 분할된 청크

```jsonc
{
  "id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
  "chunk_id": "kr_2025_c0142_2",
  "doc_id": "kr_rules_2025_v1",
  "section_index": 142,
  "chunk_seq": 144,
  "section_id": "kr_2025_sec_1편_2장_204",
  "chunk_type": "section",
  "section_path": ["1편 선급등록 및 검사", "2장 선급검사", "204."],
  "section_title": "선종별 추가요건",
  "page_start": 46,
  "page_end": 55,
  "locators": {
    "spans": [
      {"source_pdf": "강선규칙_0041-0050.pdf", "pdf_page_start": 6, "pdf_page_end": 10, "doc_page_start": 46, "doc_page_end": 50},
      {"source_pdf": "강선규칙_0051-0060.pdf", "pdf_page_start": 1, "pdf_page_end": 5, "doc_page_start": 51, "doc_page_end": 55}
    ]
  },
  "context_prefix": "1편 선급등록 및 검사 > 2장 선급검사 > 204. 선종별 추가요건",
  "text": "**3. 액화가스 산적운반선** ...\n\n(1) 단일고장이 발생할 경우 ... \n\n(20) 적용되는 경우 선수미하역장치 ...",
  "split": {
    "group_id": "kr_2025_sec_1편_2장_204|3. 액화가스 산적운반선",
    "split_index": 2,
    "split_total": 7,
    "logical_range": {
      "parent_label": "3. 액화가스 산적운반선",
      "item_start": "(1)",
      "item_end": "(20)"
    }
  },
  "prev_chunk_id": "kr_2025_c0142_1",
  "next_chunk_id": "kr_2025_c0142_3",
  "images": [],
  "tables": [],
  "tables_data": {},
  "references": [
    { "target": "지침 1장 801.", "type": "cross_part", "relation": null, "target_norm": {"part": "지침", "chapter": "1장", "article": "801."} },
    { "target": "7편 1장 1104.", "type": "cross_part", "relation": null, "target_norm": {"part": "7편", "chapter": "1장", "article": "1104."} },
    { "target": "SOLAS 74/00 Reg.II-1/3-2", "type": "external", "relation": null, "target_norm": {} }
  ],
  "equations": [],
  "keywords": ["액화가스", "산적운반선", "화물탱크", "벤트장치", "가스탐지"]
}
```

## 10. 예시: 표 청크

```jsonc
{
  "id": "d4e5f6a7-b8c9-0123-defa-234567890123",
  "chunk_id": "kr_2025_c0095_0",
  "doc_id": "kr_rules_2025_v1",
  "section_index": 95,
  "chunk_seq": 95,
  "section_id": "kr_2025_sec_3편_부록3-1_5.5",
  "chunk_type": "table",
  "table_oversized": false,
  "section_path": ["3편 선체구조", "부록 3-1", "5.5"],
  "section_title": "정수중 종굽힘 모멘트 및 정수중 전단력 계산법",
  "page_start": 1058,
  "page_end": 1059,
  "locators": {
    "spans": [
      {"source_pdf": "강선규칙_1051-1060.pdf", "pdf_page_start": 8, "pdf_page_end": 9, "doc_page_start": 1058, "doc_page_end": 1059}
    ]
  },
  "context_prefix": "3편 선체구조 > 부록 3-1 > 5.5 정수중 종굽힘 모멘트 및 정수중 전단력 계산법",
  "text": "**표 3 정수중 종굽힘 모멘트 (M_S) 및 정수중 전단력 (F_S) 계산표**\n\n| | AFT DRAFT | | BASE DRAFT | ...",
  "split": null,
  "prev_chunk_id": "kr_2025_c0094_0",
  "next_chunk_id": "kr_2025_c0096_0",
  "images": [],
  "tables": [
    { "ref": "표 3", "summary": "Frame별 SHEARING FORCE 및 BENDING MOMENT 계산 양식" }
  ],
  "tables_data": {
    "표 3": {
      "title": "정수중 종굽힘 모멘트 (M_S) 및 정수중 전단력 (F_S) 계산표",
      "notes": ["EACH VALUE SHOWS (ACTUAL VALUE / 1,000)"],
      "columns": ["frame", "sf_base", "sf_cd", "sf_ct", "bm_base", "bm_cd", "bm_ct"],
      "column_labels": {
        "sf_base": "SHEARING FORCE BASE VALUE",
        "sf_cd": "S.F. CORRECTION (DEPARTURE)",
        "sf_ct": "S.F. CORRECTION (ARRIVAL)",
        "bm_base": "BENDING MOMENT BASE VALUE",
        "bm_cd": "B.M. CORRECTION (DEPARTURE)",
        "bm_ct": "B.M. CORRECTION (ARRIVAL)"
      },
      "rows": [
        {"frame": 99, "sf_base": 2.876, "sf_cd": 0.401, "sf_ct": -0.398, "bm_base": 18.730, "bm_cd": 2.903, "bm_ct": -3.078}
      ]
    }
  },
  "references": [],
  "equations": [
    {
      "name": "shearing_force",
      "symbol": "F_S",
      "expression": "(SS - ΣW) × 9800",
      "variables": {"SS": "BUOYANCY & LW 합계", "ΣW": "DEADWEIGHT 합계"}
    },
    {
      "name": "bending_moment",
      "symbol": "M_S",
      "expression": "(ΣM - SB) × 9800",
      "variables": {"ΣM": "DEADWEIGHT ΣM", "SB": "BUOYANCY & LW B.M. 합계"}
    }
  ],
  "keywords": ["계산표", "전단력", "굽힘모멘트", "출력점", "Frame"]
}
```

## 11. 예시: micro 청크

```jsonc
{
  "id": "e5f6a7b8-c9d0-1234-efab-345678901234",
  "chunk_id": "kr_2025_c0200_0",
  "doc_id": "kr_rules_2025_v1",
  "section_index": 200,
  "chunk_seq": 200,
  "section_id": "kr_2025_sec_3편_부록3-1_5.6",
  "chunk_type": "micro",
  "section_path": ["3편 선체구조", "부록 3-1", "5.6"],
  "section_title": "격창적하전단력 계산법",
  "page_start": 1060,
  "page_end": 1060,
  "locators": {
    "spans": [
      {"source_pdf": "강선규칙_1051-1060.pdf", "pdf_page_start": 10, "pdf_page_end": 10, "doc_page_start": 1060, "doc_page_end": 1060}
    ]
  },
  "context_prefix": "3편 선체구조 > 부록 3-1 > 5.6 격창적하전단력 계산법",
  "text": "횡격벽의 전후에 적하창과 공창이 인접하는 경우 **표 5**에 따라 전단력을 수정한다.",
  "split": null,
  "prev_chunk_id": "kr_2025_c0199_0",
  "next_chunk_id": null,
  "images": [],
  "tables": [],
  "tables_data": {},
  "references": [
    { "target": "표 5", "type": "internal", "relation": null, "target_norm": {"article": "표 5"} }
  ],
  "equations": [],
  "keywords": ["격창적하", "전단력", "횡격벽", "수정"]
}
```

---

## 12. 검색 텍스트 조립 가이드

임베딩/검색 인덱싱 시 사용할 텍스트 조립 방식:

| 용도 | 조립 공식 | 설명 |
|------|-----------|------|
| **임베딩 생성** | `text` | 본문만 임베딩. context_prefix는 포함하지 않음 |
| **LLM 프롬프트** | `context_prefix + "\n" + text` | 헤더 컨텍스트 + 본문 |
| **검색 결과 표시** | `context_prefix` (breadcrumb) + `text` (snippet) | UI 표시용 |
| **확장 검색 텍스트** | `context_prefix + section_title + text + tables[].summary + equations[].symbol/name` | 재순위(reranking) 등 정밀 매칭 시 |

**메타 필터로 사용할 필드** (검색 텍스트에 넣지 않음):
- `id`, `chunk_id`, `doc_id`, `page_start/end`, `locators`, `split`

---

## 13. KG 별도 컬렉션

청크 JSON과 분리하여 관리하는 지식 그래프 데이터. 후처리 파이프라인에서 생성.

### DomainOntology (도메인 온톨로지)

선종, 구조부재, 장비, 재료 등의 정규화된 개념 노드와 계층구조.

```jsonc
{
  "id": "ship_type:LNG_bulk_carrier",
  "type": "ship_type",
  "label_ko": "액화가스 산적운반선",
  "label_en": "LNG Bulk Carrier",
  "aliases": ["LNG선", "가스운반선", "액화가스선"],
  "parent": "ship_type:gas_carrier",
  "properties": {
    "imo_code": "GC"
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | string | `{type}:{canonical}` 형식 |
| `type` | enum | `domain_entities[].type`과 동일 |
| `label_ko` | string | 한국어 표준 명칭 |
| `label_en` | string \| null | 영어 명칭 |
| `aliases` | string[] | 동의어, 약어, 변형 |
| `parent` | string \| null | 상위 개념 ID (is-a 관계) |
| `properties` | object | 추가 속성 (IMO 코드, KS 분류 등) |

### ExternalStandards (외부 표준 레지스트리)

SOLAS, MARPOL, IACS, ISO 등 외부 표준의 정규화 레지스트리.

```jsonc
{
  "id": "ext:SOLAS_II-1_3-2",
  "standard": "SOLAS",
  "organization": "IMO",
  "full_title": "International Convention for the Safety of Life at Sea",
  "chapter": "II-1",
  "regulation": "3-2",
  "edition": "1974/2006/2017",
  "aliases": ["SOLAS 74/06/17 Reg.II-1/3-2", "SOLAS II-1/3-2", "SOLAS 74/00 Reg.II-1/3-2"]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | string | `ext:{standard}_{chapter}_{regulation}` 형식 |
| `standard` | string | 표준명 (SOLAS, MARPOL, IACS UR 등) |
| `organization` | string | 발행 기관 (IMO, IACS, ISO 등) |
| `full_title` | string | 정식 명칭 |
| `chapter` | string \| null | 장/부속서 |
| `regulation` | string \| null | 규정 번호 |
| `edition` | string \| null | 판/개정 연도 |
| `aliases` | string[] | `references[].target`에 등장하는 다양한 문자열 표현 |

- `references[].type == "external"`의 `target`을 이 레지스트리에 매핑
- 동일 표준의 서로 다른 표현을 하나의 ID로 통합

### RuleGraph (규칙 의존성 그래프)

섹션 간 의미적 관계 엣지. `references[]`에서 파생.

```jsonc
{
  "id": "edge_001",
  "source_section_id": "kr_2025_sec_1편_2장_204",
  "target_section_id": "kr_2025_sec_7편_4장_1003",
  "relation": "requires",
  "condition": "액화가스 산적운반선에 한함",
  "source_chunk_id": "kr_2025_c0142_2",
  "confidence": 0.95
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | string | 엣지 고유 ID |
| `source_section_id` | string | 출발 섹션 |
| `target_section_id` | string | 도착 섹션 |
| `relation` | enum | `references[].relation`과 동일 |
| `condition` | string \| null | 관계 적용 조건 (자연어) |
| `source_chunk_id` | string | 출처 청크 (provenance) |
| `confidence` | float | 추출 신뢰도 (0~1) |

### ConditionalRules (조건-규칙)

"A이면 B를 적용한다" 형태의 조건부 규정을 구조화.

```jsonc
{
  "id": "cond_001",
  "source_chunk_id": "kr_2025_c0142_2",
  "conditions": [
    {"type": "ship_type", "value": "LNG_bulk_carrier"},
    {"type": "attribute", "attribute": "single_failure", "operator": "==", "value": true}
  ],
  "logic": "AND",
  "consequence": {
    "action": "apply",
    "target_section_id": "kr_2025_sec_7편_1장_1104",
    "description": "화물탱크 벤트장치 요건 적용"
  },
  "confidence": 0.90
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `conditions[]` | array | 조건 목록 |
| `logic` | enum | `AND` / `OR` |
| `consequence` | object | 결과 (action + target + description) |
| `confidence` | float | 추출 신뢰도 |

---

## 14. KG 구축 로드맵

현재 v0.7 청킹 파이프라인을 기반으로 단계별 KG 확장.

### Phase 1 (즉시 — 스키마 변경 최소)

- `references[].relation` 추가: 기존 참조 데이터 위에 LLM 분류만 추가
- 외부 표준 룩업 테이블(ExternalStandards) 구축: 정규식 + 수작업
- **결과**: 규칙 참조 그래프 v1

### Phase 2 (단기 — NER 파이프라인)

- `domain_entities[]` 추출: 도메인 NER + Entity Linking
- `applicability` 추출: `chunk_type: "intro"` 청크 우선 처리
- DomainOntology 초기 구축: 선종/부재/장비 계층
- **결과**: 선종별/부재별 규정 검색

### Phase 3 (중기 — 조건 추출)

- ConditionalRules 추출: LLM structured output
- `normative_values[]` 추출: 수치+단위+조건 트리플
- **결과**: 조건부 규정 질의, 수치 비교

### Phase 4 (장기 — 완전한 KG)

- 시간축 관리: 다중 버전 비교, 경과 조치
- DomainOntology 체계화: is-a/part-of 추론
- 다중 문서 간 정합: cross-document alignment
- **결과**: 완전한 해양 선급 KG

### 후처리 파이프라인 순서

```
NER → Entity Linking → Relation Classification → Condition Extraction
 → Applicability Parsing → KG Triple 생성 (→ Neo4j/RDF)
```

---

## v0.1 → v0.2 변경 요약

| 항목 | v0.1 | v0.2 |
|------|------|------|
| PK | chunk_id (규칙 기반) | `id` (UUID) + `chunk_id` (가독성) |
| 청크 분류 | 없음 | `chunk_type`: section / table / image_caption / micro |
| 헤더 반복 | text에 포함 | `context_prefix` 분리. text는 본문만 |
| 분할 범위 | split_boundary (LLM 문자열) | `logical_range` (결정론적, 구조화) |
| 원본 위치 | page_start/end만 | `locators` 추가 (원본 PDF, 페이지 범위) |
| 토큰 기준 | 500 고정 | target/hard_max/min 3단계, 실측 후 조정 |
| 짧은 청크 | 이전 청크에 병합 | 병합 안 함, chunk_type: "micro" + 검색 시 인접 확장 |
| 표 처리 | 통째 원칙 | 통째 유지 + chunk_type: "table" 태그 |

## v0.2 → v0.3 변경 요약

| 항목 | v0.2 | v0.3 |
|------|------|------|
| 청크 순번 | `chunk_index` (분할 시 중복) | `section_index` (섹션 순번) + `chunk_seq` (유일 순번) |
| 원본 위치 | `locators` (단일 span) | `locators.spans[]` (다중 span 지원) |
| 분할 판단 | `split.is_split` (중복) | `split` 존재 여부로 판단 (`is_split` 제거) |
| 섹션 식별 | `split_group_id` (분할 시만) | `section_id` (항상 존재, 분할 무관) |
| 도입부 | 별도 처리 없음 | `chunk_type: "intro"` 도입 |
| 초대형 표 | 별도 처리 없음 | `table_oversized` 플래그 + summary 우선 제공 |
| 참조 해결 | `{target, type}` | `target_norm` + `resolved_section_id` 추가 |
| 재현성 | 없음 | Documents에 sha256, pipeline_version, chunking_config |
| 운영 메타 | 없음 | Chunks에 token_count, text_sha256 (선택) |

## v0.3 → v0.4 변경 요약

| 항목 | v0.3 | v0.4 |
|------|------|------|
| 표 구조화 | text에 마크다운 표만 | `tables_data` 추가 (숫자 테이블 → rows/columns 구조화) |
| 분할 연결 | section_id로만 그룹핑 | `prev_chunk_id` / `next_chunk_id` 순차 연결 추가 |
| 페이지 구분 | spans에 page_start/end (의미 모호) | `pdf_page_start/end` (분할 PDF 내) + `doc_page_start/end` (전체 문서 절대 페이지) |
| 수식/기호 | text에 포함 | `equations` 배열 추가 (name, symbol, expression, variables) |
| 검색 가이드 | 없음 | 검색 텍스트 조립 가이드 추가 (임베딩/LLM/표시/확장 별 조립 공식) |

## v0.4 → v0.5 변경 요약

| 항목 | v0.4 | v0.5 |
|------|------|------|
| `continue` | 병합 이력 필드 (merged, sources) | **삭제**. `prev/next_chunk_id`로 연결 단일화. 병합 출처는 `locators.spans`로 확인 |
| `split.group_id` | 없음 (section_id + split_index로 추론) | 분할 묶음 식별자 추가. `{section_id}\|{parent_label}` 형식 |
| null vs 빈값 | 혼재 (`tables_data: null`, `equations: null`, `tables: []`) | **타입 통일**: `tables_data: {}`, `equations: []` (항상 같은 타입, null 사용 안 함) |
| 순번 명칭 | `section_index`, `chunk_seq` (정의 모호) | 정의 명확화: section_index=섹션 등장 순서, chunk_seq=문서 전체 청크 순번(유일, 연속) |
| 검증 방식 | PyMuPDF 기반 커버리지 검증 | verify_chunks.py는 스키마+구조만 검증. 커버리지는 Stage 2 에이전트가 PDF Read로 직접 확인 |

## v0.5 → v0.6 변경 요약

| 항목 | v0.5 | v0.6 |
|------|------|------|
| `page_start/end` | locators.spans와 역할 모호 | **파생 필드** 명시. `min/max(spans[].doc_page_start/end)`로 자동 도출. locators가 정본 |
| 식별자 | 역할 구분 없음 | 역할 칼럼 추가 (내부 PK, 안정 키, FK, 그룹 키, 정렬 키, 섹션 식별, 분류) |
| `embedding` | 청크 JSON 내 필드 (`null`) | **삭제**. 별도 컬렉션에 저장 (모델 교체 시 청크 데이터 불변) |
| `target_norm` | null 키 혼재 (`"part": null`) | **optional keys**: 해당 키만 포함, null 키 금지. external이면 빈 객체 `{}` |
| `tables` vs `tables_data` | 관계 미명시 | 관계 명시: `tables[].ref` → `tables_data` 키 매핑 |
| 운영 메타 | `token_count`만 | `text_hash`, `updated_at` 추가 (증분 재인덱싱, 수정 이력) |

## v0.6 → v0.7 변경 요약

| 항목 | v0.6 | v0.7 |
|------|------|------|
| KG 확장 | 없음 | `domain_entities[]`, `applicability`, `normative_values[]` 추가 (후처리 생성) |
| `references[].relation` | 없음 | 의미적 관계 타입 추가 (requires/defines/restricts/exempts/supplements). 초기 null |
| `effective_version` | 없음 | Documents에 규정 시간축 (rule_edition, effective_date, amendment_no, supersedes) |
| 별도 컬렉션 | 임베딩만 | DomainOntology, ExternalStandards, RuleGraph, ConditionalRules 스펙 추가 |
| KG 로드맵 | 없음 | 4단계 구축 로드맵 (Phase 1~4) + 후처리 파이프라인 순서 정의 |
