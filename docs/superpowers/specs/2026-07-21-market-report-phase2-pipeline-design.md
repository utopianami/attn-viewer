# 시황 리포트 Phase 2 — 파이프라인 설계 (Filters → 심화 → 합성 → 검증) · v3

> 설계 스냅샷 2026-07-22 · 상위 설계: `public/html/market-report-design.html` §1–8 · 입력: Phase 1 `engine/sector/report_input.py` · 출력 스키마: `storage/rag/memory_sector/reports/2026-07-21-1.json`(샘플) · **v2: codex r1(BLOCKER 8·SF 6) 반영 · v3: codex r2(신규 BLOCKER 5·PARTIAL 5·SF1) 반영 — CLI 실측 결과 포함**

**Goal:** Phase 1이 조립한 `ReportInput`을 받아 3단계 필터 → 심화(규칙 인출) → 주장 합성 → adversarial 검증 → **검증 통과분으로 결론 조립**을 거쳐, 기존 뷰어가 렌더하는 **리포트 JSON**을 결정적으로 생성·영속화한다.

**결정 확정(사용자, 2026-07-21):** 스코프=전체(검증 포함) · 실행=API+CLI 하이브리드("빠를 필요 없음", 필터=API, 심화·합성=CLI) · 모듈=`engine/sector/` · **자율 진행(승인 게이트 없이 codex 리뷰 루프)** · 과거사례 지식층은 사용자가 별도 구축 중 → **seam 유지**.

---

## Global Constraints (설계 §1 불변식 + codex r1)

- **never-raise + 진단**: 모든 스테이지는 예외를 던지지 않고 `StageResult`(성공/열화 + 사유 + StageIO)를 반환. `_safe` 래퍼는 절대 `None`을 반환하지 않고 **downstream-safe 빈 결과**를 반환. 리포트는 어떤 단계가 비어도 `diagnostics`와 함께 항상 발행.
- **숫자는 코드가**: LLM 산술 금지. metric delta·가격반응·수익률·**finalOpinion.confidence 집계**는 코드가 결정적으로 계산. 검증은 LLM 주장 수치를 코드 anchor와 **anchor 정체성(metric+entity+period) 기준**으로 대조(전역 ±5% 매칭 금지).
- **결정성(정의, codex NIT)**: byte-identical이 목표가 아님. **코드 파생 계산·cutoff·정렬·ID가 안정**적이고, **캡처된 role 출력이 주어지면 replay가 동일**함을 의미. `elapsed_ms`·run-log 등 타이밍 필드는 골든 동등성에서 제외/정규화.
- **cutoff 일원화(codex BLOCKER6)**: 파이프라인 진입 시 `effective_now`(UTC aware)를 **한 번** 계산해 모든 스테이지·검증·anchor·ID에 전파. Phase 1/metric/anchor는 `ts ≤ effective_now` **및** `ingested_at ≤ effective_now`만 사용(look-ahead 차단).
- **대원칙**: 모든 주장은 수치에 근거하고 여러 사실을 규칙으로 연결. 단일 사실 나열·수치 없는 주장 금지. **playbook은 절차적 맥락이지 사실 근거가 아님**(인용 금지 — 기존 포맷터 규칙 준수).
- **관측성**: 매 스테이지 StageIO(in/out/dropped+사유/elapsed)를 `pipeline.stages`에 기록. **뷰어 렌더 안전을 위해 stage.items는 문자열**(title/text)만; 풍부한 StageIO는 additive 필드로 저장(Phase 3에서 렌더).
- **보안(codex SF1)**: CLI 실행기는 신뢰불가 뉴스를 처리하므로 **툴 전면 비활성화·고정 cwd·세션 미영속·프로세스그룹 타임아웃 킬**.

---

## Architecture

