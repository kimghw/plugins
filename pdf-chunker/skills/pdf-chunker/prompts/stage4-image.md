# Stage 4: 이미지 분석

이미지가 있고 IMAGE_DESCRIPTION=true인 경우에만 실행합니다.

1. chunks.json에서 images[]가 비어있지 않은 청크 찾기
2. 각 이미지에 대해:
   a. 해당 청크의 text + 인접 청크 text 읽기 (문맥 수집)
   b. 이미지 파일을 Read로 읽기
   c. description 작성 (1~3문장):
      - 플로우차트 → 흐름/판단조건
      - 도해 → 구조/부호
      - 그래프 → 축/곡선/수치
      - 배치도 → 구획/Frame
      - 구조도 → 부재명칭
3. images[].description에 설명을 채워 Write로 저장
