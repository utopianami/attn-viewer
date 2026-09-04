"""시황 리포트 읽기 표면의 공통 회사명·ticker·내부표기 규칙.

생성 폴백, Pydantic 계약, 독립 저장 JSON 검증기가 이 모듈을 함께 사용한다.
원시 카드는 바꾸지 않고 ``brief_v1`` 화면 사본만 검사·정규화한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


COMPANY_NAMES = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "LRCX": "램리서치",
    "LAM RESEARCH": "램리서치",
    "LAM RESEARCH CORPORATION": "램리서치",
    "AMAT": "어플라이드 머티어리얼즈",
    "APPLIED MATERIALS": "어플라이드 머티어리얼즈",
    "APPLIED MATERIALS INC": "어플라이드 머티어리얼즈",
    "ASML": "ASML",
    "KLAC": "KLA",
    "KLA": "KLA",
    "MU": "마이크론",
    "MICRON": "마이크론",
    "GOOGL": "알파벳",
    "GOOG": "알파벳",
    "ALPHABET": "알파벳",
    "META": "메타",
    "META PLATFORMS": "메타",
    "MSFT": "마이크로소프트",
    "MICROSOFT": "마이크로소프트",
    "AMZN": "아마존",
    "AMAZON": "아마존",
    "ORCL": "오라클",
    "ORACLE": "오라클",
    "AVGO": "브로드컴",
    "BRCM": "브로드컴",
    "BROADCOM": "브로드컴",
    "NVDA": "엔비디아",
    "INTC": "인텔",
    "INTEL": "인텔",
    "QCOM": "퀄컴",
    "QUALCOMM": "퀄컴",
    "AAPL": "애플",
    "APPLE": "애플",
    "TSLA": "테슬라",
    "TESLA": "테슬라",
    "TSM": "TSMC",
    "TAIWAN SEMICONDUCTOR": "TSMC",
    "BRK": "버크셔 해서웨이",
}

NON_TICKER_ACRONYMS = frozenset({
    "AI", "GPU", "CPU", "HBM", "DRAM", "NAND", "CPI", "PPI", "GDP",
    "ETF", "FX", "USD", "KRW", "JPY", "EUR", "API", "KST", "UTC",
    "ASML", "KLA", "TSMC",
    "KOSIS", "FRED", "SEC", "IMF", "BIS", "OECD", "EIA", "IEA",
    "BEA", "BLS", "FED", "BOJ", "ECB", "PBOC", "RBNZ", "CME",
    "WSJ", "CNBC", "USTR", "FDA", "FTC", "FCC", "EPA", "MOF", "NBS",
    "CEO", "IPO", "EPS", "EBITDA", "FCF", "PMI", "SOFR", "TIPS",
    "JGB", "DXY", "WTI", "LNG", "ADR", "YTD", "QT", "TAM", "ASP",
    "MOU", "UAE", "EU", "GMT", "EDT", "SGT",
})

TICKER_SUFFIX_RE = re.compile(r"\s*\((?P<ticker>[^()\s]{1,64})\)\s*$")
PARENTHESIZED_CODE_RE = re.compile(
    r"\(\s*(?P<code>[A-Za-z0-9][A-Za-z0-9=.-]{0,63})\s*\)", re.I)
READER_INTERNAL_RE = re.compile(
    r"(?:(?<![A-Za-z0-9_])[A-Za-z0-9][A-Za-z0-9.,]*_[A-Za-z0-9_]+(?![A-Za-z0-9_])|"
    r"(?<![A-Za-z])(?:QoQ|MoM|YoY|DoD|WoW|CAPEX|backlog)(?![A-Za-z])|"
    r"@\d{4}-\d{2}(?:-\d{2})?|\d[\d,.]*\s*b원)",
    re.I,
)
CONTEXTUAL_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:종목\s*코드|티커|ticker)\s*[:：]?\s*"
    r"[A-Za-z0-9][A-Za-z0-9=.-]{0,63}", re.I)

# 거래소 suffix만 점 표기 ticker로 본다. CXL2.0, Reuters.com, Node.js 같은
# 기술 세대·도메인을 임의의 ``word.suffix`` 규칙으로 지우지 않는다.
_EXCHANGE_SUFFIXES = (
    "O", "N", "L", "S", "SA", "KS", "KQ", "T", "AS", "DE", "PA",
    "MI", "HK", "SS", "SZ", "TO", "V", "AX", "JO", "NS", "BO", "SI",
    "TW", "TWO", "MX", "BR", "CO", "OL", "ST", "HE", "IC", "VI", "WA",
    "PR", "IR", "JK", "NYB",
)
_EXCHANGE_SUFFIX_PATTERN = "|".join(
    sorted((re.escape(value) for value in _EXCHANGE_SUFFIXES), key=len, reverse=True))
QUALIFIED_TICKER_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:"
    rf"[A-Za-z][A-Za-z0-9]{{0,15}}(?:-[A-Za-z0-9]{{1,8}})?\."
    rf"(?:{_EXCHANGE_SUFFIX_PATTERN})|"
    r"[A-Za-z][A-Za-z0-9]{1,31}=[A-Za-z0-9]{1,32}|"
    r"\d{4,6}(?:\.[A-Za-z0-9]{1,8})+)(?![A-Za-z0-9])",
    re.I,
)
KNOWN_RIC_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:LCOc1|GCcv1|CLc1|NGc1|SIcv1|HGcv1|ESc1|NQc1|TYc1)"
    r"(?![A-Za-z0-9])",
    re.I,
)
KNOWN_HYPHEN_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])BRK-[AB](?:\.[A-Z]{1,4})?(?![A-Za-z0-9])", re.I)
KNOWN_TICKER_RE = re.compile(
    r"(?:\d{4,6}\.[A-Za-z0-9]{1,8}|"
    r"(?<![A-Za-z0-9.])(?:LRCX|AMAT|KLAC|MU|GOOGL|GOOG|MSFT|AMZN|ORCL|AVGO|"
    r"BRCM|META|NVDA|INTC|QCOM|AAPL|TSLA|TSM|BRK(?:-[AB])?)"
    r"(?:\.[A-Za-z0-9]{1,8})?(?![A-Za-z0-9.]))",
    re.I,
)

_LEGITIMATE_COMPANY_PHRASES = (
    "Meta Platforms", "Lam Research Corporation", "Lam Research",
    "Applied Materials Inc", "Applied Materials", "Micron Technology",
)
_BARE_WORDMARK_TICKERS = frozenset({"AMD", "IBM", "SAP", "ARM", "ASML", "KLA"})


@dataclass(frozen=True)
class ReaderIdentity:
    base_name: str
    display_name: str
    ticker: str
    aliases: frozenset[str]
    forbidden_tokens: tuple[str, ...]


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _token_is_part_of_name(token: str, names: Iterable[str]) -> bool:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", re.I)
    return any(pattern.search(name) for name in names)


def ticker_tokens(ticker: str) -> tuple[str, ...]:
    clean = ticker.strip().upper()
    if not clean:
        return ()
    root = re.split(r"[.\-=]", clean, maxsplit=1)[0]
    return tuple(dict.fromkeys((clean, root)))


def reader_identity(raw_name: object, *, kind: str = "stock") -> ReaderIdentity:
    """원본 이름에서 표시명·허용 alias·실제로 숨길 ticker를 한 번에 계산한다."""
    clean = _clean(raw_name) or "관련 대상"
    match = TICKER_SUFFIX_RE.search(clean)
    if match and kind != "stock":
        raw_code = match.group("ticker")
        code = raw_code.upper()
        if raw_code in NON_TICKER_ACRONYMS:
            match = None
        elif not (
            re.search(r"[0-9.=]", code)
            or re.fullmatch(r"[A-Z]{2,8}(?:-[A-Z]{1,8})?", code)
        ):
            match = None
    ticker = match.group("ticker").upper() if match else ""
    base = (clean[:match.start()].strip() if match else clean) or "관련 대상"
    root = re.split(r"[.\-=]", ticker, maxsplit=1)[0] if ticker else ""
    if root == "BRK" and base.upper() == "BERKSHIRE HATHAWAY":
        display = base
    else:
        display = (
            COMPANY_NAMES.get(ticker)
            or COMPANY_NAMES.get(root)
            or COMPANY_NAMES.get(base.upper())
            or ("해당 기업" if ticker and base.upper() == root
                and root not in _BARE_WORDMARK_TICKERS else base)
        )
    if display == base:
        for code, company in sorted(COMPANY_NAMES.items(), key=lambda item: -len(item[0])):
            display = re.sub(
                rf"(?<![A-Za-z0-9.]){re.escape(code)}(?![A-Za-z0-9.])",
                company,
                display,
                flags=re.I,
            )
    display = QUALIFIED_TICKER_RE.sub("", display)
    display = KNOWN_RIC_RE.sub("", display)
    display = KNOWN_HYPHEN_TICKER_RE.sub("", display)
    display = re.sub(r"\(\s*\)", "", display)
    display = _clean(display).strip(" ,;:-") or ("해당 기업" if kind == "stock" else "관련 대상")
    if READER_INTERNAL_RE.search(display) or CONTEXTUAL_TICKER_RE.search(display):
        display = "관련 대상"
    if len(display) > 100:
        display = display[:99].rstrip(" ,;:·-—") + "…"
    aliases = {base, display}
    for key in (ticker, root, base.upper()):
        if key and COMPANY_NAMES.get(key):
            aliases.add(COMPANY_NAMES[key])
    forbidden: list[str] = []
    for token in ticker_tokens(ticker):
        # AMD (AMD), ASML (ASML.AS)처럼 회사 이름 자체가 코드인 경우에는
        # root를 지우면 대상을 표현할 방법이 없다. 거래소가 붙은 전체 코드는
        # base에 그대로 쓰인 경우가 아니면 계속 금지한다.
        is_registered_wordmark = (
            token == root
            and (root in _BARE_WORDMARK_TICKERS
                 or (root in COMPANY_NAMES and _token_is_part_of_name(token, (base,))))
        )
        if not is_registered_wordmark and not (
                token != root and _token_is_part_of_name(token, (base, display))):
            forbidden.append(token)
    return ReaderIdentity(
        base_name=base,
        display_name=display,
        ticker=ticker,
        aliases=frozenset(value for value in aliases if value),
        forbidden_tokens=tuple(forbidden),
    )


def replace_ticker_token(text: str, ticker: str, replacement: str = "") -> str:
    return re.sub(
        rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])",
        replacement,
        text,
        flags=re.I,
    )


def source_ticker_replacements(items: Iterable[tuple[object, str]]) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for raw_name, kind in items:
        identity = reader_identity(raw_name, kind=kind)
        for token in identity.forbidden_tokens:
            replacements[token] = identity.display_name
    return replacements


def replace_source_tickers(text: str, replacements: dict[str, str]) -> str:
    for token, display in sorted(replacements.items(), key=lambda item: -len(item[0])):
        text = replace_ticker_token(text, token, display)
    return text


def iter_reader_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_reader_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from iter_reader_strings(item)


def contains_token(text: str, token: str) -> bool:
    return bool(re.search(
        rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text, re.I))


def reader_text_problem(text: str) -> bool:
    if (READER_INTERNAL_RE.search(text)
            or CONTEXTUAL_TICKER_RE.search(text)
            or QUALIFIED_TICKER_RE.search(text)
            or KNOWN_RIC_RE.search(text)
            or KNOWN_HYPHEN_TICKER_RE.search(text)):
        return True
    scrubbed = text
    for phrase in _LEGITIMATE_COMPANY_PHRASES:
        scrubbed = re.sub(re.escape(phrase), " ", scrubbed, flags=re.I)
    if KNOWN_TICKER_RE.search(scrubbed):
        return True
    return any(match.group("code") not in NON_TICKER_ACRONYMS
               for match in PARENTHESIZED_CODE_RE.finditer(text))


def reader_surface_problem(value: object, *, forbidden_tokens: Iterable[str] = ()) -> bool:
    tokens = tuple(dict.fromkeys(token for token in forbidden_tokens if token))
    for text in iter_reader_strings(value):
        if reader_text_problem(text):
            return True
        if any(contains_token(text, token) for token in tokens):
            return True
    return False
