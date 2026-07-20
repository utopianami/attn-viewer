# engine/evals/chain_judge.py
"""chain_judgment 저지 — gpt-5.5 교차 채점 (스펙 1부).

verdict 축 = 방향 명시 + 근거 정합 (모순 결론 0점 — 봉인 flip_verdict 전제).
claim coverage = 답변의 사실·인과 주장 중 bundle 근거 없는 비율 (r3-B7).
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

AXES = ("mechanism", "state_link", "verdict", "evidence", "countercase")
JUDGE_PROMPT_VERSION = "cj-v3"  # v3: 라벨 유효성 우선·명시적 반전 0점 (봉인 v2 실측 — 튜닝 fixture 06·07로 인코딩)

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
