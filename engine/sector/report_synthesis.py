"""심화(규칙·과거사례 대조 논증, CLI) + 합성(claims만 — 결론은 report_assemble 코드가).

LLM은 ID/수치 '선언'만 하고 코드가 hydrate·검증·as_of 파생(날조 차단, 스펙 v3).
과거사례(cases)는 casemem 질의 결과(CaseMatch dump) — 실존 episode_id로만
precedent_grounded=True (Plan4-c)."""
from __future__ import annotations

import time

from pydantic import BaseModel

import re as _re

from sector.report_contracts import (
    Anchor, NumericFact, ReportClaim, StageIO, StageResult,
)

_NUM = _re.compile(r"(\d+(?:[.,]\d+)?)")


# (제거됨 2026-07-23) _auto_declare — 본문 수치를 크기만으로 anchor에 자동 연결하던
# 보강 장치. 사실성 감사 6.2 실측: 회사·지표·기간·부호가 달라도 연결돼(메모리 주장에
# LLM 토큰 단가 anchor 귀속) numeric_facts가 출처 귀속 증거로 무너짐. 미선언 수치는
# 이제 검증기의 A1 경고 + 확신도 상한 경로로만 처리한다(정책 v2 원형 복원).


class _ClaimRow(BaseModel):
    title: str
    trigger: str = ""
    mechanism: str = ""
    confidence: str = "낮"
    counter: str = ""
    stance: str = ""
    watch_signals: list[str] = []       # 관찰 선행 신호 + 현재 상태
    load_bearing: bool = False
    evidence_ids: list[str] = []
    anchor_refs: list[str] = []
    numeric_facts: list[NumericFact] = []   # typed 강제 — CLI json-schema가 형태를
                                            # 구속해 id/unit/delta 등 자유 키 방지(감사 6.2)
    precedent: str = ""
    precedent_case_ids: list[str] = []  # casemem episode_id 선언 — 코드가 실존 검증
    matched_rules: list[str] = []


class _ClaimsOut(BaseModel):
    claims: list[_ClaimRow]


def _fmt_anchor(a: Anchor) -> str:
    # 비교 종류·직전값을 코드가 명시 — "Δ-35.8%"만 주면 LLM이 YoY로 추측 표기한
    # 확정 오류의 재발 차단(감사 4.1/4.2). 인용 시 이 라벨 그대로 쓰게 한다.
    d = ""
    if a.delta_pct is not None:
        kind = a.comparison_kind or "직전 관측 대비"
        prev = f", 직전 {a.prev_period}={a.prev_value}" if a.prev_period else ""
        d = f" (Δ{a.delta_pct:+.1f}% {kind}{prev})"
    return f"{a.anchor_id}: {a.value}{a.unit}{d} @{a.as_of} [{a.source}]"


def _fmt_rule(r: dict) -> str:
    return f"{r['slug']} (score {r['score']}, 키 {r['matched_keys']}): {r['connection']}"


def _fmt_case(c: dict) -> str:
    ev = " / ".join(f"{e.get('source', '')}: {e.get('quote', '')}"
                    for e in (c.get("evidence") or [])[:3])
    nxt = ", ".join(c.get("next_phase_labels") or []) or "?"
    return (f"{c.get('episode_id')} (국면 {c.get('matched_phase_order')}, "
            f"score {c.get('score')}) → 다음 국면 예측: {nxt}"
            + (f" · 근거: {ev}" if ev else ""))


