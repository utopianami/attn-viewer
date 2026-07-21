# SaveTicker firehose → raw 뉴스 코퍼스 (설계 v9)

- 날짜: 2026-07-21
- 대상 코드: `engine/sector/collectors/saveticker.py`, `engine/sector/store.py`, `engine/sector/contracts.py`
- 관련 메모: [[saveticker-news-sunset]]
- 리뷰 이력: codex r1~r9. r3 scan_hwm·pending 분리 / r4 무포기·cutover_floor / r5 seen·무손실=(cutover_floor, scan_hwm]·forward 예산 / r6 pending 시간예약·canary probe / r7 실제 HTTP 요청수 예약 / r8 worst-case 여유·CYCLE_CAP 하드 상한 / **r9 판정: blocker 없음, 구현 착수 가능**.
- 잔여 nit(무해): canary 요청(≤CANARY_SAMPLE)만큼 forward 예약이 엄밀히는 400 미만(~394)일 수 있음 — 진행성 영향 없음.

## 1. 배경

SaveTicker 구 뉴스 API(`/api/news/list`)가 **2026-07-07 종료**됨(sunset 공지 1건만).
saveticker 뉴스 수집이 **하루 0건**이 됐으나 캘린더가 살아있어 status는 "ok" → **2주간 미탐지**(관측성 구멍).

무인증 실측(2026-07-21) 새 접근면:

| 엔드포인트 | 상태 | 용도 |
|---|---|---|
| `GET /api/news/top-stories` | ✅ 무인증 | 큐레이션 상위 ~19건, 페이지네이션 없음. **anchor·canary 원천** |
| `GET /api/news/detail/{id}` (경로형) | ✅ 무인증 | 전문(쿼리형 `?id=`는 404). content=블록 리스트 |
| `GET /api/calendar/events` | ✅ 무인증 | 매크로 캘린더(기존 유지) |
| `GET /api/news/list` (구) | ❌ 종료 | 재작성 후 **호출 안 함** |
| SSE 라이브 피드 | 🔒 로그인(401) | 배치 부적합 |

전체 목록 엔드포인트가 없으므로 **id 순차 증가 + 무인증 detail**로 firehose 복원(id-walk).
실측 firehose ≈ **하루 ~500건 / 12h당 ~250건**, 삭제 id 산발 ~7%.

## 2. 목표와 비목표

**목표**
- firehose 전량을 **필터 없이 raw 코퍼스에 저장**(신규). `(cutover_floor, scan_hwm]` **무손실**, 그 위는 backlog/best-effort(§3).
- 죽은 **카드 경로를 새 소스로 갈아끼워 부활**하되 후보 규모·최신순·비용 근접 보존.
- **산출 기반 상태 신호**로 "0건인데 초록불" 재발 방지.

**비목표**
- judge 80상한 해제 / 카드 수 증대.
- raw 하류 소비("새로운 것") — 저장만. 조회 API 이번 범위 제외(YAGNI).
- 과거 공백 백필 — forward-only(cutover_floor 이하 안 봄).
- SSE / 로그인.

## 3. 상태 모델 (핵심)

**전제**: SaveTicker id는 삽입 시 단조 증가. 따라서 (a) valid id H 관측 시 H 미만 404는 영구부재, (b) `id ≤ observed_anchor`는 모두 발급됨.

"완료 경계"와 "스캔 재개점"을 분리(r3), 그리고 미해결 구멍을 **포기하지 않는다**(r4 — 포기와 무손실은 양립 불가). `state.json` 영속:

| 키 | 의미 | 불변식 |
|---|---|---|
| `saveticker_scan_hwm` | **스캔 재개점**. 다음 사이클 `scan_hwm+1`부터 | 단조 전진. trailing 404(frontier zone) 안 넘음 |
| `saveticker_observed_anchor` | `max(이전, top-stories now, 이번 최대 valid)` | 이 id 이하 발급 보장 → 무손실 상한 |
| `saveticker_cutover_floor` | 첫 시딩 hwm(고정) | 무손실 하한. 이 id 이하는 forward-only로 미수집 |
| `saveticker_pending` | 미해결 구멍 map `{id: {kind, attempts}}` | 유계(≤PENDING_MAX). **무기한 재시도**, 포기 없음 |
| `saveticker_retry_pos` | pending 재시도 round-robin 위치 | budget 소진 시 다음 사이클 이어감 |

