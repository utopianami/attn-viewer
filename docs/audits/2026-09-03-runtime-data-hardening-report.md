# attn-viewer 런타임·데이터 최종 점검 보고서

- 점검일: 2026-09-03 UTC
- 기준 커밋: `9faccc7`
- 대상: 리포트 생성, 블로그 수집·요약, PM2/systemd, 스케줄러, 런타임 데이터, 테스트
- 원칙: API·사용자 동작 유지, 사용자 스토리지 보존, 변경 전 외부 백업

## 결론

중복 PM2 등록과 API 프로세스에 결합된 스케줄러가 서로 증폭되어 리포트·수집을
중복 실행하던 장애를 제거했다. 현재 PM2에는 viewer, engine API, scheduler,
bridge가 각각 1개만 등록되어 있고, 3000/8801/8792 포트에도 각각 1개만 바인딩된다.
engine API는 스케줄러를 시작하지 않으며 전용 worker 하나가 sector 수집, 리포트,
모니터 일정을 소유한다. worker 안에서 동시에 발생하는 수집 요청도 하나의 자식
프로세스에 합류하며, 교착된 자식은 30분 뒤 종료·회수된다.
collector는 별도 process group으로 시작되므로 worker 종료나 hard timeout 때
그 아래 CLI/MCP 자식까지 TERM 후 KILL·회수한다.

데이터 복구는 원본을 별도 백업한 뒤 적용했다. 동일 키·동일 내용인 JSONL 중복
1,002행을 제거했고, 충돌 중복과 손상 행은 0건이었다. 인덱스에서 참조하지 않는
raw 파일 601개와 누수된 `/tmp/blog-summary-*` 4개는 삭제하지 않고 백업 디렉터리로
격리했다. 사후 dry-run은 중복·고아·임시 파일 모두 0건이다.

애플리케이션 변경과 데이터 수리는 완료됐다. 단, root 비밀번호가 없는 세션이라
체크인한 systemd/logrotate 설정을 `/etc`에 설치할 수 없었다. 기존 root 소유
`pm2-ryze_yn.service`는 여전히 `enabled/failed (Result=protocol)`이다. 부팅 시
이중 resurrect를 일으키던 사용자 crontab 항목은 제거했고, 현재 PM2 dump는
정상 4개 항목만 가진다. logrotate는 동일 설정을 사용자 crontab에서 실행하도록
설치해 현재 운영 로그 보호는 확보했다.

## 최초 상태와 원인

### P0 — 리포트·수집 중복 실행

- 백업한 PM2 dump에는 `attn-viewer`, `attn-engine`, `attn-vault-bridge`,
  `attn-ngrok`가 각각 4개씩, 총 16개 등록돼 있었다.
- engine은 4개 PM2 항목 중 3개가 안정적으로 살아 있고 1개가 빠르게 재시작했다.
  각 engine 인스턴스가 자체 scheduler를 띄워 06:30 KST 슬롯에
  `2026-09-03-1`, `-2`, `-3` 리포트가 각각 06:40:17, 06:42:07,
  06:43:06에 생성됐다.
- 직접 원인은 `engine/app/main.py`의 FastAPI lifespan이 API와 scheduler를 함께
  시작한 구조였다. PM2 dump 중복과 systemd/user-crontab의 동시 resurrect가
  인스턴스 수를 늘렸고, 각 인스턴스의 `engine/sector/report_scheduler.py`와
  `engine/sector/scheduler.py`가 독립 실행됐다.
- 단일 worker로 바꾼 뒤에도 정기 수집과 리포트 직전 freshness 수집이 같은 시각에
  겹칠 수 있음을 실서비스에서 추가 발견했다. `engine/sector/scheduler.py`에서
  진행 중 task를 공유하도록 수정해 한 자식만 실행한다.
- 직전 완료 시각이 1시간 이내면 새 수집이 `running`이어도 리포트가 바로 시작하는
  경합도 추가 발견했다. `engine/sector/report_scheduler.py`가 `_run=running`을
  freshness보다 먼저 검사하고 진행 중 task가 끝날 때까지 합류하도록 수정했다.

