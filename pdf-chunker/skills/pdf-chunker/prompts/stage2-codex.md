# Stage 2: Codex 검증 + ontology 키워드 추출

하나의 MCP 세션에서 PDF→MD 변환 + 검증 + ontology 추출을 모두 처리합니다.

## Step 1 — mcp__codex-agent__codex 호출

PDF를 마크다운으로 변환합니다.

```
prompt: "이 PDF 파일을 읽고 충실한 마크다운으로 변환하세요. 표는 마크다운 표, 수식은 LaTeX, 이미지 참조는 ![설명](경로) 유지. 요약/생략 없이 원문 전체를 변환하세요. 변환된 마크다운을 {{MD_DIR}}/[파일명].review.md 파일로 저장하세요."
cwd: "{{PDF_DIR}}"
model: "gpt-5.3-codex"
sandbox: "workspace-write"
approval-policy: "never"
```

→ threadId를 보존합니다.

## Step 2 — mcp__codex-agent__codex-reply 호출 (같은 threadId)

방금 변환한 마크다운과 chunks.json을 비교 검증합니다.

```
prompt: "방금 변환한 마크다운과 아래 chunks.json을 비교 검증하세요.

chunks.json 경로: {{MD_DIR}}/[파일명].chunks.json

작업:
A. 커버리지 검증: 마크다운에 있는데 chunks.json의 text에 없는 텍스트 → coverage_issues
B. 환각 체크: chunks.json text에 있는데 마크다운에 없는 내용 → hallucination_suspects
C. ontology 키워드: 각 청크 text에서 7가지 entity type 키워드 추출 → ontology_keywords
   entity types: ship_type, structural_member, equipment, material, inspection, load_condition, parameter

결과를 아래 JSON 형식으로 {{MD_DIR}}/[파일명].review.json 파일에 저장하세요:
{
  \"coverage_issues\": [{\"chunk_seq\": N, \"missing_text\": \"누락 텍스트\", \"location\": \"MD 내 위치\"}],
  \"hallucination_suspects\": [{\"chunk_seq\": N, \"suspect_text\": \"의심 텍스트\", \"reason\": \"사유\"}],
  \"ontology_keywords\": {\"0\": [{\"mention\": \"원문표현\", \"type\": \"entity_type\"}], ...},
  \"summary\": {\"total_chunks\": N, \"coverage_issues\": N, \"hallucination_suspects\": N, \"ontology_total\": N}
}"
```

## Codex 실패 시

Codex MCP 호출이 실패하면(권한 거부, 타임아웃 등):
- review.json 없이 Stage 3으로 이동
- Stage 3에서 PDF 직접 대조 방식으로 검증 진행
- 로그에 실패 사유 기록
