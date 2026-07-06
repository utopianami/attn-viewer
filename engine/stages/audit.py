"""AUDITOR 스테이지 — 최종 텍스트 게이트 (설계 §⑧, 2차 리뷰 확장판).

① 숫자: 답변의 숫자를 코드(regex)로 추출 → ClaimTable/CALC/typed_facts 대조.
   매칭 없는 신규 숫자 = unsupported → "[확인되지 않은 수치]" 인라인 라벨
② G4 지시어 최종 텍스트 재검사 → 자동 완곡화 + directive_hits[] 노출
③ 신규 엔티티·사건 서술 플래그 (5.5-mini 추출 — 감사 독립성: GPT 계열 고정)

GPT 다운 시 ③만 skip 표기 (①②는 순수 코드라 항상 수행).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from contracts import AuditIssue, AuditReport, CalcResult, ClaimTable, VerdictPacket
from providers import Role

# 숫자 추출 — %, 원, 배, bps, 조/억 단위 등 금융 수치 (연도·q번호·목차는 제외)
_NUM_RE = re.compile(
    r"(?<![\w.])([+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[+-]?\d+\.\d+|[+-]?\d+)\s*(%|%p|퍼센트|bps|배|원|조|억|만원|달러|\$)"
)
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")

_DIRECTIVE_RE = re.compile(
    r"(매수하세요|매도하세요|사세요|파세요|팔아라|지금 사(라|세요)?|지금 팔(아라|어라)?|"
    r"전량 매도|전량 매수|풀매수|무조건 (사|팔))"
)
# 자동 완곡화 매핑 — 지시 → 판단 기준 서술
_SOFTEN = [
    (re.compile(r"매수하세요|사세요"), "매수를 고려할 수 있는 조건입니다"),
    (re.compile(r"매도하세요|파세요|팔아라"), "매도를 고려할 수 있는 조건입니다"),
    (re.compile(r"전량 (매도|매수)"), r"\1 비중 조절 검토 대상"),
]

_REL_TOL = 0.02  # 답변 숫자 ↔ 근거 숫자 2% 이내 = 지지


class _SO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _NewFacts(_SO):
    entities: list[str] = Field(default_factory=list)   # 답변에만 있는 회사·기관·사건


class _Entail(_SO):
    idx: int
    verdict: str = "neutral"     # entail | neutral | contradict
    reason: str = ""


class _Entails(_SO):
    judgements: list[_Entail] = Field(default_factory=list)


# markdown 인용 링크 — [(문장, URL)] 쌍 추출용 (P5)
_MD_LINK_RE = re.compile(r"\[([^\]]{1,120})\]\((https?://[^)\s]+)\)")
_MAX_ENTAIL_PAIRS = 8


def _citation_pairs(answer_md: str, evidence_docs: dict[str, str]) -> list[tuple[str, str, int]]:
    """답변의 (인용 문장, 근거 원문, 링크 끝 오프셋). 근거 원문이 있는 URL만."""
    pairs = []
    for m in _MD_LINK_RE.finditer(answer_md):
        url = m.group(2)
        doc = evidence_docs.get(url)
        if not doc:
            continue
        # 인용 문장 = 링크가 붙은 문장 (직전 경계 ~ 링크 끝)
        seg_start = max(answer_md.rfind("\n", 0, m.start()),
                        answer_md.rfind(". ", 0, m.start()),
                        answer_md.rfind("다.", 0, m.start()))
        sentence = answer_md[seg_start + 1:m.end()].strip()[-400:]
        # 앞선 숫자 감사가 끼워 넣은 라벨 제거 — 판정 편향 방지 (2차 리뷰 #8)
        sentence = sentence.replace("[확인되지 않은 수치]", "")
        if sentence:
            pairs.append((sentence, doc[:1500], m.end()))
    return pairs[:_MAX_ENTAIL_PAIRS]


# 한국어 배수 단위 스케일 — "30만원"=300,000원, "113조"=1.13e14 (미적용 시 30 vs 304,000 오탐)
_UNIT_SCALE = {"만원": 1e4, "억": 1e8, "조": 1e12, "억원": 1e8, "조원": 1e12}

# 복합 수사 "1조 9,421억원" — 단순 regex가 "1조"+"9,421억"으로 쪼개면 앵커(1.9421e12)와 불일치 오탐
_COMPOSITE_RE = re.compile(r"([\d,]+)\s*조\s*([\d,]+)\s*억")


def _composites(text: str) -> list[tuple[float, tuple[int, int]]]:
    """복합 수사 → (합산값, 원문 span). span은 내부 단순 매치 스킵용."""
    out = []
    for m in _COMPOSITE_RE.finditer(text):
        try:
            v = float(m.group(1).replace(",", "")) * 1e12 \
                + float(m.group(2).replace(",", "")) * 1e8
        except ValueError:
            continue
        out.append((v, m.span()))
    return out


def _anchor_values(table: ClaimTable, calc_results: list[CalcResult],
                   verdict: VerdictPacket | None = None) -> list[float]:
    vals: list[float] = [f.value for f in table.typed_facts]
    # 검증 탈락 claim의 숫자는 앵커 자격 없음 — rejected/unverified 수치가 감사를 통과하는 구멍 차단 (codex #17)
    bad_ids: set[str] = set()
    if verdict is not None:
        bad_ids = {v.claim_id for v in verdict.verdicts if v.final != "verified"}
    for c in table.claims:
        if c.norm.value is not None and c.id not in bad_ids:
            # claim value를 단위 스케일로 정규화 ("4411 억원" → 4.411e11 — 답변 숫자와 동일 좌표계)
            vals.append(c.norm.value * _UNIT_SCALE.get(c.norm.unit.strip().lower(), 1.0))
    for r in calc_results:
        if r.ok and r.result and r.result.get("result"):
            v = r.result["result"].get("value")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append(float(v))
    # 매크로 지표 (코스피 지수·등락률 등) — 합성이 인용 가능한 결정적 수치
    macro = (table.global_context or {}).get("macro") or {}
    for v in macro.values():
        if isinstance(v, dict):
            for key in ("last", "day_pct"):
                x = v.get(key)
                if isinstance(x, (int, float)) and not isinstance(x, bool):
                    vals.append(float(x))
    return vals


def _evidence_numbers(texts: list[str]) -> list[float]:
    """수집 근거 텍스트(뉴스 본문·검색 서사)의 숫자 → 앵커 (P1 이후 본문이 합성에 유입).

    근거에 실재하는 숫자를 '확인되지 않은 수치'로 오탐하지 않기 위함 —
    감사의 정의는 '답변 숫자를 근거와 대조'이고, 본문도 근거다 (2026-07-03 E2E 오탐 8/18).
    """
    vals: list[float] = []
    for t in texts:
        vals.extend(v for v, _ in _composites(t or ""))
        for m in _NUM_RE.finditer(t or ""):
            raw, unit = m.group(1), m.group(2)
            if _YEAR_RE.match(raw.replace(",", "")):
                continue
            try:
                vals.append(float(raw.replace(",", "")) * _UNIT_SCALE.get(unit, 1.0))
            except ValueError:
                continue
    return vals[:400]


def _supported(value: float, anchors: list[float], half_step: float = 0.0) -> bool:
    """half_step: 반올림 허용 오차 — "PER 23배"(정수 표기)는 앵커 23.48의 반올림.

    상대 2%만으론 23 vs 23.48(2.04%)이 오탐 (2026-07-03 E2E). 표기 정밀도의
    절반(0.5×10^-소수자릿수 × 단위 스케일)까지는 같은 수로 본다.
    """
    for a in anchors:
        base = max(abs(a), abs(value))
        if base == 0 or abs(a - value) / base <= _REL_TOL \
                or abs(a - value) <= half_step:
            return True
        # 부호 무시 매칭 (하락률 표기 차이)
        if abs(abs(a) - abs(value)) / base <= _REL_TOL \
                or abs(abs(a) - abs(value)) <= half_step:
            return True
    return False


async def run_audit(answer_md: str, table: ClaimTable, calc_results: list[CalcResult],
                    *, verdict: VerdictPacket | None = None,
                    evidence_texts: list[str] | None = None,
                    evidence_docs: dict[str, str] | None = None,
                    overrides: dict | None = None) -> tuple[AuditReport, str]:
    """최종 답변 텍스트 감사. 반환: (리포트, 라벨/완곡화 반영된 답변).

    evidence_texts: 수집 근거 원문 (뉴스 본문·요약·검색 서사) — 숫자 앵커에 포함.
    evidence_docs: url → 원문 — ④ 인용 entailment 판정용 (P5).
    """
    anchors = _anchor_values(table, calc_results, verdict)
    anchors += _evidence_numbers(evidence_texts or [])
    issues: list[AuditIssue] = []

    # ── ① 숫자 대조 (코드) — 모든 등장을 개별 검사, match 위치 기반 라벨 (오폭 방지, codex #15/#16)
    numeric_total = 0
    numeric_supported = 0
    label = "[확인되지 않은 수치]"
    inserts: list[int] = []          # 라벨 삽입 위치 (원문 오프셋)
    reported: set[str] = set()       # 리포트 dedup용 (라벨은 등장마다)

    def _check(value: float, token: str, start: int, end: int,
               half_step: float = 0.0) -> None:
        nonlocal numeric_total, numeric_supported
        numeric_total += 1
        if _supported(value, anchors, half_step):
            numeric_supported += 1
            return
        inserts.append(end)
        if token not in reported:
            reported.add(token)
            sent = answer_md[max(0, start - 40):end + 40].replace("\n", " ")
            issues.append(AuditIssue(
                kind="numeric_unsupported", sentence=f"…{sent}…",
                detail=f"{token} — ClaimTable/CALC 매칭 없음"))

    # 복합 수사("1조 9,421억원")는 합산값 하나로 검사, 내부 단순 매치는 스킵
    comp_spans: list[tuple[int, int]] = []
    for v, (s, e) in _composites(answer_md):
        comp_spans.append((s, e))
        _check(v, answer_md[s:e], s, e, half_step=0.5e8)  # 정밀도 = 억 단위
    for m in _NUM_RE.finditer(answer_md):
        if any(s <= m.start() < e for s, e in comp_spans):
            continue
        raw, unit = m.group(1), m.group(2)
        if _YEAR_RE.match(raw.replace(",", "")):
            continue
        try:
            scale = _UNIT_SCALE.get(unit, 1.0)
            value = float(raw.replace(",", "")) * scale
        except ValueError:
            continue
        decimals = len(raw.partition(".")[2])
        _check(value, raw + unit, m.start(), m.end(),
               half_step=0.5 * (10 ** -decimals) * scale)
    # 오프셋 뒤에서부터 삽입 (앞 삽입이 뒤 오프셋을 밀지 않도록)
    patched = answer_md
    for pos in sorted(inserts, reverse=True):
        patched = patched[:pos] + label + patched[pos:]

    # ── ② G4 지시어 재검사 + 완곡화 (코드)
    directive_hits = [m.group(0) for m in _DIRECTIVE_RE.finditer(patched)]
    if directive_hits:
        for pat, repl in _SOFTEN:
            patched = pat.sub(repl, patched)
        for hit in directive_hits:
            issues.append(AuditIssue(kind="directive", sentence=hit, detail="자동 완곡화 적용"))

    # ── ③ 신규 엔티티 플래그 (mini — 감사 독립성: GPT 계열)
    skipped = False
    try:
        known = ", ".join(sorted({c.norm.entity for c in table.claims if c.norm.entity}))[:2000]
        role = Role("audit", overrides)
        ctx = f"[답변]\n{answer_md[:6000]}\n\n[수집 근거에 등장한 엔티티]\n{known}"
        if evidence_texts:
            # 매체명+제목 목록 (문서 앞머리) — 제목에만 등장하는 기관의 오탐 방지.
            # 본문 블롭 주입은 금지: mini가 목록을 놓치고 주 엔티티까지 신규로 오판했다 (E2E 확인)
            heads = "\n".join(f"- {t[:120]}" for t in evidence_texts[1:16] if t.strip())
            if heads:
                ctx += f"\n\n[근거 문서 (매체·제목)]\n{heads}"
        val: _NewFacts = await role.run(
            ctx,
            "답변에는 등장하지만 수집 근거 엔티티 목록에 없는 회사·기관·구체적 사건명만 나열하라. "
            "일반 용어·지표명·언론사(매체명)는 제외. 없으면 빈 배열.",
            response_format=_NewFacts,
        )
        # 코드 필터 — mini가 매체·본문 실재 기관까지 나열하는 노이즈 (E2E: 하나증권·이투데이 등).
        # 근거 원문 어딘가에 문자열로 실재하면 '신규'가 아니다. 최종 권위는 코드.
        haystack = known + " " + " ".join(evidence_texts or [])
        for e in val.entities[:12]:
            if e and e not in haystack:
                issues.append(AuditIssue(kind="new_fact", sentence=e,
                                         detail="근거에 없는 신규 엔티티 — 확인 필요"))
    except Exception:
        skipped = True   # GPT 다운 — "숫자 감사"는 코드라 계속, 신규사실 감사만 skip

    # ── ④ 인용 entailment (P5, F1/AAR) — (문장, 인용 URL 원문) 쌍을 mini 배치 판정.
    #    contradict = 인라인 플래그 + 이슈, neutral = 리포트만. 실패는 조용히 skip (None 유지).
    provenance: float | None = None
    pairs = _citation_pairs(patched, evidence_docs or {})
    if pairs:
        try:
            view = "\n\n".join(
                f"[{i}] 인용 문장: {s}\n출처 원문: {doc}"
                for i, (s, doc, _) in enumerate(pairs))
            val_e: _Entails = await Role("audit", overrides).run(
                view[:14000],
                "각 항목의 '인용 문장'이 '출처 원문'으로 지지되는지 판정하라.\n"
                "- entail: 원문이 문장을 직접 지지\n"
                "- neutral: 원문에 근거가 없거나 부분적\n"
                "- contradict: 원문과 모순\n"
                "숫자·시점·주체가 다르면 contradict. idx는 항목 번호 그대로.",
                response_format=_Entails,
            )
            valid = {"entail", "neutral", "contradict"}
            verdicts_by_idx = {j.idx: j for j in val_e.judgements
                               if j.verdict in valid and 0 <= j.idx < len(pairs)}
            if verdicts_by_idx:
                n_entail = sum(1 for j in verdicts_by_idx.values() if j.verdict == "entail")
                provenance = round(n_entail / len(verdicts_by_idx), 3)
                # neutral은 이슈로 안 올림 — 비율(provenance)에만 반영 (스팸 방지, 스펙 원문)
                flag_offsets = []
                for i, (sent, _doc, end_off) in enumerate(pairs):
                    j = verdicts_by_idx.get(i)
                    if j is not None and j.verdict == "contradict":
                        flag_offsets.append(end_off)
                        issues.append(AuditIssue(
                            kind="citation_mismatch", sentence=sent[:150],
                            detail=f"인용 출처와 모순 — {j.reason[:120]}"))
                for pos in sorted(flag_offsets, reverse=True):
                    patched = patched[:pos] + "[인용 불일치]" + patched[pos:]
        except Exception:
            pass  # entailment 실패 — 다른 감사는 유지

    report = AuditReport(
        numeric_total=numeric_total,
        numeric_supported=numeric_supported,
        issues=issues,
        directive_hits=directive_hits,
        # citation_mismatch 이슈는 contradict만 생성되므로 kind 검사로 충분
        # (detail 부분문자열 검사는 LLM 사유문에 "모순" 포함 시 오폭 — 2차 리뷰 #7)
        severe=any(i.kind in ("numeric_unsupported", "citation_mismatch") for i in issues),
        skipped=skipped,
        provenance_soundness=provenance,
    )
    return report, patched