**무손실 계약(정직, r5)**: `id ∈ (cutover_floor, scan_hwm]`인 모든 id는 항상 **valid(수집)·삭제/404(확정 부재)·pending(무기한 재시도 중)** 중 하나 → 조용한 유실 없음. `(scan_hwm, observed_anchor]`는 **backlog**(발급 확정이나 아직 미스캔 — budget 절단으로 남은 구간; scan_hwm이 넘어가지 않았으므로 다음 사이클 반드시 스캔, 유실 아님). `id > observed_anchor`(frontier)는 best-effort, anchor 상승 시 편입. pending은 상류 회복 시 결국 수집; `len(pending) ≥ PENDING_MAX`면 `error` backpressure로 **가시화**.

## 4. 컴포넌트

### 4.1 `saveticker.py` — id-walk (재작성)

상수:
```
MISS_STOP          = 40    # observed_anchor 위 frontier 정지(연속 404) — best-effort
CYCLE_CAP          = 800   # budget: 사이클당 최대 detail 조회(pending 재시도 포함)
MAX_ELAPSED_S      = 300   # budget: 사이클 wall-clock(pending 재시도 포함)
DETAIL_TIMEOUT_S   = 8
REQUEST_INTERVAL_S = 0.15  # 요청 간 최소 간격
RETRY_TRANSIENT    = 1     # transient 1회 backoff(0.5s+jitter)
PENDING_MAX        = 300   # 추가 시점 초과 = 상류 붕괴 → 커밋 후 error(backpressure)
PENDING_BUDGET     = 400   # pending 재시도 최대 조회수(나머지 ≥400은 forward-scan 예약, r5)
PENDING_ELAPSED_S  = 120   # pending 재시도 최대 시간(나머지 ≥180s는 forward-scan 시간 예약, r6)
CANARY_SAMPLE      = 3     # 매 사이클 재검증 known id 표본
CARD_CANDIDATE_CAP = 40    # judge 후보 상한
```

**`_classify_detail(client, rid) -> kind, news|None`** (정확히 한 분류):
- `valid`: 200 + `news` 필수필드(id·title·created_at) + content 파싱 가능
- `deleted`: 200 + `is_deleted=true`
- `not_found`: 404
- `transient`: timeout/429/5xx/연결오류/JSON 파싱실패 (RETRY_TRANSIENT 후에도)
- `invalid`: 200이나 `news` 없음/필수필드 결손/content 스키마 불명

**`_newest(client) -> (max_id|None, known_ids)`**: top-stories → 스키마 검증 → max_id·canary용 known_ids. 붕괴/빈 값이면 (None, []).

