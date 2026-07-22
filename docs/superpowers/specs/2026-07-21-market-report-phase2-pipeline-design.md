# 시황 리포트 Phase 2 — 파이프라인 설계 (Filters → 심화 → 합성 → 검증) · v2

> 설계 스냅샷 2026-07-21 · 상위 설계: `public/html/market-report-design.html` §1–8 · 입력: Phase 1 `engine/sector/report_input.py` · 출력 스키마: `storage/rag/memory_sector/reports/2026-07-21-1.json`(샘플) · **v2: codex r1 리뷰(BLOCKER 8·SHOULD-FIX 6) 반영**

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

**통합(codex BLOCKER1 해소):** ROLE_MAP fallback 의미(=raise 시 다음)를 지키기 위해 별도 client 대신 **`Role.run` 루프 안에 분기**를 둔다.
```python
# providers.py
def _capable(provider):
    if provider == "cli":
        return shutil.which("claude") is not None or shutil.which("codex") is not None
    return settings.capabilities().get(provider, False)

# Role.run 루프 내부, _make_client 앞:
if provider == "cli":
    val = await cli_complete(model, instr, run_prompt,
                             response_format=response_format, effort=effort)
    # 성공: structured면 검증된 인스턴스, 아니면 str. 실패 시 cli_complete가 raise → 다음 체인.
    return val
```
ROLE_MAP 예: `"report_deepen": [("cli","claude","high"), ("anthropic", model_claude, "high")]` — CLI 실패 시 **API opus로 자동 폴백**.

**`cli_complete(model, instructions, prompt, *, response_format, effort) -> Any`:**
- claude: `claude -p --output-format json --json-schema <tmpfile> --allowedTools "" --disallowedTools "..." ` (툴 없음), 프롬프트는 **stdin**. codex 대체: `codex exec --output-schema <f> --output-last-message <f> -s read-only`.
- `response_format` → `model_json_schema()`를 임시파일로. 결과 JSON을 `response_format.model_validate_json` 검증.
- 실패(비정상 종료·타임아웃·JSON 파싱·검증 실패): **raise**(폴백 유발). 파싱만 실패 시 1회 재시도 후 raise.
- run-log: elapsed_ms·모델·프롬프트 해시·exit·성패 기록(CostMeter 대체 계측). stderr 분리, stdout 크기 캡.
- 서브프로세스는 `_run_cli(argv, stdin_text, timeout) -> (rc, out, err)`로 추상화 → 테스트 stub.

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

- `deepen(clusters, rules, anchors, *, role) -> StageResult[DeepenResult]`: CLI claude로 관측+규칙 대조 논증(설계 §4: 나이브 기각 → if/then 비추기 → 비직관 결론). 산술 금지(anchor 값 인용만).
- `synthesize_claims(deep, clusters, anchors, *, role) -> StageResult[list[ReportClaim]]`: **claims만** 생성(overview/finalOpinion 생성 안 함 — 검증 후 조립). 각 claim은 `evidence: list[EvidenceRef]`·`anchor_refs`·`as_of`·`load_bearing`·`matched_rules` 포함.

## Component 5 — 검증 (`report_verify.py`)

기존 `run_verify`(QA 패킷 강결합, verify.py:236) 직접 재사용 금지 — **패턴만 차용**한 report 전용.
- 입력: claims + **evidence bundle**(클러스터 members 본문/excerpt) + typed anchors(codex BLOCKER3: anchor만으론 근거·모순·시점 판정 불가).
- **A1 재감사**(API `verifier`): load-bearing claim 중립 재제시 → 근거성 재판정.
- **A2 반박**(API `verifier_cross`, 교차모델): 지지 claim 반증 탐색 → 발견 시 강등.
- **숫자 대조(코드, G2 개념)**: claim의 수치를 **anchor 정체성 기준**으로 대조(전역 근사매칭 금지). claim.evidence 밖 수치도 anchor로 검증.
- **시점(코드, G3)**: `claim.as_of ≤ effective_now`.
- 산출: `ClaimVerdict{claim_id, status: verified|unverified|rejected, reasons, adjusted_confidence}`. **fail-closed**(명시적 지지 아니면 보수적).

## Component 6 — 결론 조립 (`report_assemble.py`)

