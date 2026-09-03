"""P23 off-arm structure harness (fixed clock and hermetic data stores).

pytest 의존 없음 — capture `__main__`과 `test_p23_off_identity.py`가 공유 (브리핑 Step 1).

등치 계약: "동일 고정 시계 하에서 (a) 전 LLM 프롬프트 (b) layer 스트림 (c) FinalAnswer dump의
JSON 구조 등치" (canonical 직렬화 비교 아님).

이 모듈이 하는 일:
1. FIXED_TODAY 시계 고정 seam(모듈 attr) 몽키패치
2. casemem `_STORE` 임시 store 선주입(라이브 시드 차단) + `query_case_memory_async` 캔드 패치
3. playbook STORAGE_ROOT 격리 + golden-user 플레이북 실기록(문자열 게이트만)
4. 고정 시드 SectorStore + eval bundle 캡처(가격·매크로·RA 문서 전부 고정)
5. `providers.Role` 몽키패치 — 실제 호출 역할 15종 전수 canned, 미등록은 KeyError
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as _real_datetime_mod
import json
import re as _re
import subprocess
import sys
import tempfile
from datetime import date as _real_date
from pathlib import Path

# python -m tests.p23_harness 실행 시(cwd=<repo>/engine) 이미 sys.path[0]에 engine이 잡히지만,
# pytest 경유 임포트(`from tests.p23_harness import ...`)에서도 안전하도록 명시 보강.
_ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

FIXED_TODAY = "2026-07-10"          # bundle as_of와 동일
QUESTION = "SK하이닉스 HBM 현물가 흐름 어때?"

# 골든 케이스 2개 (r2-1d) — base: user_id="" (matched 경로 미실행) / playbook: golden-user (매칭)
CASES: tuple[tuple[str, str], ...] = (("base", ""), ("playbook", "golden-user"))

_NONDETERMINISTIC_KEYS = ("elapsed_s", "cost", "planner_ms")

# ---------------------------------------------------------------------------
# 호출 기록 — providers.Role 몽키패치가 채운다 (role_name, instructions, prompt) 순서대로
# ---------------------------------------------------------------------------
_CALL_LOG: list[dict] = []


def _strip_nondeterministic(obj):
    """elapsed_s·cost·planner_ms 키를 어디에 있든 재귀 제거 (값이 비결정)."""
    if isinstance(obj, dict):
        return {k: _strip_nondeterministic(v) for k, v in obj.items()
                if k not in _NONDETERMINISTIC_KEYS}
    if isinstance(obj, list):
        return [_strip_nondeterministic(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# canned Role 응답 — (role_name, response_format 클래스명 또는 None) → 값 | callable(prompt)->값
# ---------------------------------------------------------------------------

def _build_canned() -> dict:
    from stages.triage import _TriageLLM
    from stages.plan import _PlanA, _PlanB
    from sector.queryplan import SectorQueryPlan
    from stages.da import _Claim, _DaAnswer
    from stages.answerability import _AnsLLM, _UnitVerdict
    from stages.ra_external import _Curation, _TrendSynth, _WebKnowledge, _XClaims
    from stages.news_summary import _Line, _Summary
    from stages.calc import _Program, _Programs
    from stages.verify import _V, _Verdicts
    from stages.risk import _Bear, _Risk
    from stages.audit import _Entails, _NewFacts
    from stages.chain import _ChainOut, _ChainOutEdge

    def _canned_verdicts(prompt: str):
        ids = _re.findall(r"id=(\S+)", prompt)
        return _Verdicts(verdicts=[
            _V(claim_id=cid, verdict="supported", note="근거 정합") for cid in ids])

    canned: dict = {
        # ── TRIAGE (role="plan_extract" 재사용, triage.py:101)
        ("plan_extract", "_TriageLLM"): _TriageLLM(
            route="deep", needs_fresh_data=True, reason="새 종목 판단 질문",
            question_type="stock_judgment", type_confidence="high",
            requires_countercase=True),

        # ── PLAN A/B (plan.py:170~171)
        ("planner", "_PlanA"): _PlanA(
            standalone_question=QUESTION, tier=3, knowledge_cutoff=FIXED_TODAY,
            market_scope="kr", search_queries=["SK하이닉스 HBM 현물가"],
            sub_questions=[], contrast_questions=[], needed_evidence=[]),
        ("plan_extract", "_PlanB"): _PlanB(
            fiscal_periods=[], metrics=["기간수익률"], tickers_supplement=[],
            unresolved_entities=[], richness_grade="B", tier_opinion=3,
            cutoff_opinion=FIXED_TODAY),

        # ── SECTOR_RAG 쿼리 플래너 (queryplan.py:152)
        ("sector_query", "SectorQueryPlan"): SectorQueryPlan(
            sector="memory", segments=["hbm"], entities=["SK_HYNIX"],
            metrics=["memory_price_usd_per_gb"], event_types=[], days=14,
            until=None, keywords=["현물가"]),

        # ── DA 이중 블라인드 (da.py:85~89) — 둘 다 type=fact(값 없음) → G2 비관여, G1만
        ("da_gpt", "_DaAnswer"): _DaAnswer(
            answer="SK하이닉스 HBM 현물가는 최근 상승 흐름이라는 평가가 일반적이다.",
            claims=[
                _Claim(text="SK하이닉스 HBM 현물가는 최근 상승 흐름이다", type="fact",
                       uncertainty="medium", entity="SK하이닉스", metric="현물가"),
                _Claim(text="HBM 수요는 AI 서버 확대로 견조하다", type="fact",
                       uncertainty="medium", entity="SK하이닉스", metric="HBM 수요"),
            ]),
        ("da_fable", "_DaAnswer"): _DaAnswer(
            answer="공급 측 증설 부담이 있어 낙관은 이르다는 시각도 있다.",
            claims=[
                _Claim(text="HBM 공급사 증설이 이어지고 있다", type="fact",
                       uncertainty="medium", entity="SK하이닉스", metric="공급"),
            ]),

        # ── ANSWERABILITY (answerability.py:126, role="extract")
        ("extract", "_AnsLLM"): _AnsLLM(
            unit_verdicts=[_UnitVerdict(unit_id="q0", verdict="answerable")],
            supplements=[]),
        # ── RA_EXTERNAL의 "extract" 재사용 호출부(방어적 등록 — eval bundle 경로에선
        #    미도달이지만 role 전수 canned 원칙에 따라 함께 등록)
        ("extract", "_Curation"): _Curation(units=[]),
        ("extract", "_XClaims"): _XClaims(claims=[]),
        ("extract", "_TrendSynth"): _TrendSynth(trends=[]),
        # ── web_knowledge(ra_external.py:365) — eval bundle 경로에선 미도달, 방어적 등록
        ("web_knowledge", "_WebKnowledge"): _WebKnowledge(notes=[]),

        # ── NEWS_SUMMARY (news_summary.py:56)
        ("news_summary", "_Summary"): _Summary(lines=[
            _Line(text="HBM 현물가 상승 흐름이 이어지고 있다는 보도가 있다",
                  url="https://example.com/news1"),
        ]),

        # ── CALC (calc.py:113) — typed_fact ret:000660.KS 그대로 통과(계산 불필요)
        ("calc_program", "_Programs"): _Programs(
            programs=[_Program(metric="기간수익률", unit_id="q0", steps=[],
                               passthrough_fact_id="ret:000660.KS")],
            missing_inputs=[]),

        # ── VERIFIER G1 (verify.py:298~302·394~395·422~423) — 프롬프트의 claim id 그대로 supported
        ("verifier", "_Verdicts"): _canned_verdicts,
        ("verifier_cross", "_Verdicts"): _canned_verdicts,

        # ── RISK (risk.py:47)
        ("risk", "_Risk"): _Risk(
            bear_cases=[
                _Bear(text="공급 증설이 가격 상승을 조기에 꺾을 수 있다",
                      supporting_claim_ids=["da_fable:q0:c0"]),
                _Bear(text="수요 둔화 시나리오도 배제할 수 없다", supporting_claim_ids=[]),
            ],
            wrong_if="공급 증설 속도가 예상보다 빠르면 이 분석은 틀릴 수 있다"),

        # ── CHAIN (chain.py:126, 3부 T5·T10) — 실존 카드 id 인용 결정적 제안.
        #    off-arm은 이 블록이 아예 미도달(memory_sector_active/table.claims
        #    게이트가 코드에서 스킵)이라 T1 golden은 무영향(additive-safe).
        ("chain_synth", "_ChainOut"): _ChainOut(
            event="HBM 현물가 상승 보도", mechanism="공급 타이트로 가격 상승 전이",
            verdict="상승 압력 우세",
            edges=[_ChainOutEdge(
                edge="B->A", kind="observed",
                supporting_card_ids=["card:hbm:001"],
                metric_fact_ids=[], contradicting_card_ids=[])],
            thesis_relation=[]),

        # ── SYNTHESIZER (synthesize.py:234) — 자유 텍스트(response_format 없음)
        #    숫자·마크다운 인용 링크·지시어 문구 없음 (audit 감사 경로를 단순·결정적으로 유지)
        ("synthesizer", None): (
            "SK하이닉스 HBM 현물가는 상승 흐름으로 해석되나, 공급 증설 변수도 함께 "
            "고려해야 한다는 평가가 있다. 검증된 사실과 미검증 해석을 구분해 판단이 필요하다."),

        # ── AUDIT (audit.py:240·273)
        ("audit", "_NewFacts"): _NewFacts(entities=[]),
        ("audit", "_Entails"): _Entails(judgements=[]),

        # ── casemem_rerank(orchestrator.py:389) — query_case_memory_async 캔드 패치로
        #    실제로는 호출되지 않지만(빈 매치 조기 반환) role 전수 등록 원칙상 방어적 등록
        ("casemem_rerank", None): "",
    }
    return canned


_CANNED: dict | None = None


def _canned() -> dict:
    global _CANNED
    if _CANNED is None:
        _CANNED = _build_canned()
    return _CANNED


# ---------------------------------------------------------------------------
# providers.Role 몽키패치 — 클래스 객체 자체를 패치(모든 `from providers import Role`가
# 동일 클래스 객체를 참조하므로 이렇게 해야 전 모듈에 적용된다)
# ---------------------------------------------------------------------------

def _fake_role_init(self, role, overrides=None, meter=None):
    self.role = role
    self.provider = "fake"
    self.model = "fake"
    self.effort = "low"


async def _fake_role_run(self, prompt, instructions="", *, response_format=None,
                         effort=None, cache_prefix=None):
    _CALL_LOG.append({"role": self.role, "instructions": instructions, "prompt": prompt})
    key = (self.role, response_format.__name__ if response_format is not None else None)
    maker = _canned().get(key)
    if maker is None:
        raise KeyError(
            f"p23_harness: no canned response for role={self.role!r} "
            f"response_format={key[1]!r} — 캔드 미등록(누락 가시화)")
    val = maker(prompt) if callable(maker) else maker
    if response_format is not None and not isinstance(val, response_format):
        val = response_format.model_validate(val)
    return val


# ---------------------------------------------------------------------------
# 고정 시계 — 코드에 이미 있는 monkeypatch 가능 seam(모듈 attr)만 사용
# ---------------------------------------------------------------------------

class _FixedDate(_real_date):
    @classmethod
    def today(cls):
        return cls.fromisoformat(FIXED_TODAY)


class _FixedDatetime(_real_datetime_mod.datetime):
    @classmethod
    def now(cls, tz=None):
        base = cls.fromisoformat(FIXED_TODAY)
        return base.replace(tzinfo=tz) if tz is not None else base


class _FixedDtModule:
    """sector.retrieve._dt(`import datetime as _dt`) 대체 — datetime.now만 고정."""
    datetime = _FixedDatetime
    timezone = _real_datetime_mod.timezone
    timedelta = _real_datetime_mod.timedelta
    date = _FixedDate


# ---------------------------------------------------------------------------
# eval bundle + playbook 고정 픽스처
# ---------------------------------------------------------------------------

def _build_eval_bundle(tmp_path: Path) -> Path:
    from evals.bundle import capture_bundle
    from sector.contracts import MetricObservation, SectorCard
    from sector.store import SectorStore

    store = SectorStore(tmp_path / "sector_store")
    store.append_cards([
        SectorCard(id="card:hbm:001", ts="2026-07-05T00:00:00", axis="B",
                  entities=["SK_HYNIX"], event_type="price_signal",
                  memory_segment="hbm", direction="pos", magnitude=2,
                  source_grade="A", title="HBM 현물가 상승 보도",
                  raw_quote="HBM 현물가가 최근 상승세를 보이고 있다는 업계 보도가 나왔다.",
                  interpreted_signal="현물가 상승 신호",
                  url="https://example.com/card1", source="dam",
                  ingested_at="2026-07-05T00:00:00"),
        SectorCard(id="card:hbm:002", ts="2026-07-06T00:00:00", axis="C",
                  entities=["SK_HYNIX", "MICRON"], event_type="supply_signal",
                  memory_segment="hbm", direction="neg", magnitude=1,
                  source_grade="B", title="HBM 공급 증설 소식",
                  raw_quote="주요 메모리 3사가 HBM 생산 능력 증설에 나서고 있다.",
                  interpreted_signal="공급 확대 신호",
                  url="https://example.com/card2", source="dam",
                  ingested_at="2026-07-06T00:00:00"),
        SectorCard(id="card:hbm:003", ts="2026-07-08T00:00:00", axis="A",
                  entities=["SK_HYNIX"], event_type="demand_signal",
                  memory_segment="hbm", direction="pos", magnitude=2,
                  source_grade="S", title="AI 서버향 HBM 수요 확대",
                  raw_quote="AI 서버 수요 확대로 HBM 주문이 늘고 있다는 소식이다.",
                  interpreted_signal="수요 확대 신호",
                  url="https://example.com/card3", source="dam",
                  ingested_at="2026-07-08T00:00:00"),
    ])
    store.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07-01",
                          value=0.10, unit="USD/GB",
                          meta={"category": "DRAM", "item": "DDR5"},
                          ingested_at="2026-07-01T00:00:00"),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07-08",
                          value=0.11, unit="USD/GB",
                          meta={"category": "DRAM", "item": "DDR5"},
                          ingested_at="2026-07-08T00:00:00"),
    ])

    ra_docs = [{
        "id": "news:hbm:001", "title": "HBM 현물가 상승 보도",
        "summary": "HBM 현물가가 오름세라는 보도가 나왔다.",
        "content": ("SK하이닉스 등 메모리 업체의 HBM 현물가가 최근 상승세를 "
                   "보이고 있다는 보도가 나왔다."),
        "url": "https://example.com/news1", "published_at": "2026-07-09",
        "source_name": "예시신문", "feed_count": 1, "tabs": [],
    }]
    prices = {"quotes": [{"token": "000660.KS", "symbol": "000660.KS",
                         "last": 250000.0, "cur": "KRW", "ret_pct": 12.34}]}

    bundle_dir = tmp_path / "bundle"
    capture_bundle(store, bundle_dir, as_of=FIXED_TODAY, availability="unproven",
                   ra_docs=ra_docs, prices=prices, macro={})
    return bundle_dir


def _write_playbook(tmp_path: Path) -> None:
    pb_dir = tmp_path / "storage" / "users" / "golden-user" / "corpus" / "playbooks"
    pb_dir.mkdir(parents=True, exist_ok=True)
    pb = {
        "slug": "hbm-cycle",
        "situation": "HBM 현물가 상승 국면 점검",
        "triggers": ["HBM 현물가 상승 보도"],
        "topics": ["HBM", "메모리"],
        "matchKeys": ["HBM"],
        "conclusionType": "방향 판단",
        "gates": [{"order": 1, "check": "현물가 추세 확인",
                  "operationalization": "최근 관측치가 직전 대비 상승",
                  "kill": "하락 전환 시 기각"}],
        "connection": "가격 상승과 수요 확대가 겹치면 방향성 판단에 참고한다",
        "reservations": "공급 증설 속도에 따라 조기 반전 가능",
        "status": "holdout_passed",
    }
    (pb_dir / "hbm-cycle.json").write_text(
        json.dumps(pb, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# _hermetic — 전 패치 try/finally 원복 (pytest 의존 없음, capture __main__과 공유)
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _hermetic(tmp_path: Path):
    import providers
    import sector.queryplan as queryplan_mod
    import sector.retrieve as retrieve_mod
    import stages.plan as plan_mod
    import stages.playbook as playbook_mod
    import stages.verify as verify_mod
    import casemem.api as casemem_api_mod
    import casemem.async_query as casemem_async_mod
    from casemem.contracts import CaseQueryResult
    from casemem.store import CaseStore

    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    bundle_dir = _build_eval_bundle(tmp_path)
    _write_playbook(tmp_path)

    async def _canned_query_case_memory_async(store, *, signals, as_of,
                                              sector="memory", k=5, role=None):
        return CaseQueryResult(as_of=as_of, sector=sector, matches=[], scanned=0,
                               dropped_after_as_of=0, dropped_sector=0,
                               rerank_used=False, rerank_failed=False)

    orig_role_init = providers.Role.__init__
    orig_role_run = providers.Role.run
    orig_today = plan_mod.TODAY
    orig_qp_date = queryplan_mod.date
    orig_retrieve_dt = retrieve_mod._dt
    orig_storage_root = playbook_mod.STORAGE_ROOT
    orig_case_store = casemem_api_mod._STORE
    orig_query_case_memory_async = casemem_async_mod.query_case_memory_async
    orig_g1_judge = verify_mod._g1_judge

    try:
        providers.Role.__init__ = _fake_role_init
        providers.Role.run = _fake_role_run
        plan_mod.TODAY = FIXED_TODAY
        queryplan_mod.date = _FixedDate
        retrieve_mod._dt = _FixedDtModule
        playbook_mod.STORAGE_ROOT = tmp_path / "storage"
        casemem_api_mod._STORE = CaseStore(tmp_path / "cm")
        casemem_async_mod.query_case_memory_async = _canned_query_case_memory_async
        yield bundle_dir
    finally:
        providers.Role.__init__ = orig_role_init
        providers.Role.run = orig_role_run
        plan_mod.TODAY = orig_today
        queryplan_mod.date = orig_qp_date
        retrieve_mod._dt = orig_retrieve_dt
        playbook_mod.STORAGE_ROOT = orig_storage_root
        casemem_api_mod._STORE = orig_case_store
        casemem_async_mod.query_case_memory_async = orig_query_case_memory_async
        verify_mod._g1_judge = orig_g1_judge


async def _run_once(question: str, overrides: dict, user_id: str) -> dict:
    global _CALL_LOG
    _CALL_LOG = []
    from orchestrator import run_qa

    layers: list[dict] = []
    final: dict | None = None
    async for item in run_qa(question, overrides=overrides, user_id=user_id):
        if item.get("kind") == "final":
            final = item
        else:
            layers.append(item)

    result = {
        "prompts": list(_CALL_LOG),
        "layers": layers,
        "final": final,
    }
    return _strip_nondeterministic(result)


def run_pipeline(question: str, *, overrides_extra: dict | None = None,
                 user_id: str = "", tmp_path) -> dict:
    """`run_qa(question, overrides={"eval_bundle": bundle, **overrides_extra}, user_id=user_id)`
    수집 → {"prompts": [...], "layers": [...], "final": {...}} 반환 (정규화됨)."""
    with _hermetic(tmp_path) as bundle_dir:
        overrides = {"eval_bundle": str(bundle_dir), **(overrides_extra or {})}
        return asyncio.run(_run_once(question, overrides, user_id))


# ---------------------------------------------------------------------------
# 캡처 — 의도적으로 검토한 현재 revision에서만 실행한다.
# ---------------------------------------------------------------------------

def _capture_golden() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_root),
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    base_tmp = Path(tempfile.mkdtemp(prefix="p23_capture_"))
    cases: dict = {}
    for case_id, user_id in CASES:
        case_tmp = base_tmp / case_id
        cases[case_id] = run_pipeline(
            QUESTION, overrides_extra={"disable_p23": True}, user_id=user_id,
            tmp_path=case_tmp)

    out = {
        "_meta": {
            "contract": "current-off-arm-structure-v1",
            "captured_at_sha": sha,
            "fixed_today": FIXED_TODAY,
        },
        "cases": cases,
    }
    fixtures_dir = Path(__file__).parent / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    golden_path = fixtures_dir / "p23_off_golden.json"
    golden_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"[p23_harness] captured -> {golden_path} (captured_at_sha={sha})")
    return golden_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", action="store_true",
                        help="capture the reviewed current off-arm structural snapshot")
    args = parser.parse_args()
    if not args.capture:
        parser.error("--capture 플래그가 필요합니다")
    _capture_golden()
