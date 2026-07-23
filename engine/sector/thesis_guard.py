"""테제(Thesis) 구조 guard — 결정적(deterministic) 근거 검증 (2부 T3).

LLM이 만들어내는 Statement/Evidence/KeyMetric은 여기를 통과해야만 신뢰된다.
핵심 원칙(B4): publisher_id·canonical_url 등은 절대 LLM/입력값을 그대로 믿지
않고 항상 카드(SectorCard) 원본에서 재파생한다 — 이 모듈이 그 단일 진입점.
"""
from __future__ import annotations

import datetime as _dt
import ipaddress
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

from publicsuffix2 import PublicSuffixList

from sector.contracts import MetricObservation, SectorCard
from sector.metrics_registry import METRIC_REGISTRY, _GROUP_KEYS
from sector.period import parse_period
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
#
# mask-then-ban 3단계 재설계 (2부 T9 블로커 7 — 과차단·우회 동시 수정):
#   1) 통화/단위 인접 수량은 문자-선행 여부와 무관하게 우선 차단한다
#      ($12·12$·USD12·12 USD·USD-12·12-USD·12달러·12조·12%·3bp 등 — 순서 무관).
#      찾은 즉시 마스킹해 아래 단계가 같은 구간을 재사용하지 않게 한다.
#   2) 남은 "문자로 시작하는 제품 토큰"(gpt-5.5·HBM3E·DDR5·H100·B200 등, 1단계에서
#      이미 소비된 통화 토큰은 제외)을 마스킹해 보존한다 — 이게 숫자를 포함해도
#      허용 목록이다.
#   3) 마스킹 후 그래도 남은 모든 숫자열은 예외 없이 차단한다 — 이전 방식의
#      "앞뒤 비-영숫자" lookaround가 봐주던 우회(-12·12GB·3nm·2x·1e6 등)를 막는다.

_CURRENCY_SYMS = "$₩€£"
_CURRENCY_CODES = ("USD", "KRW", "JPY", "EUR", "GBP", "CNY")
_CODE_ALT = "|".join(_CURRENCY_CODES)
_SYM_CLASS = re.escape(_CURRENCY_SYMS)

# 1단계 — 통화/단위 인접 수량. 순서(양방향)·하이픈/공백 구분자 허용.
_UNIT_PATTERNS: list[re.Pattern] = [
    re.compile(rf"[{_SYM_CLASS}][ \t\-]?\d+(?:\.\d+)?"),
    re.compile(rf"\d+(?:\.\d+)?[ \t\-]?[{_SYM_CLASS}]"),
    re.compile(rf"\b(?:{_CODE_ALT})[ \t\-]?\d+(?:\.\d+)?", re.IGNORECASE),
    re.compile(rf"\d+(?:\.\d+)?[ \t\-]?(?:{_CODE_ALT})\b", re.IGNORECASE),
    re.compile(r"\d+(?:\.\d+)?\s*(?:%|퍼센트)"),
    re.compile(r"\d+(?:\.\d+)?\s*(?:달러|원|엔|위안)"),
    re.compile(r"\d+(?:\.\d+)?\s*(?:조|억|만)\b"),
    re.compile(r"\d+(?:\.\d+)?\s*bp\b", re.IGNORECASE),
]

# 2단계 — 문자로 시작하는 제품 토큰(통화 아님). gpt-5.5/HBM3E/DDR5/H100/B200 등.
_PRODUCT_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[.\-][A-Za-z0-9]+)*\b")

# 3단계 — 마스킹 후 남은 모든 숫자열(지수 표기 1e6 포함).
_REMAINING_DIGIT_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


def quantity_literal(text: str) -> list[str]:
    """text에서 발견된 금지 수량 literal 목록(중복 제거). 빈 리스트 = 클린."""
    original = text or ""
    found: list[str] = []
    seen: set[str] = set()
    masked = list(original)

    def _add(s: str) -> None:
        if s not in seen:
            seen.add(s)
            found.append(s)

    def _mask_span(start: int, end: int) -> None:
        for i in range(start, end):
            masked[i] = "\0"

    for pat in _UNIT_PATTERNS:
        working = "".join(masked)
        for m in pat.finditer(working):
            _add(original[m.start():m.end()])
            _mask_span(m.start(), m.end())

    working = "".join(masked)
    for m in _PRODUCT_TOKEN_RE.finditer(working):
        _mask_span(m.start(), m.end())

    working = "".join(masked)
    for m in _REMAINING_DIGIT_RE.finditer(working):
        _add(original[m.start():m.end()])

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
    """구조 검증을 통과한 statement를 REBUILT Evidence로 새로 만들어 반환한다.

    카드에서 재파생한 `rebuilt` Evidence로 검증하고 통과분을 카운트하지만, 반환은
    항상 원본 `st`가 아니라 `supporting=rebuilt`·`contradicting=[]`인 새 Statement다
    (2부 T9 블로커 5 — 원본을 그대로 돌려주면 LLM이 위조한 canonical_url/
    publisher_id가 검증을 우회해 그대로 살아남는다).
    """
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
        kept.append(st.model_copy(update={"supporting": rebuilt, "contradicting": []}))
    return kept, dropped


