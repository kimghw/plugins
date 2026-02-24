# Stage 1: 구조화 (PDF → chunks.json)

1. Read로 PDF 읽기: `{{PDF_DIR}}/{{PDF_FILE}}`
2. 청크 스키마를 Read로 읽기: `{{PLUGIN_DIR}}/skills/pdf-chunker/chunk-schema.md`
3. 청크 JSON 직접 생성 (chunk-schema.md v0.7):
   - ### 최하위 헤딩 단위로 청킹, 각 청크에 section_id 부여
   - 섹션 도입부(공통 정의/적용조건)는 chunk_type: "intro"로 분리
   - 500토큰 초과 시 **(1)**/(가) 경계에서 분할, split.group_id 부여 ({section_id}|{parent_label})
   - 50토큰 미만은 chunk_type: "micro", 표는 통째 chunk_type: "table"
   - 2000토큰 초과 표는 table_oversized: true
   - 각 청크에: section_id, section_path, context_prefix, images[], tables[], references[], keywords(5개)
   - images[].description: 빈 문자열 ""로 설정 (Stage 4에서 채움)
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
4. Write로 저장: `{{MD_DIR}}/[파일명].chunks.json`
5. 이미지 추출:
   ```bash
   python3 "{{PLUGIN_DIR}}/skills/pdf-chunker/scripts/extract_images.py" "{{PDF_DIR}}/{{PDF_FILE}}" -o "{{IMG_DIR}}" -v
   ```