**의사코드**:
```
persistent: scan_hwm, observed_anchor, cutover_floor, pending{id:{kind,attempts}}, retry_pos

def collect(store):
    budget = Budget(CYCLE_CAP, MAX_ELAPSED_S, REQUEST_INTERVAL_S)     # 모든 detail 호출 공유(r5: canary 포함)
    seen = set()                                                     # 이번 사이클 스캔한 id — 재조회 방지(r5)
    def classify(rid): seen.add(rid); return _classify_detail(rid)   # 스캔용(budget 차감 + seen 오염)
    def probe(rid):    return _classify_detail(rid)                  # canary용(budget만, seen 미오염 — r6)

    anchor_now, known = _newest()
    if anchor_now is None: return error("top-stories drift")          # 캘린더는 별도 수집
    ck = [probe(k)[0] for k in sample(known, CANARY_SAMPLE)]          # kind만 추출(r6)
    if ck and all(k in {not_found, invalid} for k in ck):
        return error("detail canary fail")                            # transient뿐이면 아래서 degraded
    anchor = max(state.observed_anchor or 0, anchor_now)

    if state.scan_hwm is None:                                        # 시딩
        hwm = _frontier_probe(anchor, budget)                        # anchor+1.. MISS_STOP, 마지막 valid(없으면 anchor)
        commit(scan_hwm=hwm, observed_anchor=max(anchor,hwm),
               cutover_floor=hwm, pending={}, retry_pos=0)
        return degraded(f"seeded={hwm}", raw=0, items=0)

    docs = []; pending = dict(state.pending)

    # (1) pending 무기한 재시도 — 실제 요청수·시간 둘 다 예약(forward-scan 기아 방지, r5·r6·r7·r8)
    start_req = budget.requests()                                    # Budget은 실제 HTTP 요청(transient 재시도 포함) 카운트
    MAX_REQ_PER_ITEM = 1 + RETRY_TRANSIENT                           # 한 id의 최악 요청수
    for pid in rotate(sorted(pending), state.retry_pos):
        # 다음 id가 최악(재시도 포함)까지 써도 PENDING_BUDGET 초과 안 하도록 사전 여유 확보(r8)
        if (not budget.ok()
                or budget.requests() - start_req + MAX_REQ_PER_ITEM > PENDING_BUDGET
                or budget.elapsed() >= PENDING_ELAPSED_S): break
        k, news = classify(pid)
        if k == valid: docs.append(news); pending.pop(pid)
        elif k in (deleted, not_found): pending.pop(pid)            # 확정 부재
        else: pending[pid].attempts += 1                            # 보관(포기 없음)
    retry_pos = next_pos(pending, state.retry_pos)

    # (2) region A: scan_hwm+1 .. anchor  (발급 확정). pending·seen id는 건너뜀(중복 방지, r5).
    id = state.scan_hwm + 1
    while id <= anchor and budget.ok():
        if id in pending or id in seen: id += 1; continue
        k, news = classify(id)
        if k == valid: docs.append(news)
        elif k in (deleted, not_found): pass
        else:
            if len(pending) >= PENDING_MAX: return _overflow(pending, docs, scan_hwm=id-1)
            pending[id] = {kind:k, attempts:1}                      # 추가 시점 상한 검사
        id += 1
    scan_hwm = min(id-1, anchor)                                    # budget 절단 시 스캔한 만큼만(나머지=backlog)

    # (3) region B: anchor+1 .. frontier  (best-effort). pending·seen id는 건너뜀.
    miss = 0; max_valid = scan_hwm
    while budget.ok() and miss < MISS_STOP:
        if id in pending or id in seen: id += 1; continue
        k, news = classify(id)
        if k == valid: docs.append(news); max_valid = id; anchor = id; miss = 0
        elif k == not_found: miss += 1                              # trailing zone — 커밋 안 함
        elif k == deleted: miss = 0
        else:
            if len(pending) >= PENDING_MAX: return _overflow(pending, docs, scan_hwm=max(scan_hwm,max_valid))
            pending[id] = {kind:k, attempts:1}; miss = 0
        id += 1
    scan_hwm = max(scan_hwm, max_valid)                             # trailing 404 절대 안 넘김

    # (4) 커밋: raw 먼저(fsync) → 상태 원자 저장(temp+fsync+os.replace)
    store.append_raw_news(docs)
    commit(scan_hwm, observed_anchor=max(anchor, max_valid),
           cutover_floor=state.cutover_floor, pending=pending, retry_pos=retry_pos)
    cand = sort_by_id_desc([d for d in docs if _relevant(d)])[:CARD_CANDIDATE_CAP]
    return result(items=to_raw_news_items(cand), status=_liveness(...), stats=...)
```
- `Budget`은 **실제 HTTP 요청(transient 재시도 포함)**을 센다. `budget.ok()` = `requests < CYCLE_CAP and elapsed < MAX_ELAPSED_S`, `budget.requests()`=누적 요청수. **CYCLE_CAP은 각 실제 HTTP 호출(재시도 호출 포함) 직전에 검사되는 하드 상한** → 절대 초과 없음. `stop_reason ∈ {budget, frontier}`.
- `_overflow(...)`: pending을 커밋(scan_hwm은 안전 지점까지만) 후 `status=error, detail="pending overflow"`.
- **캘린더**: 기존 로직. 200 아니면 별도 카운터.

