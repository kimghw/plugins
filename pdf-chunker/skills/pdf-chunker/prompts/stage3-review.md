# Stage 3: 검증 결과 반영 + 최종 검증

1. review 파일이 있으면 Read로 읽기: `{{MD_DIR}}/[파일명].review.{{REVIEW_MODEL}}.json`

2. **coverage_issues** 처리:
   - 누락 텍스트가 있으면 PDF를 Read로 다시 확인
   - 실제 누락이면 해당 청크의 text에 추가
   - 포맷 차이(LaTeX vs plain text, 헤더가 section_path에 이미 포함 등)는 false positive → 무시

3. **hallucination_suspects** 처리:
   - 검토 후 실제 환각이면 해당 텍스트 삭제
   - 유니코드/수식 표기 차이에 의한 유사도 불일치는 false positive → 무시

4. **ontology_keywords** 처리:
   - review 파일의 키워드를 기존 chunks.json의 ontology_keywords와 병합 (union, 중복 제거)
   - 각 청크에 ontology_keywords 필드 추가/업데이트

5. review 파일이 없으면 (Stage 2 스킵/실패 시):
   - PDF를 Read로 읽어 chunks.json text와 직접 대조
   - 누락 텍스트 확인 후 추가

6. 스키마/구조 자동 검증:
   ```bash
   python3 "{{PLUGIN_DIR}}/skills/pdf-chunker/scripts/verify_chunks.py" "{{MD_DIR}}/[파일명].chunks.json" -v
   ```

7. 스키마/구조 에러가 있으면 수정 후 재검증

8. 모든 검증 통과 시:
   ```bash
   bash "{{PLUGIN_DIR}}/skills/pdf-chunker/scripts/queue_manager.sh" complete "[파일명]"
   ```

9. 수정 불가능한 에러 시:
   ```bash
   bash "{{PLUGIN_DIR}}/skills/pdf-chunker/scripts/queue_manager.sh" fail "[파일명]" "에러 설명"
   ```

10. 로그 저장 — 아래 내용을 로그 파일에 Write로 저장 (`{{LOG_DIR}}/[파일명].log`):
    - Stage 1: 처리 페이지 수, 생성 청크 수, 이미지 수, 경고/에러
    - Stage 2: MCP 호출 성공/실패, review 파일 요약 (issues 수, ontology 수)
    - Stage 3: 수정 항목, verify_chunks.py 결과, 최종 OK/FAIL
