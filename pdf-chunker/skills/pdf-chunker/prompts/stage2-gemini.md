# Stage 2: Gemini 검증 + ontology 키워드 추출

Gemini는 stateless이므로 각 Step을 독립적으로 호출합니다.

## Step 1 — mcp__gemini__ask-gemini 호출

PDF를 마크다운으로 변환합니다.

```
prompt: "@{{PDF_DIR}}/{{PDF_FILE}} 이 PDF를 읽고 충실한 마크다운으로 변환하세요. 표는 마크다운 표, 수식은 LaTeX. 요약/생략 없이 원문 전체를 변환하세요."
model: "gemini-3-pro-preview"
```

→ 결과를 `{{MD_DIR}}/[파일명].review.md`에 Write로 저장

## Step 2 — mcp__gemini__ask-gemini 호출

review.md 내용 + chunks.json 내용을 프롬프트에 포함하여 검증 + ontology 추출을 요청합니다.

```
prompt에 포함할 내용:
- review.md 전문 (Step 1 결과)
- chunks.json 전문

작업:
A. 커버리지 검증: MD에 있는데 chunks text에 없는 텍스트 → coverage_issues
B. 환각 체크: chunks text에 있는데 MD에 없는 내용 → hallucination_suspects
C. ontology 키워드: 각 청크에서 7가지 entity type 추출 → ontology_keywords
   entity types: ship_type, structural_member, equipment, material, inspection, load_condition, parameter

JSON 형식:
{
  "coverage_issues": [{"chunk_seq": N, "missing_text": "누락 텍스트", "location": "MD 내 위치"}],
  "hallucination_suspects": [{"chunk_seq": N, "suspect_text": "의심 텍스트", "reason": "사유"}],
  "ontology_keywords": {"0": [{"mention": "원문표현", "type": "entity_type"}], ...},
  "summary": {"total_chunks": N, "coverage_issues": N, "hallucination_suspects": N, "ontology_total": N}
}
```

→ 결과를 `{{MD_DIR}}/[파일명].review.json`에 Write로 저장

## Gemini 실패 시

Gemini MCP 호출이 실패하면:
- review.json 없이 Stage 3으로 이동
- Stage 3에서 PDF 직접 대조 방식으로 검증 진행
- 로그에 실패 사유 기록