### 4.2 카드 경로 보존 계약
- `_relevant` 입력 = **`title + content[:200]`**(전문 앞 200자). 전량 투입 시 후보·비용 달라지므로 한정.
- `RawNewsItem`: 기존 필드(id=`st-<rid>`, preview=content[:200], `(카더라)`→D), **id 내림차순** 후 CAP 절단.
- **후보 규모(정밀)**: runner registry에서 **saveticker 최우선**([runner.py](engine/sector/runner.py))이라 판정 풀 선두 → judge 등급 안정정렬 후 앞 80에서 saveticker가 최대 40칸 선점, 나머지 타 소스. saveticker 생존기 footprint와 동일 계열. 계약은 **"타 소스 starvation 없음"**(동일성 아님), 회귀 테스트로 검증. judge/runner 무변경.

### 4.3 `contracts.py`
```python
class RawNewsDoc(BaseModel):
    id: str
    title: str                    # 필수 — 결손 시 _classify가 invalid로 차단
    created_at: str               # 필수
    content: str = ""
    source: str = ""
    url: str = ""
    tag_names: list[str] = Field(default_factory=list)
    collected_at: str = ""        # store 스탬프
```
`CollectorResult`에 `stats: dict[str, Any] = Field(default_factory=dict)` 추가.

### 4.4 `store.py`
- **raw 코퍼스**: `news_raw/YYYY-MM.jsonl`(파티션=`created_at[:7]`, 파싱불가→`unknown`).
  `append_raw_news(docs)`:
  - **dedup은 doc별 대상 파티션**(r3): 각 doc의 `created_at[:7]` 파일에서 id 확인 후 신규만 append. 배치가 건드리는 월만 로드(1~2개). in-batch dedup 병행.
  - `collected_at` 스탬프. 파일 `with`(flush) + **fsync**. 반환=추가 수.
- **원자 상태 저장**: state를 **임시파일 → fsync → `os.replace`**. 기존 `set_state`도 이 경로로 통일.
- **write_status 확장**: `CollectorResult.stats`를 status 항목에 구조화 저장.
- 카드 index.jsonl 불변.

### 4.5 `runner.py` — 무변경
items→judge, observations→append, write_status 그대로. raw 직접저장은 기존 패턴(saveticker가 이미 state를 store에 직접 씀)과 동일, stats로 status 노출.

## 5. 관측성 (산출 기반)
- 시딩: `degraded`.
- **canary**: 표본 전부 404/invalid → `error`. 표본 transient → `degraded`. 하나라도 valid → 통과.
- **anchor 전진인데 valid 0**: `error`.
- invalid 비율 임계 초과(region A 표본): `error`(drift).
- transient>0 또는 pending 존재: `degraded`. `len(pending) ≥ PENDING_MAX`: `error`(backpressure).
- stats: 분류 카운트·`scan_hwm`·`observed_anchor`·`cutover_floor`·`anchor_minus_scan_hwm`(backlog)·`scanned`·`stop_reason`·`pending_len`·`pending_max_attempts`·canary. (불확실한 예측 해소치는 안 냄.)
- 캘린더 실패는 뉴스와 **별도 카운터**.

## 6. 안전·부하
- 순차 + `REQUEST_INTERVAL_S`. transient 1회 backoff(jitter). **모든 detail(pending 재시도 포함)이 단일 budget 공유**(CYCLE_CAP·MAX_ELAPSED_S).
- `stop_reason`: `budget` / `frontier`. 구멍은 종료가 아니라 pending 격리.
- 스케줄러 12h 순차(await 후 sleep) + MAX_ELAPSED_S(300s)≪12h → 중복 실행 없음.
- 내구성: raw fsync 후 state fsync+os.replace. raw 미기록 상태로 커서 전진 불가.