| 파일 | 역할 |
|---|---|
| `engine/cli_role.py` (신규) | `cli_complete(...)` — claude/codex CLI 구조화 출력 실행기(툴 없이) |
| `engine/providers.py` (수정) | `Role.run`에 `provider=="cli"` 분기 + `_capable("cli")` |
| `engine/sector/report_contracts.py` (신규) | `EvidenceRef`·`EventCluster`·`Anchor`·`ReportClaim`·`FinalOpinion`·`PipelineStage`·`StageIO`·`StageResult`·`Report` |
| `engine/sector/report_filters.py` (신규) | f1/f2/f3 (async, 자체 never-raise 배치) |
| `engine/sector/report_rules.py` (신규) | `rank_playbooks` 결정적 랭커 + `derive_topics` |
| `engine/sector/report_synthesis.py` (신규) | 심화(규칙 대조) + 합성(claims만) |
| `engine/sector/report_verify.py` (신규) | A1/A2 + 숫자·시점 대조 → claim status |
| `engine/sector/report_assemble.py` (신규) | 검증 통과분으로 overview/finalOpinion 조립(코드가 confidence 집계) |
| `engine/sector/report_anchors.py` (신규) | `build_anchors(store, now)` — 코드가 typed 수치 anchor 생성 |
| `engine/sector/report_pipeline.py` (신규) | 오케스트레이션 + CLI 엔트리포인트 + 영속화 |
| `engine/sector/report_input.py` (Phase 1, **소폭 수정**) | cutoff·ingested_at 필터 + typed 관측 노출 |

**데이터 흐름(순서 변경 — 검증이 결론 앞):**
```
effective_now = _to_utc(now)               # 진입 시 1회
ReportInput = assemble_report_input(store, now=effective_now, window_hours)
anchors     = build_anchors(store, now=effective_now)         # 코드, typed
f1 관련성(API)  → f2 중요도(API) → f3 이벤트클러스터 dedup(API)   # 각 StageResult
rules  = rank_playbooks(derive_topics(clusters,metrics), corpus, allowed_types)   # 코드
deep   = await deepen(clusters, rules, anchors)      # CLI, 규칙 대조 논증
claims = await synthesize_claims(deep, clusters, anchors)      # CLI, claims만(결론 X)
verdicts = await verify_claims(claims, anchors, evidence, cutoff=effective_now)   # A1/A2/숫자/시점
report = assemble_report(clusters, claims, verdicts, anchors, stages, now=effective_now)
         # ← overview/finalOpinion는 검증 통과 claim만으로 조립, confidence 코드 집계
save_report(report)                         # CLI 엔트리포인트 소유
```

---

## Component 1 — CliRole (`engine/cli_role.py` + `providers.py` 분기)

**통합(codex r1-B1 + r2-P1 해소):** ROLE_MAP fallback 의미(=raise 시 다음)를 지키기 위해 별도 client 대신 **`Role.run` 루프의 try 블록 안, `run_prompt`/`cache_prefix` 처리 뒤**에 분기를 둔다(run_prompt 초기화 전 참조 금지 — codex r2).
```python
# providers.py
def _capable(provider):
    if provider == "cli":
        return shutil.which("claude") is not None or shutil.which("codex") is not None
    return settings.capabilities().get(provider, False)

# Role.run 루프 내부 try:, run_prompt 조립(cache_prefix 접두 포함) 직후 · _make_client 앞:
                if provider == "cli":
                    if cache_prefix:
                        run_prompt = f"{cache_prefix}\n\n{prompt}"   # CLI엔 캐시 없음 — 접두로
                    return await cli_complete(model, instr, run_prompt,
                                              response_format=response_format, effort=effort or e)
    # 성공: structured면 검증된 인스턴스, 아니면 str. 실패 시 cli_complete가 raise → except → 다음 체인.
```
ROLE_MAP 예: `"report_deepen": [("cli","claude","high"), ("anthropic", model_claude, "high")]` — CLI 실패 시 **API opus로 자동 폴백**.

**`cli_complete(model, instructions, prompt, *, response_format, effort) -> Any` (codex r2 CLI 실측 반영):**
- claude: `claude -p --model <m> --output-format json --json-schema '<인라인 JSON 문자열>' --tools "" --no-session-persistence [--effort <e>]`, 프롬프트는 **stdin**.
  - `--json-schema`는 **파일 경로가 아니라 인라인 JSON**(파일 경로는 "not valid JSON"으로 즉사 — codex r2 실측).
  - 툴 비활성은 **`--tools ""`** (`--allowedTools ""`는 Bash를 막지 못함 — codex r2 스모크 실측).