# ---- resolve_required_inputs / resolve_key_metrics --------------------------


def _group_key(meta: dict) -> str:
    for k in _GROUP_KEYS:
        v = meta.get(k)
        if v:
            return str(v)
    return ""


def resolve_required_inputs(
    seed: dict, store, now: _dt.datetime | None = None,
    rows_by_metric: dict[str, list[MetricObservation]] | None = None,
) -> list[tuple[dict, KeyMetric | None]]:
    """seed의 required_inputs 항목마다 독립적으로 (entry, KeyMetric|None)을 낸다.

    `resolve_key_metrics`(이름 기준 first-wins)와 달리 이름 dedup을 하지 않는다 —
    같은 metric 이름이 여러 required_inputs에 나오면(HBM/DRAM 병행 추적 등) 각
    항목이 자기 meta_filter 그룹으로 독립적인 KeyMetric을 낸다(2부 T9 블로커 2).
    update_thesis의 prompt 조립·InputSnapshot·최종 key_metrics가 전부 이 한 번의
    결과를 공유해야 TOCTOU(블로커 4)가 생기지 않는다.

    최신 선택은 (미래·파싱불가 제외) 유효 관측만 대상으로 한다(블로커 3 — 공유
    `sector.period.parse_period`). 그룹이 둘 이상으로 모호하면 fail-closed로 None.

    `rows_by_metric`을 주면 그 캐시를 쓰고(호출측이 metric 이름당 1회만 미리
    읽음 — 블로커 4), 없으면 이 함수 안에서 이름당 1회씩만 읽어 로컬 캐시한다.
    """
    if now is None:
        now = _dt.datetime.now(_dt.timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)

    local_cache: dict[str, list[MetricObservation]] = {}

    def _rows_for(name: str) -> list[MetricObservation]:
        if rows_by_metric is not None:
            return rows_by_metric.get(name, [])
        if name not in local_cache:
            local_cache[name] = store.read_metric(name, last_n=1_000_000)
        return local_cache[name]

    out: list[tuple[dict, KeyMetric | None]] = []
    for ri in seed.get("required_inputs", []):
        name = ri["metric"]
        if name not in METRIC_REGISTRY:
            out.append((ri, None))
            continue
        meta_filter = ri.get("meta_filter", {}) or {}
        rows = _rows_for(name)
        matching = [o for o in rows
                   if all(o.meta.get(k) == v for k, v in meta_filter.items())]
        valid: list[tuple[MetricObservation, _dt.datetime]] = []
        for o in matching:
            period = parse_period(o.ts)
            if period is None:
                continue  # 파싱 불가 → 무효 (블로커 3)
            start, end = period
            if start > now:
                continue  # 미래 → 무효 (블로커 3)
            valid.append((o, end))
        if not valid:
            out.append((ri, None))
            continue
        groups: dict[str, list[tuple[MetricObservation, _dt.datetime]]] = {}
        for o, end in valid:
            groups.setdefault(_group_key(o.meta), []).append((o, end))
        if len(groups) != 1:
            # 다중 서브시리즈(예: hyperscaler_capex의 MSFT/META)가 meta_filter로
            # 하나로 좁혀지지 않으면 어느 쪽이 "최신"인지 임의로 고를 수 없다 —
            # fail-closed: 모호하면 절대 조용히 아무 서브시리즈나 반환하지 않는다.
            out.append((ri, None))
            continue
        latest_o, _end = max(valid, key=lambda t: t[1])  # 기간 끝 기준(문자열 ts 아님, 블로커 3)
        source = latest_o.source or METRIC_REGISTRY[name]["desc"]  # provenance 부재 관측의 표시용
        km = KeyMetric(
            metric=name, observation_id=observation_id(name, latest_o.ts, latest_o.meta),
            value=latest_o.value, unit=latest_o.unit, ts=latest_o.ts,
            meta=latest_o.meta, source=source)
        out.append((ri, km))
    return out


def resolve_key_metrics(
    names: list[str], seed: dict, store, now: _dt.datetime | None = None,
) -> tuple[list[KeyMetric], list[str]]:
    """seed의 required_inputs에서 각 metric의 meta_filter 그룹을 찾아 최신 관측을 KeyMetric으로.

    같은 metric 이름이 required_inputs에 여러 번 나오면(예: hbm-tightness의
    HBM/DRAM 병행 추적) 첫 번째 항목을 헤드라인 필터로 결정적으로 사용한다 —
    이 함수 자체의 first-wins 계약(기존 테스트)은 유지한다. update_thesis
    파이프라인은 여러 항목을 동시에 원하므로 이제 `resolve_required_inputs`를
    직접 쓰고, 이 함수는 그 위의 이름-dedup wrapper로 남는다(2부 T9 블로커 2/4).
    """
    resolved = resolve_required_inputs(seed, store, now)
    by_metric: dict[str, KeyMetric | None] = {}
    for ri, km in resolved:
        by_metric.setdefault(ri["metric"], km)  # first-wins — setdefault는 첫 값만 채움
    kms: list[KeyMetric] = []
    dropped: list[str] = []
    for name in names:
        km = by_metric.get(name)
        if km is None:
            dropped.append(name)
            continue
        kms.append(km)
    return kms, dropped
