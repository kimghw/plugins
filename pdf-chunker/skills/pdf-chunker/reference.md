# PDF → 청크 JSON 변환 플러그인 레퍼런스

## 플러그인 구조

공식 Claude Code 플러그인 구조를 따릅니다. `claude --plugin-dir ./plugins/pdf-chunker`로 로드합니다.

```
plugins/pdf-chunker/
├── .claude-plugin/
│   └── plugin.json              # 플러그인 매니페스트
├── skills/
│   └── pdf-chunker/
│       ├── SKILL.md             # 스킬 정의
│       ├── config.sh            # 경로 설정 (★ 새 프로젝트에서 이것만 수정)
│       ├── chunk-schema.md      # 청크 JSON 스키마 정의
│       ├── reference.md         # 이 파일
│       ├── prompts/             # 서브에이전트 프롬프트 (Stage별 분리)
│       │   ├── agent.md          # 메인 프롬프트 (실행 순서, stage 파일 경로)
│       │   ├── stage1-structure.md  # Stage 1: PDF→chunks.json 구조화
│       │   ├── stage4-image.md       # Stage 4: 이미지 분석 (선택, Stage 3 이후)
│       │   ├── stage2-codex.md      # Stage 2: Codex MCP 검증
│       │   ├── stage2-gemini.md     # Stage 2: Gemini MCP 검증
│       │   └── stage3-review.md     # Stage 3: 검증 결과 반영 + verify
│       └── scripts/
│           ├── split_pdf.py      # PDF 분할 (11페이지 이상 → 10페이지씩)
│           ├── extract_images.py  # 이미지 추출 (조각 합침, 벡터 포함)
│           ├── verify_chunks.py   # 청크 JSON 통합 검증
│           ├── verify_markdown.py # 검증 스크립트 (레거시)
│           ├── queue_manager.sh   # 공유 큐 관리
│           └── setup_mcp.sh       # MCP 서버 자동 설정 (Codex/Gemini)
├── hooks/
│   └── hooks.json               # 후크 선언 (현재 비활성)
└── commands/
    ├── convert.md               # 변환 커맨드 (코디네이터)
    ├── setup.md                 # 초기 설정 커맨드 (경로 + MCP + 다사용자)
    └── cowork.md                # 협업 설정 커맨드
```

### 새 프로젝트에서 사용하기

1. 플러그인 폴더 복사 또는 `claude plugin install`
2. `skills/pdf-chunker/config.sh`에서 경로 수정:
   ```bash
   PDF_DIR="$PROJECT_DIR/path/to/pdf"
   MD_DIR="$PROJECT_DIR/path/to/markdown"
   IMG_DIR="$MD_DIR/images"
   ```
3. `claude --plugin-dir ./plugins/pdf-chunker`로 실행

---

## config.sh

모든 경로의 단일 진실 원천(Single Source of Truth)입니다.
스크립트, 후크, 커맨드 모두 이 파일을 `source`합니다.

```bash
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-...}"
PLUGIN_DIR="${CLAUDE_PLUGIN_DIR:-...}"
PDF_DIR="/home/kimghw/kgc/pdf-source/chunks"
MD_DIR="/home/kimghw/kgc/pdf-source/output"
IMG_DIR="$MD_DIR/images"
QUEUE_DIR="/home/kimghw/kgc/.queue"
QUEUE_PENDING="$QUEUE_DIR/pending"
QUEUE_PROCESSING="$QUEUE_DIR/processing"
QUEUE_DONE="$QUEUE_DIR/done"
QUEUE_FAILED="$QUEUE_DIR/failed"
INSTANCE_ID="$(hostname -s)_pid-$$"
STALE_THRESHOLD=1800
SKILL_DIR="$PLUGIN_DIR/skills/pdf-chunker"
QUEUE_SCRIPT="$SKILL_DIR/scripts/queue_manager.sh"
```

---

## 후크 설정

현재 후크는 비활성 상태입니다 (`hooks/hooks.json`이 비어있음).
이전에 사용하던 자동 연속 실행 후크(auto-next-batch, check-failed-tasks)는 제거되었습니다.

---

## 공유 큐

### 디렉토리 구조