- 출력 파싱: stdout은 JSON envelope. **`structured_output` 필드**(canonical)를 우선 취하고, 없으면 `result` 문자열을 파싱. `is_error==true`면 raise. 이후 `response_format.model_validate(...)` 검증.
- codex 대체: `codex exec --output-schema <f> --output-last-message <f>` (참고: `-s read-only`도 tool-free가 아님 — 격리 요건 동일 적용).
- 실패(비정상 종료·타임아웃·JSON 파싱·검증 실패): **raise**(폴백 유발). 파싱만 실패 시 1회 재시도 후 raise.
- run-log: elapsed_ms·모델·프롬프트 해시·exit·성패 기록(CostMeter 대체 계측). stderr 분리, stdout 크기 캡.
- 서브프로세스는 `_run_cli(argv, stdin_text, timeout) -> (rc, out, err)`로 추상화 → 테스트 stub. 프로세스그룹 킬(타임아웃).

---

## Component 2 — 필터 f1/f2/f3 (`report_filters.py`)

judge 배치 **패턴만** 참고하되(codex SF2: judge는 raise·80캡·grade_hint라 **그대로 상속 금지**), 자체 규율:
- **async**, 각 `-> StageResult`(output=kept 리스트, io=StageIO, error).
- **전량 처리**: firehose 전량을 40/배치로 **여러 배치** 처리(80 캡 없음). 배치 실패는 **fail-closed**(그 배치 항목 drop, 사유 기록) — 무성 통과 금지.
- 행 재조정: 누락 idx→해당 항목 보수적 drop+사유 / 중복 idx→첫 것 / 범위밖 enum→clamp. **원본 인덱스 안정 정렬**.
- `RawNewsDoc`엔 grade_hint 없음 → 우선순위는 `source`·recency로(전량 처리라 절단 없음, 배치 순서용).

| 필터 | 입력→출력 | LLM row |
|---|---|---|
| **f1 관련성** | raw_news 전량 → 메모리 밸류체인 관련만. cards는 판정본이라 통과 | `{idx, relevant, reason}` |
| **f2 중요도** | f1-kept + cards → 12h 임팩트 상위 | `{idx, impact:상|중|하, keep, reason}` |
| **f3 이벤트클러스터** | 중복 이벤트 dedup → `EventCluster[]` (원본 EvidenceRef 보존) | `{cluster_id, member_idxs, title, axis, direction}` |

**핵심(codex BLOCKER3): 클러스터는 원본 레코드를 버리지 않는다** — `EventCluster.members: list[EvidenceRef]`로 id/title/ts/excerpt/source 보존(검증·근거·시점에 필요).

---

## Component 3 — 규칙 랭커 (`report_rules.py`)

codex BLOCKER7 해소: `match_playbook`(단일반환·private 스코어링·question_type 의존) 재사용 불가 → 스코어링을 **결정적 랭커로 추출**.
```python
def rank_playbooks(signals: list[str], playbooks: list[dict], *,
                   allowed_conclusion_types: set[str], top_k: int = 5) -> list[RankedRule]:
    # 기존 match_playbook의 점수·matchKey·margin 로직을 공유 함수로 리팩터.
    # RankedRule = {slug, situation, connection, score, matched_keys, eligible, margin, conclusionType}
    # matchKey ≥1 필수(topic-only 배제) 유지. slug dedup. holdout_passed만.
```
- 리포트 allowed conclusion types = 4종 전부(`방향 판단/종목 비교/시점 판단/리스크 점검`).
- `derive_topics(cluster, metrics)` — SectorCard엔 `topics` 필드 없음 → `entities + axis + event_type + metric label`에서 신호 문자열 유도.
- **precedent은 SEAM(과거사례 별도 구축 중)**: RankedRule의 `situation`/`connection`을 "규칙 근거"로만 사용. 구체적 과거 에피소드는 case-memory 층 완료 후 연결. 그 전엔 `precedent`에 규칙 근거 + `precedent_grounded=false` 표기(날조 금지).

