"""테제(Thesis) 구조 guard — 결정적(deterministic) 근거 검증 (2부 T3).

LLM이 만들어내는 Statement/Evidence/KeyMetric은 여기를 통과해야만 신뢰된다.
핵심 원칙(B4): publisher_id·canonical_url 등은 절대 LLM/입력값을 그대로 믿지
않고 항상 카드(SectorCard) 원본에서 재파생한다 — 이 모듈이 그 단일 진입점.
"""
from __future__ import annotations

import ipaddress
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

from publicsuffix2 import PublicSuffixList

from sector.contracts import MetricObservation, SectorCard
from sector.metrics_registry import METRIC_REGISTRY, _GROUP_KEYS
from sector.thesis_contracts import Evidence, KeyMetric, Statement, observation_id

_PSL = PublicSuffixList()  # 오프라인 번들 PSL 데이터 사용 — import 시점에 네트워크 없음

_AUTO_PRESERVE_MARKER = "(자동 보존)"

# ---- publisher_id ----------------------------------------------------------


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def publisher_id(url: str) -> str:
    """URL의 registrable domain(eTLD+1)을 오프라인 PSL로 계산한다.

    IP 호스트·단일 라벨(localhost)·public-suffix-only host(co.kr)는 전부
    무효로 보고 ""를 반환한다 (r2-B4).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https"):
        return ""
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return ""
    if _is_ip(host):
        return ""
    if "." not in host:                       # 단일 라벨 (localhost)
        return ""
    try:
        # host 자체가 순수 public suffix(예: co.kr)인지 판별: 합성 라벨을 붙여
        # get_sld가 전체(합성라벨+host)를 그대로 반환하면 host가 통째로 suffix.
        probe = "zz9k-guard." + host
        if _PSL.get_sld(probe) == probe:
            return ""
        sld = _PSL.get_sld(host)
    except Exception:  # noqa: BLE001 — PSL 파싱 실패는 무효로 취급
        return ""
    if not sld or "." not in sld:
        return ""
    return sld


# ---- quantity_literal -------------------------------------------------------

# 순서 무관 — banned quantity idiom들을 각각 특정해 오탐(제품명 숫자)을 피한다.
_QUANTITY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\d+(?:\.\d+)?\s*(?:%|퍼센트)"),
    re.compile(r"[$₩]\s*\d+(?:\.\d+)?"),
    re.compile(r"\bUSD\s*\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\d+(?:\.\d+)?\s*USD\b", re.IGNORECASE),
    re.compile(r"\d+(?:\.\d+)?\s*(?:달러|원|엔|위안)"),
    re.compile(r"\d+(?:\.\d+)?\s*(?:조|억|만)\b"),
    re.compile(r"\d+(?:\.\d+)?\s*bp\b", re.IGNORECASE),
    # 독립 숫자 — 앞뒤로 문자/자릿점/통화기호/하이픈이 붙어 있지 않은 경우만.
    # gpt-5.5(하이픈 결합)·HBM3E/DDR5/H100(문자 뒤 결합)은 여기서 자동 제외.
    re.compile(r"(?<![A-Za-z0-9.$₩-])\d+(?:\.\d+)?(?![A-Za-z0-9])"),
]


def quantity_literal(text: str) -> list[str]:
    """text에서 발견된 금지 수량 literal 목록(중복 제거). 빈 리스트 = 클린."""
    found: list[str] = []
    seen: set[str] = set()
    for pat in _QUANTITY_PATTERNS:
        for m in pat.finditer(text or ""):
            s = m.group(0)
            if s not in seen:
                seen.add(s)
                found.append(s)
    return found


# ---- card 적격성 / quote 검증 ------------------------------------------------


def eligible_card(card: SectorCard) -> bool:
    """부적격 카드 제외: quote 없음·D등급·자동보존 마커."""
    if not (card.raw_quote or "").strip():
        return False
    if card.source_grade == "D":
        return False
    if _AUTO_PRESERVE_MARKER in (card.interpreted_signal or ""):
        return False
    return True


def quote_valid(card: SectorCard, quote: str) -> bool:
    q = (quote or "").strip()
    if not q:
        return False
    return q in (card.raw_quote or "") or q in (card.title or "")


def _canonical_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    return url


def build_evidence(card: SectorCard, quote: str) -> Evidence | None:
    """카드에서 전부 재파생 — LLM/입력의 publisher·url을 신뢰하지 않는 단일 진입점 (B4)."""
    if not eligible_card(card):
        return None
    if not quote_valid(card, quote):
        return None
    canonical_url = _canonical_url(card.url)
    if canonical_url is None:
        return None
    pub = publisher_id(card.url)
    if not pub:
        return None
    return Evidence(card_id=card.id, canonical_url=canonical_url,
                    publisher_id=pub, quote=quote.strip())


# ---- 독립성 -------------------------------------------------------------


_PUNCT_RE = re.compile(r"[\s\W]+", re.UNICODE)


def _normalize_quote(q: str) -> str:
    return _PUNCT_RE.sub("", q or "")


def independent_publishers(evs: list[Evidence], cards: dict) -> int:
    """distinct publisher 수 — quote 정규화 SequenceMatcher>=0.8인 쌍은 동일 주체로 병합(전재)."""
    # 각 evidence를 (publisher_id, normalized_quote) 항목으로 모으고,
    # 유사도 0.8 이상인 항목끼리 union-find로 병합한 뒤 그룹 대표의 publisher만 센다.
    items = [(ev.publisher_id, _normalize_quote(ev.quote)) for ev in evs]
    n = len(items)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if items[i][0] == items[j][0]:
                continue  # 동일 publisher는 애초에 병합 대상 아님(별개 계산 불필요)
            ratio = SequenceMatcher(None, items[i][1], items[j][1]).ratio()
            if ratio >= 0.8:
                union(i, j)

    groups: dict[int, set[str]] = {}
    for idx, (pub, _q) in enumerate(items):
        groups.setdefault(find(idx), set()).add(pub)

    # 그룹마다 대표 publisher 1개만 카운트(전재 병합) — 그룹 내 publisher가
    # 여럿이면 그 중 하나만 대표로 취급.
    distinct: set[str] = set()
    for pubs in groups.values():
        distinct.add(sorted(pubs)[0])
    return len(distinct)


# ---- filter_statements ------------------------------------------------------


def filter_statements(stmts: list[Statement], cards: dict) -> tuple[list[Statement], list[str]]:
    kept: list[Statement] = []
    dropped: list[str] = []
    for st in stmts:
        rebuilt: list[Evidence] = []
        for ev in st.supporting:
            card = cards.get(ev.card_id)
            if card is None or not eligible_card(card):
                continue
            rev = build_evidence(card, ev.quote)
            if rev is not None:
                rebuilt.append(rev)
        if len(rebuilt) < 2:
            dropped.append(f"{st.statement_id}: 재구성된 supporting evidence {len(rebuilt)}개 (<2)")
            continue
        indep = independent_publishers(rebuilt, cards)
        if indep < 2:
            dropped.append(f"{st.statement_id}: 독립 publisher {indep}개 (<2)")
            continue
        lits = quantity_literal(st.text)
        if lits:
            dropped.append(f"{st.statement_id}: 금지 수량 literal 포함 {lits}")
            continue
        kept.append(st)
    return kept, dropped


# ---- resolve_key_metrics ----------------------------------------------------


def _group_key(meta: dict) -> str:
    for k in _GROUP_KEYS:
        v = meta.get(k)
        if v:
            return str(v)
    return ""


def resolve_key_metrics(names: list[str], seed: dict, store) -> tuple[list[KeyMetric], list[str]]:
    """seed의 required_inputs에서 각 metric의 meta_filter 그룹을 찾아 최신 관측을 KeyMetric으로."""
    by_metric: dict[str, dict] = {ri["metric"]: ri for ri in seed.get("required_inputs", [])}
    kms: list[KeyMetric] = []
    dropped: list[str] = []
    for name in names:
        if name not in METRIC_REGISTRY or name not in by_metric:
            dropped.append(name)
            continue
        ri = by_metric[name]
        meta_filter = ri.get("meta_filter", {}) or {}
        rows: list[MetricObservation] = store.read_metric(name, last_n=1_000_000)
        matching = [o for o in rows
                   if all(o.meta.get(k) == v for k, v in meta_filter.items())]
        if not matching:
            dropped.append(name)
            continue
        groups: dict[str, list[MetricObservation]] = {}
        for o in matching:
            groups.setdefault(_group_key(o.meta), []).append(o)
        if len(groups) != 1:
            # 다중 서브시리즈(예: hyperscaler_capex의 MSFT/META)가 meta_filter로
            # 하나로 좁혀지지 않으면 어느 쪽이 "최신"인지 임의로 고를 수 없다 —
            # fail-closed: 모호하면 절대 조용히 아무 서브시리즈나 반환하지 않는다.
            dropped.append(name)
            continue
        latest = max(matching, key=lambda o: o.ts)
        source = latest.source or METRIC_REGISTRY[name]["desc"]  # provenance 부재 관측의 표시용
        kms.append(KeyMetric(
            metric=name,
            observation_id=observation_id(name, latest.ts, latest.meta),
            value=latest.value, unit=latest.unit, ts=latest.ts,
            meta=latest.meta, source=source))
    return kms, dropped