```
/home/kimghw/kgc/.queue/
├── pending/       ← 대기 (.task 파일)
├── processing/    ← 작업 중 (mv로 원자적 할당)
├── done/          ← 완료
└── failed/        ← 실패
```

### .task 파일 형식

```
pdf=강선규칙_0201-0210.pdf
created_at=2026-02-13T10:00:00Z
claimed_by=machine-A_pid-12345
claimed_at=2026-02-13T10:05:30Z
completed_at=
error=
```

### 큐 관리
```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"

# 큐 초기화
bash "$QUEUE_SCRIPT" init

# 작업 할당 (원자적, 동시 접근 안전)
bash "$QUEUE_SCRIPT" claim 10

# 작업 완료/실패
bash "$QUEUE_SCRIPT" complete "강선규칙_0201-0210"
bash "$QUEUE_SCRIPT" fail "강선규칙_0201-0210" "에러 메시지"

# stale 작업 복구
bash "$QUEUE_SCRIPT" recover

# 현황 확인
bash "$QUEUE_SCRIPT" status
```

### 동시 접근 안전성

- `mv` 명령으로 원자적 할당: 두 인스턴스가 동시에 같은 파일을 가져가면 하나만 성공
- 세션 종료 시 해당 인스턴스의 미완료 작업 자동 반환 (다른 인스턴스가 이어서 처리)
- 30분 초과 stale 작업 자동 복구
- 각 인스턴스는 `hostname_pid-$$` 형식의 고유 ID로 식별

### 멀티 인스턴스 사용 가이드

동일 PC의 여러 터미널, 또는 클라우드 저장소를 통한 여러 PC에서 동시 작업이 가능합니다.

**사전 조건**:
- 큐 초기화(`init`)가 최소 한 번 실행된 상태

**시작 방법**:
```bash
# 터미널 A (최초 1회)
cd /path/to/project && claude --plugin-dir ./plugins/pdf-chunker
# → /pdf-chunker init  (큐 초기화)
# → /pdf-chunker start (배치 시작)

# 터미널 B, C, ... (추가 인스턴스)
cd /path/to/project && claude --plugin-dir ./plugins/pdf-chunker
# → /pdf-chunker start (init 없이 바로 시작)
```

**안전 보장**:
| 시나리오 | 동작 |
|----------|------|
| 두 인스턴스가 동시에 같은 작업 할당 시도 | `mv`가 하나만 성공, 나머지 실패 (충돌 없음) |
| 한 인스턴스가 비정상 종료 | 30분 후 stale 복구 → pending으로 자동 반환 |
| 한 인스턴스가 정상 종료 | Stop 후크가 미완료 작업을 즉시 pending으로 반환 |
| 큐 초기화를 여러 번 실행 | 기존 상태 유지, 신규 PDF만 추가 등록 |

**권장 인스턴스 수**: 2~10개

---

## 마크다운 변환 규칙

| 요소 | 마크다운 문법 |
|------|--------------|
| 편 제목 | `#` |
| 장 제목 | `##` |
| 절 제목 | `##` |
| 조항 번호 | `###` (예: `### 101. 용어의 정의`) |
| 용어 정의 | `**용어**` |
| 표 | 마크다운 표 문법 |
| 목록 | `-` 또는 숫자 목록 |
| 이미지 | `![설명](images/파일명.png)` |

---

## 이미지 추출 (extract_images.py)

### 동작 원리
1. PDF 내 이미지 오브젝트의 위치(bbox) 파악
2. 같은 페이지에서 y좌표가 근접한 이미지 조각을 자동 그룹핑
3. 그룹 영역을 300dpi로 클립 렌더링 (벡터 그래픽 포함)
4. 캡션이 있으면 파일명에 반영, 없으면 페이지+순번

### 결과 파일명
- 캡션 있음: `그림_1.2.1_화물창의_대표적인_횡단면.png`
- 캡션 없음: `강선규칙_0021-0030_p07_01.png`

---

## 검증

```bash
python3 "$SKILL_DIR/scripts/verify_markdown.py" "$PDF_DIR/XXX.pdf" "$MD_DIR/XXX.md" -v
```

기준: 커버리지 90% 이상이면 양호