---

## Component 4 — 심화 + 합성 (`report_synthesis.py`, CLI)

- `deepen(clusters, rules, anchors, *, role) -> StageResult` (output=논증 텍스트): CLI claude로 관측+규칙 대조 논증(설계 §4: 나이브 기각 → if/then 비추기 → 비직관 결론). 산술 금지(anchor 값 인용만).
- `synthesize_claims(deepen_text, clusters, anchors, rules, *, role) -> StageResult` (output=list[ReportClaim]): **claims만** 생성(overview/finalOpinion 생성 안 함 — 검증 후 조립).
- **스테이지 간 전달은 `.output` 언랩 명시**(codex r2-P2): 오케스트레이터가 `StageResult`를 받아 `res.output`을 다음 스테이지에 넘긴다. `error`·`io`는 stages/diagnostics로.
- **evidence는 ID만 받아 코드가 hydrate**(codex r2-B5): LLM row는 `evidence_ids: list[str]`·`anchor_refs: list[str]`만 반환. 코드가 `EventCluster.members`/anchors에서 **존재 검증 후** immutable `EvidenceRef`로 hydrate. 미존재 ID는 drop+사유(날조 차단). LLM이 EvidenceRef 객체를 직접 만들지 않는다.

## Component 5 — 검증 (`report_verify.py`)

기존 `run_verify`(QA 패킷 강결합, verify.py:236) 직접 재사용 금지 — **패턴만 차용**한 report 전용.
- 입력: claims + **evidence bundle**(클러스터 members 본문/excerpt) + typed anchors(codex BLOCKER3: anchor만으론 근거·모순·시점 판정 불가).
- **A1 재감사**(API `verifier`): load-bearing claim 중립 재제시 → 근거성 재판정.
- **A2 반박**(API `verifier_cross`, 교차모델): 지지 claim 반증 탐색 → 발견 시 강등.
- **숫자 대조(코드, G2 개념)**: claim의 수치를 **anchor 정체성 기준**으로 대조(전역 근사매칭 금지). claim.evidence 밖 수치도 anchor로 검증.
- **시점(코드, G3)**: `claim.as_of ≤ effective_now`.
- 산출: `ClaimVerdict{claim_id, status: verified|unverified|rejected, reasons, adjusted_confidence}`. **fail-closed**(명시적 지지 아니면 보수적).

## Component 6 — 결론 조립 (`report_assemble.py`)

codex r1-B5 + r2-P5 해소: **검증 후** 결론 생성, 그리고 **결론은 verified만으로**.
- `assemble_report(clusters, claims, verdicts, anchors, stages, *, now, seq) -> Report`:
  - verdict 적용 후 3분류: **verified**(결론 반영) / **unverified**(claims[]에 남되 confidence=낮 표기, 결론 미반영) / **rejected**(**claims[]에서 제외** — 뷰어가 status 무시하고 "최종 주장"으로 렌더하므로(report.js:230, codex r2-B3). `diagnostics.rejected_claims` + verify stage 기록으로 투명성 유지).
  - **overview/finalOpinion.text: LLM 재합성 금지**(미검증 텍스트 유입 차단 — codex r2). 코드가 verified claim의 title/stance를 결정적으로 연결. verified 0건이면 보수 문구("검증된 주장 없음 — 관망") + confidence="낮".
  - `finalOpinion.confidence`: **코드가 집계**(verified claim들의 최소 — LLM 자가평가 금지).
  - `diagnostics.seams_empty`·`stage_errors`·`rejected_claims` 채움.

---

## Component 7 — 오케스트레이션 & 영속화 (`report_pipeline.py`)