## 7. 테스트 (TDD, 실제 상류 출력 2층)
픽스처: 실제 top-stories JSON + detail JSON(valid/deleted/not_found/invalid/transient).

무손실·커서(r1~r4 반례를 그대로 테스트):
- **영구 구멍 non-blocking·무손실**(r4): `scan_hwm=100,anchor=103`, `101=transient` 지속, `102~103=valid` → 101은 pending에 **영구 보관·매 사이클 재시도**, scan_hwm=103, 102·103 수집. 101 정상화되면 그때 수집(포기 없음).
- **trailing-404 off-by-one**: 101=valid,102..141=404(anchor=100) → scan_hwm=101. 다음 사이클 anchor 상승 시 region A 편입.
- **region B 중복 방지**(r4): pending에 든 id는 region A/B에서 건너뜀 → 중복 append 없음.
- **PENDING_MAX add-time**(r4): `101~401=invalid` → 추가 도중 300 도달 시 즉시 커밋+error(초과 커밋 없음).
- **budget 공유**(r4): pending 대량 재시도가 CYCLE_CAP·MAX_ELAPSED_S에 포함(canary도), retry_pos로 다음 사이클 이어감.
- **pending-resolve 중복 없음**(r5): 재시도로 valid된 id를 region A/B가 재조회 안 함(`seen`).
- **forward-scan 기아 방지**(r5): pending이 PENDING_BUDGET(400)까지만 써서 region A가 최소 진행 보장.
- **budget 절단 backlog**(r5): region A가 budget으로 잘리면 scan_hwm은 스캔분까지만, `(scan_hwm, anchor]`는 backlog로 다음 사이클 스캔(유실 아님).
- **canary budget 편입**(r5): canary 호출도 budget에서 차감.
- **pending 시간 예약**(r6): pending 재시도가 PENDING_ELAPSED_S(120s) 넘으면 중단 → forward에 ≥180s 보장.
- **canary valid id 미유실**(r6): canary는 `seen` 미오염(probe) → 그 id가 forward 범위면 region A가 정상 수집.
- **canary kind 비교**(r6): `probe()[0]`로 kind 추출해 판정.
- **cutover_floor**(r4): 시딩 hwm=105 → 무손실은 `(105, anchor]`, 1~105는 forward-only 미수집(모순 아님).
- **canary**: 전부 404/invalid=error, transient=degraded, 하나 valid=통과.
- off-by-one: MISS 39/40/41, CYCLE_CAP 799/800/801.

산출·계약:
- raw 전량: region A·B valid 전부 append(키워드 불문).
- 카드 경로: `_relevant`(title+content[:200]) 통과분만 items, id 내림차순, CAP 절단.
- **starvation 회귀**: saveticker 40건 + 타 소스 동시 → 타 소스 판정 풀 소멸 없음.
- dedup: doc별 대상 파티션, 월 경계·재수집 → 추가 0.
- schema drift: 200+news없음/content 문자열·null·미지 block → invalid → error 유발.
- **원자·내구성**: state 저장 중 크래시 모사 시 부분기록 없음(temp+fsync+os.replace). raw append 실패 시 scan_hwm 미전진.

관측성: 시딩=degraded, canary 전부실패=error, anchor 전진+valid 0=error, invalid 다수=error, transient/pending>0=degraded, pending overflow=error, 캘린더 비200=별도 카운터.

## 8. 롤아웃 / 후속(범위 밖)
- 배포 첫 사이클=시딩(degraded) → 이후 raw 적재 + 카드 부활.
- **후속(별도 태스크)**: workflow-review.html 현행화([[update-workflow-review-after-ship]]) — 본 구현의 완료 조건에서 분리.