async def deepen(clusters, rules, anchors, *, role,
                 cases: list[dict] | None = None) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="deepen", label="심화 — 규칙·과거사례 대조", in_count=len(clusters))
    cases = cases or []
    try:
        parts = ["[관측 이벤트 — 근거 발췌 포함]"]
        for c in clusters:
            parts.append(f"- {c.title} ({c.axis}/{c.direction}, 출처 {len(c.members)}건)")
            for m in c.members[:4]:
                ex = f": {m.excerpt[:160]}" if m.excerpt else ""
                parts.append(f"    · [{m.id}] {m.title}{ex}")
        parts.append("\n[수치 anchor — 인용만, 산술 금지]")
        parts += [_fmt_anchor(a) for a in anchors]
        parts.append("\n[매칭 규칙 — 절차 참고용, 사실 인용 금지]")
        parts += [_fmt_rule(r) for r in rules]
        if cases:
            parts.append(
                "\n[과거사례 — 국면 위치 판정과 양방향 대조를 요구한다]\n"
                "· 현재 관측이 어느 에피소드의 몇 번째 국면과 가장 유사한지 판정하고 근거를 대라.\n"
                "· 지지 사례만 고르지 마라 — 반대 방향 에피소드(예: 업사이클 주장이면 과거 "
                "고점 붕괴 국면)와도 대조해 '이번이 다른 이유'를 수치로 설명하거나, 못 하면 "
                "그 리스크를 정직한 단서로 남겨라.\n"
                "· 매칭 국면의 '다음 국면 전이 조건'을 관찰 신호(watch_signals)로 변환하라.")
            parts += [_fmt_case(c) for c in cases]
        parts.append(
            "\n[논증 요구 — 벤치마크: 공대인 스타일]\n"
            "1. 나이브 단정(\"AI 핫→반도체 좋다\") 기각. 지배 방정식을 먼저 세워라 "
            "(예: 수급 갭 = 비트 수요 증가율 − 비트 공급 증가율; 이익 = 출하 × ASP − 비용).\n"
            "2. 단위 정합: 매출로 가격을 논하는 순환논리 금지 — 가격·물량(비트)·웨이퍼·CapEx를 분해.\n"
            "3. 비대칭 인식: 공급은 계산 가능(CapEx 리드타임 1.5~2년), 수요는 추정 — "
            "공급을 고정하고 수요가 넘어야 할 문턱(손익분기)을 역산하라.\n"
            "4. 모든 수치에 〔근거: 출처〕 또는 〔가정〕 라벨을 붙여 구분하라.\n"
            "5. 재무 귀결: 관측이 매출·마진·계약구조(장기계약 floor·선지급)·밸류에이션에 "
            "어떻게 꽂히는지 끝까지 계산하라 (매출 증가율 ≈ (1+물량)×(1+ASP)−1).\n"
            "6. 정직한 단서: 논증이 틀릴 조건을 본문에 내장하라.\n"
            "7. 예측 대신 관찰: 결론을 가르는 선행 신호와 그 현재 상태를 명시하라.")
        text = await role.run("\n".join(parts),
                              instructions="메모리 반도체 시황 분석가. 숫자로 끝까지 따진다.",
                              effort="high")
        io.out_count = 1
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=str(text), io=io, error=None)
    except Exception as exc:  # noqa: BLE001
        io.note = f"심화 실패: {exc}"
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output="", io=io, error=str(exc))


def _hydrate(ids: list[str], pool: dict, io: StageIO) -> list:
    out = []
    for i in ids:
        if i in pool:
            out.append(pool[i])
        else:
            io.dropped.append({"title": i, "reason": "미존재 evidence id(날조 의심)"})
    return out