```python
async def run_report_pipeline(store, *, now: datetime, window_hours: int = 12,
                              playbook_corpus: str = CURATOR_CORPUS,
                              overrides: dict | None = None) -> Report: ...
def save_report(report: Report) -> Path: ...            # 엔트리포인트가 호출(파이프라인은 순수)
def main(argv: list[str]) -> int: ...                   # 테스트 가능 계약
```
- **영속화(codex r1-B4)**: **flat** `storage/rag/memory_sector/reports/{id}.json`(서버가 flat만 읽음 — server.mjs:130/161, codex r2 확정). 월파티션·index.jsonl 의존 폐기.
- **ID/seq(codex SF3 + r2-B2 순환 해소)**: `id = "{KST YYYY-MM-DD}-{seq}"`. **할당이 조립보다 먼저**: ① `alloc_report_slot(root, kst_date) -> (seq, path)`가 `os.open(O_CREAT|O_EXCL)`로 빈 파일을 **예약**(충돌 시 seq+1 재시도) → ② `assemble_report(..., seq=seq)` → ③ `save_report(report, path)`가 temp 파일에 쓴 뒤 `os.replace`로 예약 파일 위에 원자 교체. 순환 없음·동시 실행 안전. 날짜=**KST**.
- **엔트리포인트(codex SF6)**: `cd engine && .venv/bin/python -m sector.report_pipeline --now <ISO> --window 12`(루트엔 bare python 없음).
- **user 스코프(codex r1-B8 + r2-P8)**: 이 리포트는 **싱글턴 시스템 리포트** — 기존 시황 리포트·대시보드가 이미 `storage/rag/`(시스템 전역) + 공개 `/api/market-reports`로 존재. playbook은 **요청이 주입하는 임의 user_id가 아니라 고정 큐레이터 코퍼스**(`playbook_corpus`, 기본 ryze_yn 큐레이터). 신규 auth 없음(기존과 동일). **AGENTS.md에 시스템 리포트 예외를 명시 1줄 추가**(r2: "analysis 공유 금지" 문구와의 텍스트 충돌 해소 — 위치·동작 변경 없음, 문서화만).

---

## 출력 계약 & OpenAPI (codex SF5)

`openapi.yaml`의 report는 현재 `additionalProperties: true` → **명시 스키마 추가**: `Report`·`ReportClaim`·`PipelineStage`(alias `generatedAt`/`finalOpinion`). 통합 테스트: 리포트 저장 후 **실제 list/detail 핸들러**로 조회 왕복.

**Report JSON(뷰어 호환 + additive):**
```jsonc
{
  "id":"2026-07-21-2","seq":2,"generatedAt":"<KST ISO>","title":"...",
  "window":{"from":"...","to":"..."},
  "overview":"string",
  "finalOpinion":{"text":"string","confidence":"낮|중|높"},   // confidence 코드 집계
  "claims":[{"title","confidence","status":"verified|unverified",   // rejected는 제외(diagnostics로)
             "trigger","mechanism",
             "evidence":["표시 문자열 — 뷰어가 그대로 렌더(r2-B3: 객체면 [object Object])"],
             "evidence_refs":[{"kind","id","title","ts","source"}],  // typed는 additive 필드로
             "anchor_refs":[],"precedent","precedent_grounded":false,"counter","stance",
             "matched_rules":[],"load_bearing":true}],
  "pipeline":{"stages":[
     {"key":"raw","label":"raw","sources":[...]},
     {"key":"f1","label":"1차 필터 — 관련성","note":"...","items":["문자열"],   // 렌더 안전
      "io":{"in":N,"out":M,"dropped":[{"title","reason"}],"elapsed_ms":T}},      // additive, Phase3 렌더
     {"key":"f2",...},{"key":"f3",...},{"key":"deepen",...},{"key":"synth",...},{"key":"verify",...}
  ]},
  "diagnostics":{"stage_errors":[],"seams_empty":["price_reaction","analyst_reports","case_memory"]}
}
```
`items`는 문자열만(report.js:161 object는 title/text만 렌더). 풍부한 관측치는 `io`에(뷰어가 무시 → 무해, Phase 3에서 렌더).

---

## Phase 1 소폭 수정 (codex r1-B6 + r2-P6/B4)