수정 대상:

- `engine/app/main.py`
- `engine/app/scheduler_worker.py`
- `engine/sector/scheduler.py`
- `engine/sector/report_scheduler.py`
- `engine/sector/collect_pipeline.py`
- `ecosystem.config.cjs`

### P0 — 공유 JSON/JSONL 경합과 데이터 중복

- 세 engine scheduler가 동시에 같은 raw/metrics/status/state 파일을 읽고
  append/replace했다.
- 실제 중복은 raw 630행, `openrouter_daily_tokens` 102행,
  `sdk_downloads` 4행, `token_price` 266행으로 총 1,002행이었다.
- 값이 다른 동일 키 충돌은 0건이므로 중복 제거로 의미 데이터가 소실되지 않았다.
- 프로세스 안의 비동기 제어만으로는 다중 프로세스 쓰기를 막지 못한 것이 원인이다.

수정 대상:

- `engine/runtime_io.py`: `fcntl` 기반 프로세스 간 lock, 임시 파일+fsync+replace
- `engine/sector/store.py`: 카드·지표·raw·state·status 직렬화
- `engine/monitor/alert.py`, `engine/monitor/runner.py`: 알림 transaction과 health 원자 저장
- `scripts/repair_runtime_data.py`: dry-run 기본, 명시적 backup을 요구하는 복구 도구

### P1 — PM2/systemd 기동 소유권과 로그

- root systemd unit와 사용자 crontab이 모두 `pm2 resurrect`를 수행했다.
- 기존 systemd unit은 `Type=forking` 프로토콜 실패 상태였고, 중복 dump를 계속
  복원할 수 있었다.
- PM2 활성 로그는 점검 시 약 786MB였으며 회전 정책이 없었다.
- ngrok는 계정의 동시 endpoint 제한 `ERR_NGROK_18021`로 정지 상태였지만 PM2에
  4개나 남아 있었다.

수정 대상:

- `ecosystem.config.cjs`: core role 각 1개, ngrok는 `ATTN_NGROK_ENABLED=1`일 때만
  추가하고 자동 재시작 금지
- `ops/pm2-ryze_yn.service`: manifest 하나만 startOrReload하는 canonical unit
- `ops/logrotate-attn-viewer`: daily/maxsize 20M/7회/compress/copytruncate
- `README.md`: 설치·전환·rootless fallback 절차

적용 결과:

- 기존 16개 PM2 항목을 모두 중지·삭제한 뒤 manifest로 4개만 시작하고
  `pm2 save --force`를 수행했다.
- 사용자 crontab의 PM2 resurrect 한 줄만 제거했다. 다른 paper 작업은 보존했다.
- 운영 로그 전체를 백업한 뒤 logrotate를 1회 실행했다. 활성 로그는 약 128KB이며
  이전 786MB는 `.1`과 외부 백업에 남아 있다. `delaycompress` 때문에 다음 일일
  실행 때 압축된다.
- root 설치 대신 같은 logrotate 설정을 매일 00:17 UTC 사용자 crontab에서 실행한다.
- ngrok는 외부 제한이 해결될 때까지 명시적으로 비활성화했다.

### P1 — 블로그 불필요 수집과 임시 파일

- `dreamer6847`은 로컬 index가 비어 있고 원격 글이 모두 `crawlSince`보다 오래돼
  저장할 글이 없는데도 30분마다 전체 crawler가 실행됐다. 점검 당시 job 2,022개
  중 2,021개가 실질적 no-op이었다.
- preview 응답에 게시 시각이 없고, empty corpus를 무조건 신규로 판정한 것이
  직접 원인이다.
- 요약 CLI의 `--output-last-message` 파일은 일부 실패·timeout 경로에서 남았다.

수정 대상:

- `lib/blogs.mjs`, `lib/blogs-router.mjs`: preview `publishedAt`와
  `hasNewEligiblePost` 판정