async def synthesize_claims(deepen_text, clusters, anchors, rules, *, role,
                            cases: list[dict] | None = None) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="synth", label="합성 — 주장", in_count=len(clusters))
    cases = cases or []
    try:
        pool = {m.id: m for c in clusters for m in c.members}
        anchor_ids = {a.anchor_id for a in anchors}
        case_ids = {str(c.get("episode_id")) for c in cases if c.get("episode_id")}
        ev_lines = [f"- {i}: {m.title}" + (f" — {m.excerpt[:120]}" if m.excerpt else "")
                    for i, m in sorted(pool.items())]
        anchor_lines = [_fmt_anchor(a) for a in anchors]
        prompt = (f"[논증]\n{deepen_text}\n\n[근거 풀 — id: 제목/발췌]\n"
                  + "\n".join(ev_lines)
                  + "\n[anchor 풀]\n" + "\n".join(anchor_lines)
                  + f"\n[과거사례 id 풀]\n{sorted(case_ids)}\n\n"
                  "주장 카드는 **최대 2개** — 가장 설득력 있는 것만(종합/최종의견 금지). "
                  "각 주장은 벤치마크 구조를 갖춰라:\n"
                  "· mechanism: 지배 방정식→분해→손익분기 역산→재무 귀결(매출≈(1+물량)×(1+ASP)−1, "
                  "마진·계약구조)까지의 인과 사슬. 모든 수치에 〔근거〕/〔가정〕 라벨.\n"
                  "· counter: 이 주장이 틀릴 조건(정직한 단서).\n"
                  "· watch_signals: 결론을 가르는 관찰 가능한 선행 신호 2~4개, 각각 현재 상태 포함 "
                  "(예: '유통 재고 8주 초과 시 경계 — 현재 2~4주로 바닥').\n"
                  "evidence_ids는 그 주장을 실제로 지지하는 근거만, "
                  "anchor_refs/numeric_facts/precedent_case_ids는 반드시 위 풀의 id만. "
                  "anchor 수치를 본문에 쓰면 반드시 numeric_facts로 선언하라 — 선언 없는 "
                  "수치는 검증에서 경고·확신도 상한이 붙는다. 증감률을 인용할 땐 anchor에 "
                  "적힌 비교 종류(MoM/QoQ/YoY)를 **그대로** 표기하라 — 다른 종류로 바꿔 "
                  "말하지 마라.")
        res = await role.run(prompt, instructions="주장 합성기.",
                             response_format=_ClaimsOut, effort="high")
        claims: list[ReportClaim] = []
        for i, r in enumerate(res.claims):
            refs = _hydrate(r.evidence_ids, pool, io)
            # 숫자 선언은 전부 보존 — 미존재 anchor_id도 검증(T8)이 reject하도록
            # 여기서 거르지 않는다(거르면 reject 분기가 죽음 — codex plan r2 NB3)
            # fuzzy 자동 선언(_auto_declare)은 제거 — 감사 6.2(무관 anchor 귀속)
            nf = list(r.numeric_facts)
            valid_cases = []
            for cid in r.precedent_case_ids:
                if cid in case_ids:
                    valid_cases.append(cid)
                else:
                    io.dropped.append({"title": cid, "reason": "미존재 case id(날조 의심)"})
            claims.append(ReportClaim(
                claim_id=f"c{i}", title=r.title, trigger=r.trigger, mechanism=r.mechanism,
                confidence=r.confidence if r.confidence in ("낮", "중", "높") else "낮",
                counter=r.counter, stance=r.stance, load_bearing=r.load_bearing,
                evidence_refs=refs,
                evidence=[f"{e.title} ({e.source})" if e.source else e.title for e in refs],
                anchor_refs=[a for a in r.anchor_refs if a in anchor_ids],
                numeric_facts=nf,
                precedent=r.precedent,
                precedent_grounded=bool(valid_cases),      # 실존 case로만 접지(날조 금지)
                precedent_case_ids=valid_cases,
                matched_rules=r.matched_rules,
                watch_signals=r.watch_signals, status="unverified",
                as_of=max((e.ts for e in refs if e.ts), default="")))   # 코드 파생
        io.out_count = len(claims)
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=claims, io=io, error=None)
    except Exception as exc:  # noqa: BLE001
        io.note = f"합성 실패: {exc}"
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=[], io=io, error=str(exc))


