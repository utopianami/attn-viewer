# CLAUDE.md

attn-viewer — 번역 리더(뷰어) + 금융 QA 엔진 + 메모리 섹터 대시보드가 한 리포에 있다.
작업 규칙의 원본은 AGENTS.md(계약 우선·모바일 우선·스토리지 규칙).

## 명령
- 서버: `npm start` (dev: `npm run dev`), ngrok 터널: `npm run tunnel`
- Node 테스트: `node --test lib/*.test.mjs`
- 엔진 테스트(오프라인): `cd engine && .venv/bin/python -m pytest -c pytest.ini tests -m "not live"`
- **bare `pytest` 금지** — live 마커 테스트(실네트워크)와 engine/poc/(test_workflow는 오프라인
  pytest, test_providers는 실 API 키·과금 가능)까지 수집된다. 반드시 위처럼 경로·마커를 한정할 것.
- 운영 서버에서 PM2가 관리하는 엔진을 재시작할 때는 `pm2 restart attn-engine`만 사용
  (pkill+nohup 금지 — PM2가 즉시 부활시켜 포트 충돌)

## 런타임 (운영 서버 기준)
PM2 앱 4개 등록: attn-viewer(server.mjs) · attn-engine(uvicorn engine.app.main:app, :8801)
· attn-vault-bridge · attn-ngrok(선택적 — 중지 상태일 수 있음).
로컬에서는 `npm start`로 뷰어를, engine/.venv의 uvicorn으로 엔진(`engine.app.main:app`)을 띄울 수 있다.

## 구조
- `server.mjs` + `lib/`(인증·문서 유틸·블로그·메모리 프록시·엔진 클라이언트 등 보조 모듈) —
  Express API·인증·문서/블로그/메모리 기능. UI는 `public/index.html`(모바일 우선)
- `engine/` — Python FastAPI (venv: engine/.venv, sys.path 루트는 engine/,
  engine 루트 기준 절대 import가 지배적 관례)
  - `app/main.py` 진입점 → `orchestrator.py`(QA 파이프라인 드라이버) → `stages/` → `tools/`(가격·뉴스·Toss·계산)
  - `sector/` — 서브시스템 3개 공존: 대시보드(store/api/collectors), 시황 리포트(report_*), thesis 레이어(thesis_*)
  - `casemem/` — 과거사례 지식층(RAG/CBR), `evals/` — 평가 하니스(수동 CLI)
- "contracts" 모듈 5곳(engine/contracts/, sector/contracts.py, sector/report_contracts.py,
  sector/thesis_contracts.py, casemem/contracts.py) — 계층별 별도 계약.
  **동일 클래스명이 서로 다른 계약 모듈에 존재**(예: Evidence, ClaimVerdict) — import 경로 확인 필수.
- `sector/collectors/` — 수집기 모듈별 NAME/KIND/collect 규약. 공용 파싱 헬퍼는 `_util.py`.
- `openapi.yaml` — API 계약 기준 문서(계약 우선 원칙). 단 미등재 라우트가 있다(비포괄 예시:
  KG `/kg`·`/api/kg/*`, `/v1/case-memory/*`, `/v1/sector/*` 일부) — 라우트 변경 시 같은 변경에서 갱신할 것.

## 주의
- 공유 운영 워크트리에서 작업할 때: 커밋 전 브랜치·스테이징 확인, 무관 변경 커밋 금지.
- 파일 삭제·이동 전 동적 참조 확인 필수: PM2·subprocess 경로 문자열·express.static·glob/readdir 기반 로딩이 많다.

## 처음 읽는 순서
README(설치·실행) → AGENTS.md(규칙) → 작업 대상 API의 openapi.yaml 경로 → 해당 진입점
(뷰어: server.mjs·lib/, 엔진: engine/app/main.py). docs/는 전부 읽지 말고 작업 관련 설계 문서만.