- `openapi.yaml`, `test/contract/openapi-routes.test.mjs`: optional
  `publishedAt` 계약 명시
- `scripts/crawl_naver_blog.mjs`: parse/index 성공 뒤 raw publish
- `lib/summaries.mjs`: 성공·실패·timeout·spawn 오류 모든 경로 임시 파일 정리

현재 블로그 corpus는 점검 중 신규 글 2건이 정상 반영되어 index 8,524행이다.
본문·메타 누락 0건, JSON 요약 1,912개 파싱 오류 0건, 요약 대상 대기 0건이다.
`dreamer6847`은 preview 단계에서 대상 글이 없으면 crawler를 실행하지 않는다.

### P1 — 상태가 실제 실패·실행 시간을 숨김

- DART/EDGAR collector는 내부 source 요청이 모두 실패해도 빈 결과를 `ok`로
  반환할 수 있었다.
- API와 scheduler가 같은 프로세스라 scheduler가 막히면 `/healthz`도 3초 안에
  응답하지 못했다.
- 수집 `_run.state=completed`가 후속 thesis 갱신 전에 기록되어 실제 자식이
  실행 중인데도 완료로 보였다.
- scheduler 전용 프로세스에 기본 logging 설정이 없어 lifecycle과 timeout이
  PM2 로그에 남지 않았고, 설정 후에는 `httpx` INFO가 과도하게 출력됐다.

수정 대상:

- `engine/sector/collectors/dart_edgar.py`: 시도·실패 source를 집계해
  `ok/degraded/error` 결정
- `engine/monitor/checks.py`, `engine/monitor/runner.py`,
  `engine/monitor/scheduler.py`: 제한 시간 있는 engine health 점검
- `engine/sector/runner.py`: 시작 시 `running`, thesis까지 끝난 뒤 `completed` 기록
- `engine/app/scheduler_worker.py`, `engine/sector/collect_pipeline.py`: lifecycle INFO를
  켜고 `httpx/httpcore`는 WARNING으로 제한

최신 실수집은 collector 20개 중 `ok=18`, `degraded=1`, `missing_key=1`이다.
DART/EDGAR 6개 source는 모두 성공했다. 경고는 PyPI API의 HTTP 429와 미설정
ECOS API key이며, engine `/healthz`는 `200`, `ok=true`로 확인됐다.

### P1 — 리포트 생성 중 최종 JSON 경로 오염

- `alloc_report_slot`이 동시 실행 ID를 예약하면서 최종 `reports/<id>.json`에
  비-JSON 토큰을 먼저 기록했다. 정상 완료 시 JSON으로 교체되지만 생성 중에는
  parser가 실패하고, 비정상 종료 시 토큰 파일이 영구 잔류할 수 있었다.
- `engine/sector/report_pipeline.py`가 최종 경로와 분리된 `<id>.reserve`를
  `O_EXCL`로 생성하도록 바꿨다. 최종 `*.json`은 완성된 report를 원자 발행할 때만
  나타나며 성공 후 reservation을 소비한다.

### P2 — P23 off-arm golden 실패

- `tests/test_p23_off_identity.py`의 golden이 현재 공통 harness 출력 구조보다
  오래되어 구조 등치가 실패했다.
- off-arm 동작을 바꾸지 않고, clean worktree·고정 clock·canned role로 현재 기준을
  다시 캡처했다.

수정 대상:

- `engine/tests/p23_harness.py`
- `engine/tests/test_p23_off_identity.py`
- `engine/tests/fixtures/p23_off_golden.json`

## 데이터 수리와 복구 위치

전체 운영 백업:

```text
/home/ryze_yn/attn-viewer-ops-backups/20260903T085908Z
```

데이터 수리 백업:

```text
/home/ryze_yn/attn-viewer-ops-backups/20260903T085908Z/data-repair
```