- `assemble_report_input(store, *, now, ...)`: `now` **필수화**(기본값 제거 — 모순 없이 일관, 기존 호출자는 테스트 6곳뿐이며 전부 now 전달 중, codex r2 확인). 파이프라인이 항상 effective_now 주입.
- **ingested_at 게이트 + 레거시 정책(r2-B4)**: `ingested_at`이 **파싱 가능하고 `> now`면 제외**(look-ahead 차단). **빈 값/파싱 불가면 통과** — 현 저장소에 빈 값 레거시가 대량(카드 1,038·관측 4,277)이라 배제 시 히스토리 전멸. event-ts 창 필터가 여전히 1차 방어이며, 신규 수집분은 ingested_at이 채워지므로 시간이 지나면 게이트가 실효. 정책을 diagnostics에 카운트로 표기(`ingested_unknown`).
- 테스트 픽스처 주의: store.append가 실시계 `ingested_at`을 찍음(store.py:46) → 과거 now 주입 테스트는 **명시적 ingested_at**을 넣어 통과시킨다.
- anchor는 `build_anchors`가 원 `MetricObservation`을 cutoff(`ts ≤ now`)로 읽어 typed 생성(summary 문자열 파싱 아님). `metric_summary` 자체는 대시보드용으로 유지(리포트 경로는 anchors만 사용).

---

## Testing

- 각 스테이지: 수제 입력 + **실제 상류 출력** 2층(대량 동일사유 drop = 버그 신호로 감시). CLI/API role은 주입 stub.
- **CliRole**: `_run_cli` stub으로 JSON 검증·재시도·타임아웃·비정상종료 **raise(폴백)** 경로.
- **폴백**: CLI raise 시 API opus로 넘어가는지(Role 체인).
- **결정성**: effective_now 전파, look-ahead 차단(ts/ingested_at > now 제외), 캡처 role 출력 replay 동일.
- **숫자 대조**: anchor 정체성 불일치 claim이 reject/하향.
- **검증 루프**: rejected load-bearing claim이 overview/finalOpinion에서 빠지는지, confidence 코드 집계.
- **영속화**: seq 원자적 할당(동시 2건 다른 id), 서버 flat 조회 왕복(list+detail 실핸들러), OpenAPI 스키마 검증.
- **골든 리포트 픽스처 1개**(타이밍 필드 정규화, 롤아웃 게이트).

---

## Seams & Phase 경계

- **SEAM(graceful empty → `diagnostics.seams_empty`):** 가격반응 조인(토스, yvon) · 증권사 리포트 · **과거사례/thesis(사용자 별도 구축 중 — 완료 통보 시 precedent 실접지)**.
- **Phase 2 = 파이프라인 생성 + 영속화**(수동 실행). **Phase 3** = 스케줄러(KST 04:39/16:39) + 뷰어 관측성 렌더 + `data-collection.html` 현행화.

## Self-Review (v3)

- codex r1 BLOCKER 1–8 + r2 신규 BLOCKER 1–5·PARTIAL 5·SF1 반영: CLI 인라인 스키마·`structured_output` 파싱·`--tools ""`(실측) / cli 분기는 try 내 run_prompt 뒤 / StageResult `.output` 언랩 명시 / 결론=verified만·LLM 재합성 금지·rejected는 claims[] 제외 / seq 예약→조립→저장 순서 / ingested_at 레거시(빈값 통과) 정책 / evidence ID hydrate(날조 차단) / 뷰어 호환 evidence 문자열+`evidence_refs` additive / AGENTS.md 예외 1줄.
- **테스트 관례**: engine엔 pytest-asyncio 없음 → async 테스트는 **sync test + `asyncio.run(...)`** 래핑(기존 test_reaudit.py 관례).
- **잔여 리스크(수용)**: (1) precedent 실접지는 case-memory 완료까지 seam(날조 금지로 안전). (2) CLI 구조화 출력 신뢰성 — 인라인 스키마 + 재시도 + API 폴백. (3) 레거시 빈 ingested_at 통과는 look-ahead 방어를 event-ts에 의존 — 신규 수집분부터 게이트 실효(진단 카운트로 관찰).
