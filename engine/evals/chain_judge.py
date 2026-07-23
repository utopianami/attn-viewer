# engine/evals/chain_judge.py
"""chain_judgment 저지 — gpt-5.5 교차 채점 (스펙 1부).

verdict 축 = 방향 명시 + 근거 정합 (모순 결론 0점 — 봉인 flip_verdict 전제).
claim coverage = 답변의 사실·인과 주장 중 bundle 근거 없는 비율 (r3-B7).
"""
from __future__ import annotations

import hashlib
import json
import logging

from pydantic import BaseModel, ConfigDict, Field

AXES = ("mechanism", "state_link", "verdict", "evidence", "countercase")
JUDGE_PROMPT_VERSION = "cj-v7"  # cj-v7 확정 계약 — 변형 4종 8항목(strip_evidence 봉인 제거, counter-leak 사전 필터)

_INSTR = """너는 금융 QA 답변의 근거 체인 채점자다. 제공된 evidence bundle 안의 근거만
실재로 인정하라 — bundle에 없는 인용·수치에 기댄 주장은 해당 축 0점.
축 정의:
- mechanism(0/1): 사건을 메커니즘으로 분해했는가 (예: 추론 개선 vs 학습 효율)
- state_link(0/1): 현재 판(자금 사용처·CAPEX 국면·공급사 포지션)과 연결했는가
- verdict(0/1): 방향 판단을 명시했고, 그 판단이 제시된 근거와 정합하는가.
  다음은 반드시 0이다: ①근거와 모순된 결론 ②bundle에 없는 주장·사건(미래 정보 포함)에
  기댄 결론 ③**답변 본문의 근거들이 가리키는 방향과 결론 문장의 방향이 어긋나는 경우**
  (본문 근거가 긍정적인데 결론만 부정, 또는 그 반대 — 결론 문장을 본문과 대조해 방향
  일치를 확인하라) ④결론이 "앞선 근거와 반대로 판단한다"처럼 **명시적으로 근거와
  반대 방향임을 선언**하거나 근거 없이 방향만 선언하는 경우
- evidence(0~1): 루브릭 evidence 목록 중, 답변에서 **bundle에 대응하는 인용과 함께**
  등장한 항목의 비율. 항목마다 **뒷받침 인용 라벨을 확인**하라: 라벨이 bundle 카드
  ID와 일치하거나 해당 내용을 담은 bundle 항목의 출처(매체명·도메인)와 대응하면 유효.
  **라벨이 둘 다 아니면(예: ghost-999 같은 미지 라벨) 항목 내용이 bundle과 겹치더라도
  그 항목은 missing이다 — 라벨 유효성이 내용 일치보다 우선한다.** 수치가 bundle과
  불일치하는 항목도 missing — matched/missing을 정확히 나눠라
- countercase(0/1): 반대 방향 시나리오가 실근거와 함께 있는가
유창함·문체는 채점 대상이 아니다."""

_COVERAGE_INSTR = """답변에서 사실·인과 주장을 전부 추출하고(결론·시나리오 포함),
각 주장이 evidence bundle의 근거로 뒷받침되는지 판정하라. 주장 누락 없이 전수 추출이
원칙이다 — 지원되는 주장만 골라내면 안 된다."""


class ChainAxisScore(BaseModel):
    score: float | None = Field(default=None, ge=0.0, le=1.0)   # B9: 범위 강제
    reason: str = ""
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class ChainJudgeResult(BaseModel):
    case_id: str
    axes: dict[str, ChainAxisScore]
    raws: list[str]                                    # 반복 원시 응답 전량 (권고1)
    judge_model: str
    judge_prompt_version: str


class _JudgeOut(BaseModel):
    mechanism: ChainAxisScore
    state_link: ChainAxisScore
    verdict: ChainAxisScore
    evidence: ChainAxisScore
    countercase: ChainAxisScore


class _Claim(BaseModel):
    text: str
    supported: bool
    why: str = ""


class _CoverageOut(BaseModel):
    claims: list[_Claim]