codex BLOCKER5 해소: **검증 후** overview/finalOpinion 생성.
- `assemble_report(clusters, claims, verdicts, anchors, stages, *, now, seq) -> Report`:
  - **rejected claim은 결론에서 제외**(pipeline.stages엔 투명 기록). accepted(verified/unverified) claim만 반영.
  - overview: accepted claim 요약(짧은 LLM 합성 또는 규칙 서술 — accepted만 입력).
  - `finalOpinion.confidence`: **코드가 집계**(accepted claim들의 최소/가중 — LLM 자가평가 금지, 설계 §5 불변식).
  - claim에 최종 `status` 부착. `diagnostics.seams_empty`·`stage_errors` 채움.

---

## Component 7 — 오케스트레이션 & 영속화 (`report_pipeline.py`)

```python
async def run_report_pipeline(store, *, now: datetime, window_hours: int = 12,
                              playbook_corpus: str = CURATOR_CORPUS,
                              overrides: dict | None = None) -> Report: ...
def save_report(report: Report) -> Path: ...            # 엔트리포인트가 호출(파이프라인은 순수)
def main(argv: list[str]) -> int: ...                   # 테스트 가능 계약
```
- **영속화(codex BLOCKER4)**: **flat** `storage/rag/memory_sector/reports/{id}.json`(서버가 flat만 읽음 — server.mjs:126/153). 월파티션·index.jsonl 의존 폐기(서버가 안 읽음). 
- **ID/seq(codex SF3)**: `id = "{KST YYYY-MM-DD}-{seq}"`. seq 할당 = **원자적 배타 생성**(`open(path,'x')` 실패 시 seq+1 재시도) → 동시 실행 충돌·덮어쓰기 방지. JSON을 temp+rename으로 먼저 확정. 날짜=**KST**(샘플·스케줄·뷰어 슬라이스 일치).
- **엔트리포인트(codex SF6)**: `cd engine && .venv/bin/python -m sector.report_pipeline --now <ISO> --window 12`(루트엔 bare python 없음).
- **user 스코프(codex BLOCKER8)**: 이 리포트는 **싱글턴 시스템 리포트** — 기존 시황 리포트·대시보드가 이미 `storage/rag/`(시스템 전역) + 공개 `/api/market-reports`로 존재. AGENTS.md user-storage/auth 규칙은 *user 문서* 대상이고 rag/ 시장데이터는 별도 시스템 트리. playbook은 **요청이 주입하는 임의 user_id가 아니라 고정 큐레이터 코퍼스**(`playbook_corpus`, 기본 ryze_yn 큐레이터). 신규 auth 없음(기존과 동일).

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
  "claims":[{"title","confidence","status":"verified|unverified|rejected",
             "trigger","mechanism","evidence":[{"kind","id","title","ts","source"}],
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

## Phase 1 소폭 수정 (codex BLOCKER6)

- `assemble_report_input(store, *, now, ...)`: `now` **필수화**(파이프라인이 항상 effective_now 주입). cards/news를 event ts뿐 아니라 `ingested_at ≤ now`로도 필터(availability).
- `build_metric_summaries`/`metric_summary`가 `now`를 무시하고 최신 관측을 씀 → **cutoff 인지 경로** 추가(`ts ≤ now` 관측만). anchor는 `build_anchors`가 원 `MetricObservation`을 cutoff로 읽어 typed 생성(summary 문자열 파싱 아님).

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

## Self-Review (v2)

- codex r1 BLOCKER 1–8 전부 반영: CliRole=Role 분기+raise폴백 / async·typed StageResult / EvidenceRef·typed anchor / flat 저장+save 소유 / 검증→결론 순서 / effective_now·cutoff / 결정적 랭커+topics유도 / 싱글턴 시스템 리포트. SHOULD-FIX 1–6·NIT 반영.
- **잔여 리스크(수용)**: (1) precedent 실접지는 case-memory 완료까지 seam(날조 금지로 안전). (2) CLI 구조화 출력 신뢰성 — 네이티브 `--json-schema` + 재시도 + API 폴백. (3) Phase 1 수정이 기존 호출자에 영향 — `now` 기본값 유지하되 파이프라인만 필수 주입(회귀 테스트로 가드).