async def revise_claims(claims, verdicts, clusters, anchors, rules, *, role,
                        cases: list[dict] | None = None) -> StageResult:
    """REFLECT 라운드 — A1/A2 반증을 되먹여 주장을 수정(흡수·한정·강화).

    벤치마크의 '정직한 단서' 원리: 반증을 피하지 말고 본문에 내장해 좁힌다.
    수정 후에도 재검증(verify)을 다시 통과해야 결론에 반영된다."""
    t0 = time.monotonic()
    io = StageIO(key="revise", label="수정 — 반증 흡수", in_count=len(claims))
    cases = cases or []
    vmap = {v.claim_id: v for v in verdicts}
    targets = [c for c in claims
               if vmap.get(c.claim_id) and vmap[c.claim_id].status == "unverified"
               and vmap[c.claim_id].reasons]
    if not targets:
        io.out_count = len(claims)
        return StageResult(output=claims, io=io, error=None)
    try:
        blocks = []
        for c in targets:
            v = vmap[c.claim_id]
            blocks.append(f"[{c.claim_id}] {c.title}\n논증: {c.mechanism}\n"
                          f"스탠스: {c.stance}\n반증(검증 게이트): " + " / ".join(v.reasons))
        pool = {m.id: m for cl in clusters for m in cl.members}
        anchor_ids = {a.anchor_id for a in anchors}
        case_ids = {str(c.get("episode_id")) for c in cases if c.get("episode_id")}
        prompt = ("아래 주장들이 교차 검증에서 반증당했다. 반증을 회피하지 말고 흡수하라 — "
                  "① 반증이 옳으면 주장을 좁히거나 조건부로 한정하고 그 한계를 본문에 명시 "
                  "② 반증이 과하면 수치로 재반박 ③ 못 지키는 주장은 버려라(더 적어도 된다).\n\n"
                  + "\n\n".join(blocks)
                  + f"\n\n[근거 id 풀]\n{sorted(pool)}\n[anchor 풀]\n"
                  + "\n".join(_fmt_anchor(a) for a in anchors)
                  + f"\n[과거사례 id 풀]\n{sorted(case_ids)}\n\n"
                  "수정된 주장 카드만 출력(최대 2개). 기존 규칙: 수치 라벨〔근거〕/〔가정〕, "
                  "재무 귀결, watch_signals, evidence_ids/anchor_refs/numeric_facts는 풀의 id만.")
        res = await role.run(prompt, instructions="주장 수정기 — 반증 흡수.",
                             response_format=_ClaimsOut, effort="high")
        revised: list[ReportClaim] = []
        for i, r in enumerate(res.claims[:2]):
            refs = _hydrate(r.evidence_ids, pool, io)
            nf = list(r.numeric_facts)     # typed 스키마 강제 — fuzzy 자동 선언 제거(감사 6.2)
            valid_cases = [cid for cid in r.precedent_case_ids if cid in case_ids]
            revised.append(ReportClaim(
                claim_id=f"r{i}", title=r.title, trigger=r.trigger, mechanism=r.mechanism,
                confidence=r.confidence if r.confidence in ("낮", "중", "높") else "낮",
                counter=r.counter, stance=r.stance, load_bearing=r.load_bearing,
                evidence_refs=refs,
                evidence=[f"{e.title} ({e.source})" if e.source else e.title for e in refs],
                anchor_refs=[a for a in r.anchor_refs if a in anchor_ids],
                numeric_facts=nf, precedent=r.precedent,
                precedent_grounded=bool(valid_cases), precedent_case_ids=valid_cases,
                matched_rules=r.matched_rules, watch_signals=r.watch_signals,
                status="unverified",
                as_of=max((e.ts for e in refs if e.ts), default="")))
        kept = [c for c in claims if c not in targets]
        io.out_count = len(kept) + len(revised)
        io.note = f"반증 흡수 수정 {len(targets)}→{len(revised)}건"
        return StageResult(output=kept + revised, io=io, error=None)
    except Exception as exc:  # noqa: BLE001 — 수정 실패 시 원본 유지(never-raise)
        io.note = f"수정 실패: {exc}"
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=claims, io=io, error=str(exc))
