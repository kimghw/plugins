# PDF → 청크 JSON 변환 에이전트

PDF 파일에서 구조화된 청크 JSON을 생성하고, 검증하고, 수정합니다.

## 설정값

Task prompt에서 전달받은 값을 사용합니다.
프롬프트 파일 내 `{{변수명}}`은 아래 설정값으로 대체하여 실행하세요.

- `{{PLUGIN_DIR}}` — 플러그인 루트 디렉토리
- `{{PDF_DIR}}` — PDF 원본 디렉토리
- `{{MD_DIR}}` — 청크 JSON 출력 디렉토리
- `{{IMG_DIR}}` — 이미지 출력 디렉토리
- `{{LOG_DIR}}` — 로그 디렉토리
- `{{PDF_FILE}}` — 대상 PDF 파일명 (예: 강선규칙_1031-1040.pdf)
- `{{REVIEW_MODEL}}` — 검증 모델 (codex / gemini / off)
- `{{IMAGE_DESCRIPTION}}` — 이미지 분석 여부 (true / false)

파일명 stem (확장자 제외)은 `{{PDF_FILE}}`에서 `.pdf`를 제거한 값입니다.

## 실행 순서

각 Stage 프롬프트를 **Read로 읽고** 지시에 따라 실행하세요.

### 1. Stage 1 — 구조화

Read: `{{PLUGIN_DIR}}/skills/pdf-chunker/prompts/stage1-structure.md`

PDF를 읽고 청크 JSON을 생성합니다.

### 2. Stage 2 — 검증 + ontology 키워드 추출 (선택)

`{{REVIEW_MODEL}}`이 `off`이면 이 단계를 건너뜁니다.

- `{{REVIEW_MODEL}}`이 `codex`이면:
  Read: `{{PLUGIN_DIR}}/skills/pdf-chunker/prompts/stage2-codex.md`

- `{{REVIEW_MODEL}}`이 `gemini`이면:
  Read: `{{PLUGIN_DIR}}/skills/pdf-chunker/prompts/stage2-gemini.md`

### 3. Stage 3 — 검증 결과 반영 + 최종 검증

Read: `{{PLUGIN_DIR}}/skills/pdf-chunker/prompts/stage3-review.md`

### 4. Stage 4 — 이미지 분석 (선택)

`{{IMAGE_DESCRIPTION}}`이 `true`이고 chunks.json에 이미지가 있을 때만 실행합니다.
Stage 3에서 chunks.json이 확정된 후 실행하므로 재작업이 없습니다.

Read: `{{PLUGIN_DIR}}/skills/pdf-chunker/prompts/stage4-image.md`

## 결과 보고

반드시 아래 **한 줄 형식**으로만 반환하세요:

```
OK [파일명] 청크N개
```
또는
```
FAIL [파일명] 에러사유
```
