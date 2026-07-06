"""ANSWERABILITY 스테이지 — 증거로 답 가능한지 선판정 + 표적 보완질문 (P1-3/P1-4, F6).

F6(HiREC): 딥리서치류 오류의 46.5%가 검색(증거 부족·노이즈)에서 온다.
검증(G1~G4)이 실패를 '발견'하기 전에, 조립 직후 "지금 증거로 답이 되는가"를 묻고
부족한 사실 하나를 특정하는 보완질문을 만들어 표적 재검색 1회를 선제 발동한다.
기존 REFLECT 루프는 게이트 실패용 2차 안전망으로 유지 — 총 라운드 상한 2 공유.

① 코드 프리패스 (mini 불경유):
   - coverage uncovered(required·obtainable) → 보완 쿼리 직결
   - DA-DA 불일치(P1-4) → "{entity} {metric} 최신 공식 수치" 쿼리 직결
② mini 1콜: 유닛별 answerable|partial|unanswerable + 부족한 사실을 겨냥한 보완질문
   (원질문 재서술 금지 — "2026 Q1 카카오 영업이익 컨센서스"처럼 사실 하나를 특정)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from contracts import ClaimTable, PlanPacket, RaPacket
from providers import Role

_MAX_SUPPLEMENTS = 3   # mini 보완질문 상한 (프리패스 직결분은 별도)
_MAX_PREPASS = 3


class _SO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SupplementQuestion(_SO):
    unit_id: str = "q0"
    question: str
    search_queries: list[str] = Field(default_factory=list)


class _UnitVerdict(_SO):
    unit_id: str
    verdict: str = "answerable"   # answerable | partial | unanswerable


class _AnsLLM(_SO):
    unit_verdicts: list[_UnitVerdict] = Field(default_factory=list)
    supplements: list[SupplementQuestion] = Field(default_factory=list)


class AnswerabilityResult(_SO):
    unit_verdicts: dict[str, str] = Field(default_factory=dict)
    supplements: list[SupplementQuestion] = Field(default_factory=list)

    def queries(self) -> list[str]:
        out: list[str] = []
        for s in self.supplements:
            out.extend(s.search_queries or [s.question])
        return list(dict.fromkeys(q.strip() for q in out if q.strip()))


def _prepass(table: ClaimTable) -> list[SupplementQuestion]:
    """코드 프리패스 — LLM 없이 확정 가능한 부족분을 쿼리로 직결."""
    out: list[SupplementQuestion] = []
    seen: set[str] = set()
    # 커버리지 구멍 (required·obtainable)
    for ce in table.coverage:
        if ce.status != "uncovered" or not ce.slot.required \
                or ce.slot.obtainability == "unavailable":
            continue
        q = f"{ce.slot.entity} {ce.slot.metric} {ce.slot.period}".strip()
        if q and q not in seen:
            seen.add(q)
            out.append(SupplementQuestion(
                question=f"{q} 확인", search_queries=[q]))
    # DA-DA 불일치 → 공식 수치 재검색 직결 (P1-4)
    for d in table.da_disagreements:
        entity, metric, *_ = (d.claim_key.split("|") + ["", ""])[:3]
        q = f"{entity} {metric} 최신 공식 수치".strip()
        if entity and q not in seen:
            seen.add(q)
            out.append(SupplementQuestion(
                question=f"{entity} {metric} — 두 모델 기억이 불일치, 공식 수치 확인",
                search_queries=[q]))
    return out[:_MAX_PREPASS]


def _render_state(plan: PlanPacket, table: ClaimTable, ra: RaPacket) -> str:
    parts = [f"[기준시점] {plan.knowledge_cutoff}"]
    parts.append("[유닛(질문) 목록]\n" + "\n".join(
        f"- {uid}: {q}" for uid, q in plan.units()))
    by_unit: dict[str, list[str]] = {}
    for c in table.claims:
        by_unit.setdefault(c.unit_id, []).append(f"  · ({c.source}) {c.text[:100]}")
    ev = []
    for uid, lines in by_unit.items():
        ev.append(f"[{uid} 확보 주장 {len(lines)}건]\n" + "\n".join(lines[:8]))
    parts.extend(ev)
    if table.typed_facts:
        parts.append("[결정적 수치]\n" + "\n".join(
            f"- {f.label}: {f.value} {f.unit}" for f in table.typed_facts[:10]))
    titles = [n.title for items in ra.curated_items().values() for n in items[:5]]
    if titles:
        parts.append("[확보 뉴스]\n" + "\n".join(f"- {t}" for t in titles[:15]))
    return "\n\n".join(parts)[:10000]


async def run_answerability(plan: PlanPacket, table: ClaimTable, ra: RaPacket,
                            overrides: dict | None = None, *,
                            calc_missing: list[dict] | None = None,
                            ) -> AnswerabilityResult:
    prepass = _prepass(table)
    # CALC missing_inputs 합류 (P3-3) — "공식은 매칭됐는데 입력 수치가 없다"를 표적 검색.
    # 엔티티 없으면 스킵 — "2025년 연간 주당배당금" 단독 검색은 무의미한 라운드 소모 (2차 리뷰 #6)
    entity = plan.tickers[0].name if plan.tickers else ""
    if entity:
        seen_pp = {s.question for s in prepass}
        for m in (calc_missing or [])[:2]:
            needed = str(m.get("needed", "")).strip()
            if not needed:
                continue
            q = f"{entity} {needed}".strip()
            if q not in seen_pp:
                seen_pp.add(q)
                prepass.append(SupplementQuestion(
                    question=q, search_queries=[q]))
    verdicts: dict[str, str] = {}

    llm_supp: list[SupplementQuestion] = []
    try:
        role = Role("extract", overrides)
        val: _AnsLLM = await role.run(
            _render_state(plan, table, ra),
            "각 유닛에 대해 현재 확보된 증거만으로 답변 가능한지 판정하라 "
            "(answerable | partial | unanswerable).\n"
            "partial/unanswerable 유닛에는 '무엇이 부족한지'를 겨냥한 보완질문을 만들어라.\n"
            "- 원질문 재서술 금지. 부족한 사실 하나를 특정하라 "
            "(예: '2026 Q1 카카오 영업이익 컨센서스').\n"
            "- [결정적 수치]·[확보 주장]에 이미 있는 사실은 부족분이 아니다 — 다시 요구하지 마라.\n"
            "- 확실히 답에 필요한 부족분만. 없으면 보완질문 0개가 정답이다.\n"
            "- search_queries는 한국어 뉴스 검색어 1~2개.\n"
            f"- 보완질문 최대 {_MAX_SUPPLEMENTS}개, 가장 결정적인 것부터.",
            response_format=_AnsLLM,
        )
        unit_ids = {uid for uid, _ in plan.units()}
        valid = {"answerable", "partial", "unanswerable"}
        for uv in val.unit_verdicts:
            if uv.unit_id in unit_ids:
                verdicts[uv.unit_id] = uv.verdict if uv.verdict in valid else "partial"
        llm_supp = [s for s in val.supplements if s.question.strip()][:_MAX_SUPPLEMENTS]
    except Exception:
        pass  # mini 다운 — 프리패스 결과만으로 동작

    # 프리패스가 구멍을 찾은 유닛은 answerable로 남을 수 없다 (코드가 최종 권위)
    if prepass:
        verdicts["q0"] = "partial" if verdicts.get("q0", "partial") != "unanswerable" \
            else "unanswerable"

    # 프리패스 우선 + 중복 질문 제거
    seen_q = {s.question for s in prepass}
    merged = prepass + [s for s in llm_supp if s.question not in seen_q]
    return AnswerabilityResult(unit_verdicts=verdicts, supplements=merged)