def judge_config_hash(role) -> str:
    """저지 설정 해시 — provider·model ID·effort(chain_judge 엔트리)·instruction/schema를
    sha256으로 묶어 앞 16자 반환.

    ledger 키를 (version, sealed_hash, judge_config_hash) 세 요소로 구성함으로써
    모델·프롬프트 설정이 바뀌어도 이전 pass가 재사용되는 것을 차단한다.
    """
    provider = getattr(role, "provider", "") or ""
    model_id = getattr(role, "model", "") or ""
    effort = getattr(role, "effort", "") or ""
    h = hashlib.sha256()
    h.update(provider.encode())
    h.update(model_id.encode())
    h.update(effort.encode())
    h.update(_INSTR.encode())
    h.update(json.dumps(_JudgeOut.model_json_schema(), sort_keys=True,
                        ensure_ascii=False).encode())
    return h.hexdigest()[:16]


def _valid(r) -> bool:
    return r is not None and all(r.axes[a].score is not None for a in AXES)


def merge_repeats(a: ChainJudgeResult, b: ChainJudgeResult,
                  tie: ChainJudgeResult | None) -> ChainJudgeResult:
    axes: dict[str, ChainAxisScore] = {}
    for ax in AXES:
        sa, sb = a.axes[ax].score, b.axes[ax].score
        if sa is None or sb is None:
            axes[ax] = ChainAxisScore(score=None, reason="repeat null")
        elif sa == sb:
            axes[ax] = a.axes[ax]
        elif tie is not None and tie.axes[ax].score is not None:
            st = tie.axes[ax].score
            if st == sa:
                axes[ax] = a.axes[ax]
            elif st == sb:
                axes[ax] = b.axes[ax]
            else:
                axes[ax] = ChainAxisScore(score=None, reason="no majority")
        else:
            axes[ax] = ChainAxisScore(score=None, reason="mismatch, no tiebreak")
    raws = a.raws + b.raws + (tie.raws if tie else [])
    return ChainJudgeResult(case_id=a.case_id, axes=axes, raws=raws,
                            judge_model=a.judge_model,
                            judge_prompt_version=a.judge_prompt_version)


async def _judge_once(case_id, answer_md, rubric, bundle_text, role) -> ChainJudgeResult | None:
    prompt = (f"[루브릭]\n{json.dumps(rubric, ensure_ascii=False)}\n\n"
              f"[답변]\n{answer_md}\n\n각 축을 채점하라.")
    for _ in range(2):                                 # invalid/timeout 1회 재시도
        try:
            out = await role.run(prompt, instructions=_INSTR,
                                 response_format=_JudgeOut,
                                 cache_prefix=f"[evidence bundle]\n{bundle_text}")
            data = out if isinstance(out, _JudgeOut) else _JudgeOut.model_validate(out)
            return ChainJudgeResult(
                case_id=case_id, axes={a: getattr(data, a) for a in AXES},
                raws=[data.model_dump_json()], judge_model=role.model,
                judge_prompt_version=JUDGE_PROMPT_VERSION)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).debug("chain_judge retry: %s", exc)
            continue
    return None


def _sink_append(sink: list[str] | None, result: ChainJudgeResult | None) -> None:
    """raws_sink에 원시 응답 또는 "invalid" 마커를 기록한다."""
    if sink is None:
        return
    if result is not None:
        sink.extend(result.raws)
    else:
        sink.append("invalid")


async def judge_case(case_id, answer_md, rubric, bundle_text, role,
                     raws_sink: list[str] | None = None) -> ChainJudgeResult | None:
    r1 = await _judge_once(case_id, answer_md, rubric, bundle_text, role)
    _sink_append(raws_sink, r1)
    r2 = await _judge_once(case_id, answer_md, rubric, bundle_text, role)
    _sink_append(raws_sink, r2)
    if not _valid(r1) or not _valid(r2):
        return None
    if all(r1.axes[a].score == r2.axes[a].score for a in AXES):
        return merge_repeats(r1, r2, tie=None)
    r3 = await _judge_once(case_id, answer_md, rubric, bundle_text, role)
    _sink_append(raws_sink, r3)
    merged = merge_repeats(r1, r2, tie=r3 if _valid(r3) else None)
    return merged if _valid(merged) else None