- `original/`: 수정 전 JSONL 원본 4개
- `quarantine/`: raw 고아 601개와 summary temp 4개
- `repair-report.json`: 적용 결과
- `operational/`: PM2 dump/list, 전체 PM2 로그, systemd unit, crontab, session 사본

백업 총 크기는 약 856MB다. 격리 파일과 회전 로그는 삭제하지 않았다.

## 검증 결과

- `npm test`
  - syntax 및 OpenAPI validation 통과
  - Node: 91/91 통과
  - E2E: 11/11 통과(모바일·데스크톱 포함)
  - Python: 867 통과, 13 deselected, 실패 0
  - 잔여 경고: FastAPI TestClient의 Starlette `httpx2` 전환 deprecation 1건
- 런타임 JSON 21,333개와 JSONL 101개/55,924행 전수 parse 오류 0
- report ID 예약 중에도 최종 `*.json` 경로에는 비-JSON sentinel이 나타나지 않는
  회귀 테스트 통과
- 복구 도구 사후 dry-run: duplicate 0, conflict 0, orphan raw 0, summary temp 0
- PM2 live/dump: core role 각 1개, 모두 online
- 두 번째 scheduler worker 기동 시 singleton lock을 감지하고 exit 0
- 18:30 KST 실제 예약 실행이 `진행 중 수집에 합류`와
  `joining the in-flight collection`을 기록했고, worker 직속 collector 자식은
  계속 1개였다.
- collector PID/PGID/SID가 동일한 독립 process group임을 확인했다.
- 포트: `127.0.0.1:3000`, `:8801`, `:8792` 각각 listener 1개
- API smoke:
  - engine `/healthz` 200
  - viewer/bridge `/api/session` 기존 401 `로그인이 필요합니다.` 응답 유지
  - `/api/market-reports` 200, 104개 조회
- 최신 report detail 200
- 18:30 KST 실제 리포트는 수집 합류 후 09:35:45 UTC에 시작해 10:15:33 UTC에
  첫 시도로 완료됐다. `2026-09-03-4` 단 1개가 추가되어 총 104개이며,
  `publish_status=ok`, macro/memory/other 3축, list/detail API 200을 확인했다.

## 남은 항목과 우선순위

### P1 — root 권한으로 canonical 설정 설치

현재 세션의 `sudo -n`은 비밀번호를 요구해 아래 파일을 `/etc`에 반영하지 못했다.
애플리케이션은 정상 운영 중이지만, 다음 재부팅 전에 관리자가 한 번 적용해야
systemd 상태까지 완전히 정상화된다.

```bash
sudo install -o root -g root -m 0644 \
  /home/ryze_yn/attn-viewer/ops/pm2-ryze_yn.service \
  /etc/systemd/system/pm2-ryze_yn.service
sudo install -o root -g root -m 0644 \
  /home/ryze_yn/attn-viewer/ops/logrotate-attn-viewer \
  /etc/logrotate.d/attn-viewer
sudo systemctl daemon-reload
pm2 save --force
pm2 kill
sudo systemctl reset-failed pm2-ryze_yn.service
sudo systemctl enable --now pm2-ryze_yn.service
sudo logrotate --debug /etc/logrotate.d/attn-viewer
```

설치 후 사용자 crontab의 00:17 logrotate fallback은 제거해 회전 소유자도 하나로
만든다. 위 전환은 짧은 서비스 중단을 수반하므로 root 권한을 가진 관리 창에서
수행한다.

### P2 — 외부 의존성

- ngrok: 계정의 동시 endpoint를 정리한 뒤 `ATTN_NGROK_ENABLED=1`로 명시 활성화한다.
- ECOS: 해당 지표가 필요하면 `ECOS_API_KEY`를 설정한다.
- PyPI stats: HTTP 429는 공급자 rate limit이다. 지속되면 backoff/cache를 추가한다.

### P3 — 유지보수

- npm audit의 moderate 1건은 별도 dependency update로 처리한다.
- Starlette TestClient deprecation은 FastAPI/Starlette 지원 범위를 확인한 뒤
  `httpx2`로 전환한다.
