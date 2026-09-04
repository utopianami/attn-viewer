# 시황 리포트 읽기 편집본 배포

편집본 JSON은 원본의 수치·출처·상세 분석을 수정하지 않고, 읽기 가이드만
추가한다. `openapi.yaml`의 `MarketReport` 계약 검증을 통과한 새 파일만 원자적으로
게시되며 기존 파일은 덮어쓰지 않는다.

저장소 루트에서 다음처럼 생성한다. 서버는 리포트 파일을 요청마다 읽으므로
정상 생성 후 프로세스를 재시작할 필요가 없다.

```bash
node scripts/create-report-editorial.mjs \
  --base storage/rag/memory_sector/reports/2026-09-04-1.json \
  --overlay content/report-editorials/2026-09-04-2.json \
  --output storage/rag/memory_sector/reports/2026-09-04-2.json
```

편집본은 목록에서 편집 제목과 원본 ID가 표시되고, `editedAt`을 기준으로 원본보다
먼저 정렬된다. 생성 전에는 `id`, `seq`, `baseReportId`, `baseGeneratedAt`을 원본과
대조한다.