async def judge_claim_coverage(case_id, answer_md, bundle_text, role,
                               raws_sink: list[str] | None = None) -> float | None:
    """uncovered_claim_ratio — 전수 주장 추출 후 미지원 비율 (r3-B7)."""
    for _ in range(2):
        try:
            out = await role.run(f"[답변]\n{answer_md}", instructions=_COVERAGE_INSTR,
                                 response_format=_CoverageOut,
                                 cache_prefix=f"[evidence bundle]\n{bundle_text}")
            data = out if isinstance(out, _CoverageOut) else _CoverageOut.model_validate(out)
            if raws_sink is not None:
                raws_sink.append(data.model_dump_json())
            if not data.claims:
                return None                            # 주장 0개 = invalid (조작 의심)
            bad = sum(1 for c in data.claims if not c.supported)
            return round(bad / len(data.claims), 3)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).debug("chain_judge retry: %s", exc)
            if raws_sink is not None:
                raws_sink.append("invalid")
            continue
    return None


# ---------------------------------------------------------------------------
# ChainPacket edge 근거 resolver + entailment 저지 (3부 T10, r2-7·r3-4)
# ---------------------------------------------------------------------------


def resolve_edge_evidence(edges: list[dict], bundle, layers: list[dict]) -> dict[str, str]:
    """edges가 인용한 id 전수를 근거 원문으로 역참조 (구조화 ID·전수, r2-7·r3-4).

    소스 = bundle 카드(`bundle.store().read_cards()`) ∪ bundle NewsItem
    (`bundle.ra_news_items()`) ∪ chain layer의 `typed_fact_snapshot`(T5가 체인
    생성 시점 table.typed_facts 전체를 방출 — ChainPacket이 인용 가능한 집합과
    정확히 일치). bundle은 None일 수 있다(스냅샷 id만 인용된 경우).

    fail-hard(자유 문자열 검색·"(미해석 인용)" 마킹 폐기 — 측정 무결성):
      ① 빈 인용 id → ValueError
      ② 전 소스 어디에도 해소되지 않는 id → ValueError(미해석 = 측정 오류)
      ③ 2개 이상의 객체에서 동시에 해소되는 id → ValueError(다중 해소 = 어느
         근거 원문을 저지에 넣을지 정의 불가 — VERIFY 유일 해소 강제와 동일 원칙).
         같은 소스 내 중복(예: 뉴스 리스트에 같은 id가 2번)도 여기 포함된다 —
         3부 T11 블로커1: dict comprehension으로 조립하면 동일 소스 중복을 조용히
         덮어써(마지막 항목 승) 다중 해소가 은폐되므로 카운트로 먼저 잡는다.
    """
    from collections import Counter

    from evals.metrics import chain_layer as _chain_layer

    chain = _chain_layer(layers) or {}
    snapshot: dict = chain.get("typed_fact_snapshot") or {}

    card_counts: Counter = Counter()
    news_counts: Counter = Counter()
    cards_by_id: dict = {}
    news_by_id: dict = {}
    if bundle is not None:
        # limit=100_000 — bundle.py:70의 500-limit 함정 회피 (다른 소비면과 동일 관례)
        cards = bundle.store().read_cards(days=None, limit=100_000)
        for c in cards:
            cid = getattr(c, "id", None)
            if cid:
                card_counts[cid] += 1
                cards_by_id[cid] = c
        for d in bundle.ra_news_items():
            did = d.get("id")
            if did:
                news_counts[did] += 1
                news_by_id[did] = d

    ids: list[str] = []
    for e in edges:
        ids.extend(e.get("supporting_card_ids") or [])
        ids.extend(e.get("metric_fact_ids") or [])
        ids.extend(e.get("contradicting_card_ids") or [])

    evidence: dict[str, str] = {}
    for cid in dict.fromkeys(ids):                      # 유일 id만, 원 순서 유지
        if not cid:
            raise ValueError("resolve_edge_evidence: 빈 인용 id — 비공백 강제 (r3-4)")
        n_card = card_counts.get(cid, 0)
        n_news = news_counts.get(cid, 0)
        n_fact = 1 if cid in snapshot else 0
        total = n_card + n_news + n_fact
        if total == 0:
            raise ValueError(f"resolve_edge_evidence: 미해석 인용 id: {cid!r} "
                              "(T5 코드 검증이 인용 실존을 보장하므로 측정 오류)")
        if total > 1:
            kinds = (["card"] * n_card) + (["news"] * n_news) + (["fact"] * n_fact)
            raise ValueError(f"resolve_edge_evidence: 다중 해소 id: {cid!r} "
                              f"— {kinds} 전부에서 발견(유일 해소 실패, r3-4)")
        if n_card:
            c = cards_by_id[cid]
            evidence[cid] = f"{cid}: {c.title} — {c.raw_quote}"
        elif n_news:
            d = news_by_id[cid]
            snippet = d.get("snippet") or d.get("summary") or ""
            evidence[cid] = f"{cid}: {d.get('title', '')} — {snippet}"
        else:
            f = snapshot[cid]
            evidence[cid] = (f"{cid}: {f.get('label', '')} = "
                             f"{f.get('value')}{f.get('unit', '')} "
                             f"(source={f.get('source', '')})")
    return evidence


class _EdgeRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    entailed: bool
    reason: str = ""


class _EdgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[_EdgeRow] = Field(default_factory=list)


_EDGE_INSTR = """너는 금융 인과 사슬(edge)의 근거 정합성을 판정하는 채점자다. 각 edge에
제시된 인용 근거 원문(resolver 역참조 결과)이 그 edge가 주장하는 인과를 실제로
뒷받침하는지 판정하라(entailed: true/false, reason에 근거 사유). 근거가 없거나
edge 주장과 무관하면 entailed=false로 판정하라. thesis_claims가 제공되면 배경
판(과거 판단)과의 정합 여부도 함께 고려하되, edge 자체의 근거 정합이 우선이다.
rows는 제공된 edge_id 전부에 대해 정확히 한 번씩만 반환하라 — 누락·중복·미지
edge_id는 무효 응답이다."""


def _build_edge_prompt(edges: list[dict], evidence_by_id: dict[str, str],
                       thesis_claims: list[str] | None) -> str:
    lines = ["[edges]"]
    for e in edges:
        eid = e.get("edge_id", "")
        lines.append(f"- {eid}: {e.get('edge', '')} ({e.get('kind', '')})")
        cite_ids = (list(e.get("supporting_card_ids") or [])
                    + list(e.get("metric_fact_ids") or [])
                    + list(e.get("contradicting_card_ids") or []))
        for cid in cite_ids:
            if cid in evidence_by_id:
                lines.append(f"  근거[{cid}]: {evidence_by_id[cid]}")
    if thesis_claims:
        lines.append("[thesis_claims]")
        for c in thesis_claims:
            lines.append(f"- {c}")
    return "\n".join(lines)


async def judge_edge_entailment(case_id, edges: list[dict], evidence_by_id: dict[str, str],
                                role, *, thesis_claims: list[str] | None = None,
                                raws_sink: list[str] | None = None) -> float | None:
    """edge별 근거 정합 판정 — entailed / 전체 edge (B9).

    구조화 판정 `_EdgeOut{rows: [{edge_id, entailed, reason}]}`. 반환 rows의
    edge_id 집합이 edges의 edge_id 집합과 정확히 일치하지 않으면(누락·중복·미지
    id) invalid — 1회 재시도 후에도 invalid면 None. edges 빈 목록이면 None.
    """
    if not edges:
        return None
    # 3부 T11 블로커2 — post-merge 불변식(canonical edge 유일)이 깨진 채 여기까지
    # 오면 측정 오류다 — 은폐 없이 드러낸다(중복 semantic edge 독립 거부).
    edge_texts = [e.get("edge") for e in edges]
    if len(set(edge_texts)) != len(edge_texts):
        dupes = sorted({t for t in edge_texts if edge_texts.count(t) > 1})
        raise ValueError(f"judge_edge_entailment: 중복 canonical edge: {dupes}")
    edge_id_set = {e["edge_id"] for e in edges}
    prompt = _build_edge_prompt(edges, evidence_by_id, thesis_claims)

    for _ in range(2):                                   # invalid/timeout 1회 재시도
        try:
            out = await role.run(prompt, instructions=_EDGE_INSTR,
                                 response_format=_EdgeOut)
            data = out if isinstance(out, _EdgeOut) else _EdgeOut.model_validate(out)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).debug("judge_edge_entailment retry: %s", exc)
            if raws_sink is not None:
                raws_sink.append("invalid")
            continue

        row_ids = [r.edge_id for r in data.rows]
        if set(row_ids) != edge_id_set or len(row_ids) != len(set(row_ids)):
            if raws_sink is not None:
                raws_sink.append("invalid")
            continue

        if raws_sink is not None:
            raws_sink.append(data.model_dump_json())
        entailed_count = sum(1 for r in data.rows if r.entailed)
        return round(entailed_count / len(edges), 3)
    return None
