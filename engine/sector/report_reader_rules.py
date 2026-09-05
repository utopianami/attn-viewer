"""시황 리포트 읽기 표면의 공통 회사명·ticker·내부표기 규칙.

생성 폴백, Pydantic 계약, 독립 저장 JSON 검증기가 이 모듈을 함께 사용한다.
원시 카드는 바꾸지 않고 ``brief_v1`` 화면 사본만 검사·정규화한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Mapping


@lru_cache(maxsize=32768)
def _compiled_reader_pattern(pattern: str, flags: int = 0) -> re.Pattern:
    """Reuse report-specific cleanup regexes across every reader field."""
    return re.compile(pattern, flags)


def _reader_re_sub(pattern: str | re.Pattern, replacement, text: str,
                   count: int = 0, flags: int = 0) -> str:
    """``re.sub`` equivalent backed by a cache larger than ``re``'s 512 slots."""
    if isinstance(pattern, re.Pattern):
        if flags:
            raise ValueError("cannot process flags argument with a compiled pattern")
        compiled = pattern
    else:
        compiled = _compiled_reader_pattern(pattern, flags)
    return compiled.sub(replacement, text, count=count)


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
    "MICRON TECHNOLOGY": "마이크론",
    "MICRON TECHNOLOGY INC": "마이크론",
    "CRM": "세일즈포스",
    "SALESFORCE": "세일즈포스",
    "SNPS": "시놉시스",
    "SYNOPSYS": "시놉시스",
    "MRVL": "마벨 테크놀로지",
    "WDC": "웨스턴디지털",
    "SNDK": "샌디스크",
    "SHOP": "쇼피파이",
    "IBM": "IBM",
    "BP": "BP",
    "0981": "중신궈지",
    "285A": "키옥시아",
    "RIO": "리오틴토",
    "0285": "비야디",
    "002594": "비야디",
    "9888": "바이두",
    "BIDU": "바이두",
    "7203": "도요타",
    "TM": "도요타",
    "1398": "중국공상은행",
    "601398": "중국공상은행",
    "BABA": "알리바바",
    "TEAM": "아틀라시안",
    "MCHP": "마이크로칩 테크놀로지",
    "NEE": "넥스트에라 에너지",
    "NYT": "뉴욕타임스",
    "MTZ": "MasTec",
    "KLAR": "Klarna",
    "ISHIP": "해운업종",
    "APPL": "애플",
    "9984": "소프트뱅크",
    "9432": "NTT",
    "RHM": "라인메탈",
    "GFS": "글로벌파운드리스",
    "UMC": "UMC",
    "MS": "모건스탠리",
    "NOW": "서비스나우",
    "VZ": "버라이즌",
    "ON": "온세미",
    "2330": "TSMC",
    "2317": "홍하이",
    "HONHAI": "홍하이",
    "HON HAI": "홍하이",
    "FOXCONN": "홍하이",
    "6669": "위윈",
    "WIWYNN": "위윈",
    "2356": "인벤텍",
    "INVENTEC": "인벤텍",
    "2382": "콴타",
    "QUANTA": "콴타",
    "QUANTA COMPUTER": "콴타",
    "3231": "위스트론",
    "WISTRON": "위스트론",
    "0700": "텐센트",
    "688836": "유니트리",
    "9618": "징둥닷컴",
    "JD": "징둥닷컴",
    "601939": "중국건설은행",
    "0939": "중국건설은행",
    "UPS": "UPS",
    "STLAM": "스텔란티스",
    "STLA": "스텔란티스",
    "GM": "제너럴 모터스",
    "7267": "혼다",
    "HMC": "혼다",
    "6857": "어드반테스트",
    "5711": "미쓰비시머티리얼",
    "5631": "일본제강소",
    "9503": "간사이전력",
    "5301": "도카이카본",
    "6473": "JTEKT",
    "ALP": "알파 컴퓨트",
    "APLD": "어플라이드 디지털",
    "BKNG": "부킹 홀딩스",
    "BMWG": "BMW",
    "CAT": "캐터필러",
    "DBSM": "DBS 그룹",
    "DE": "디어",
    "ENB": "앤브리지",
    "ETN": "이튼",
    "EVRG": "에버너지",
    "HPQ": "HP",
    "HUT": "헛 에이트",
    "LEGD": "레그랑",
    "LIN": "린데",
    "LNT": "올리언트 에너지",
    "MPWR": "모놀리식 파워 시스템즈",
    "MSTR": "스트래티지",
    "NBIS": "네비우스 그룹",
    "OOGL": "알파벳",
    "SHEL": "셸",
    "SHW": "셔윈윌리엄스",
    "SO": "서던컴퍼니",
    "TTWO": "테이크투 인터랙티브",
    "TXN": "텍사스인스트루먼트",
    "VOWG": "폭스바겐",
    "WMT": "월마트",
    "XOM": "엑손모빌",
    "BRKA": "버크셔 해서웨이",
    "GOOGL": "알파벳",
    "GOOG": "알파벳",
    "GOOGLE": "알파벳",
    "ALPHABET": "알파벳",
    "META": "메타",
    "META PLATFORMS": "메타",
    "META PLATFORMS INC": "메타",
    "META PLATFORMS, INC.": "메타",
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
    "NVIDIA": "엔비디아",
    "NVIDIA CORPORATION": "엔비디아",
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
    "PLTR": "팔란티어",
    "VRT": "버티브",
    "BRK": "버크셔 해서웨이",
    "DX-Y": "달러지수",
    "SIEGN": "지멘스",
    "GHCPIY": "소비자물가 지표",
    "GSPC": "S&P 500 지수",
    "SPX": "S&P 500 지수",
    "IXIC": "나스닥 종합지수",
    "SOX": "필라델피아 반도체지수",
    "KS11": "코스피",
    "TNX": "미국 10년물 국채금리",
    "DJI": "다우존스 산업평균지수",
    "N225": "닛케이 225 지수",
    "HSI": "항셍지수",
    "9988": "알리바바",
    "US10YT": "미국 10년물 국채금리",
    "US2US10": "미국 2년·10년 금리차",
    "CL=F": "WTI 원유",
    "KRW=X": "원·달러 환율",
    "JPY=X": "엔·달러 환율",
    "JP2YTN=JBTC": "일본 2년물 금리",
    "DDR5=PC": "PC용 DDR5",
    "DDR=D": "DDR 메모리",
    "Y2=HBM": "신규 HBM 공장",
    "SX8P=STOXX": "유럽 기술주 지수",
    "FDX": "페덱스",
    "CRWV": "코어위브",
    "ENR1N": "지멘스에너지",
    "NVT": "엔벤트 일렉트릭",
    "PETR4": "페트로브라스",
    "CVX": "셰브론",
    "SMCI": "슈퍼마이크로컴퓨터",
    "CSCO": "시스코",
    "SKHY": "SK하이닉스",
    "CRBS": "세레브라스",
    "CBRS": "세레브라스",
    "NVENT ELECTRIC": "엔벤트 일렉트릭",
    "TSEM": "타워 세미컨덕터",
    "TOWER SEMICONDUCTOR": "타워 세미컨덕터",
    "KSP": "킹스판",
    "KINGSPAN": "킹스판",
    "REP": "렙솔",
    "REPSOL": "렙솔",
    "MAGS": "매그니피센트 세븐 ETF",
    "688825": "CXMT",
    "APO": "아폴로 글로벌 매니지먼트",
    "BAM": "브룩필드 자산운용",
    "BLK": "블랙록",
    "BX": "블랙스톤",
    "GS": "골드만삭스",
    "KKR": "KKR",
}

# 전역 자연어 치환이 안전한 실제 회사 이름·영문 별칭만 둔다. REP·SOX·MAGS나
# 숫자 코드처럼 일반 문장과 충돌하는 ticker root는 source inventory가 확인한
# 문맥에서만 치환한다.
GLOBAL_COMPANY_NAME_ALIASES = {
    "LAM RESEARCH": "램리서치",
    "LAM RESEARCH CORPORATION": "램리서치",
    "APPLIED MATERIALS": "어플라이드 머티어리얼즈",
    "APPLIED MATERIALS INC": "어플라이드 머티어리얼즈",
    "MICRON": "마이크론",
    "MICRON TECHNOLOGY": "마이크론",
    "MICRON TECHNOLOGY INC": "마이크론",
    "SALESFORCE": "세일즈포스",
    "SYNOPSYS": "시놉시스",
    # 자연어의 Google은 브랜드/서비스 이름으로도 쓰인다. 주식 코드
    # GOOGL·GOOG는 계속 알파벳으로 풀되, 이미 읽을 수 있는 회사명은
    # 구글로 보존해 ``알파벳의 알파벳 투자`` 같은 중복을 막는다.
    "GOOGLE": "구글",
    "ALPHABET": "알파벳",
    "ALPHABET INC.": "알파벳",
    "META PLATFORMS": "메타",
    "META PLATFORMS INC": "메타",
    "MICROSOFT": "마이크로소프트",
    "AMAZON": "아마존",
    "AMAZON WEB SERVICES": "아마존웹서비스",
    "ORACLE": "오라클",
    "ORACLE CORP": "오라클",
    "BROADCOM": "브로드컴",
    "BROADCOM INC.": "브로드컴",
    "NVIDIA": "엔비디아",
    "NVIDIA CORPORATION": "엔비디아",
    "INTEL": "인텔",
    "QUALCOMM": "퀄컴",
    "APPLE": "애플",
    "TESLA": "테슬라",
    "TAIWAN SEMICONDUCTOR": "TSMC",
    "NVENT ELECTRIC": "엔벤트 일렉트릭",
    "TOWER SEMICONDUCTOR": "타워 세미컨덕터",
    "KINGSPAN": "킹스판",
    "REPSOL": "렙솔",
}

GLOBAL_BARE_TICKER_NAMES = {
    code: COMPANY_NAMES[code]
    for code in (
        "LRCX", "AMAT", "KLAC", "MU", "SNPS", "GOOGL", "GOOG", "MSFT",
        "AMZN", "SNDK",
        "ORCL", "AVGO", "BRCM", "META", "NVDA", "INTC", "QCOM", "AAPL",
        "TSLA", "TSM", "BRK",
    )
}

DOLLAR_TICKER_NAMES = {
    "NVDA": "엔비디아", "GOOGL": "알파벳", "MSFT": "마이크로소프트",
    "AMD": "AMD", "META": "메타", "AAPL": "애플", "SPCX": "스페이스X",
    "AMZN": "아마존", "QCOM": "퀄컴", "CVX": "셰브론", "INTC": "인텔",
    "AVGO": "브로드컴", "ORCL": "오라클", "MU": "마이크론", "F": "포드",
    "SKHY": "SK하이닉스", "SMCI": "슈퍼마이크로컴퓨터", "TSM": "TSMC",
    "TSLA": "테슬라", "CSCO": "시스코", "CRBS": "세레브라스",
    "CBRS": "세레브라스", "C": "씨티그룹", "O": "리얼티인컴",
    "V": "비자", "J": "제이콥스 솔루션스", "T": "AT&T",
    "D": "도미니언 에너지", "X": "US스틸",
    "UMC": "UMC", "GFS": "글로벌파운드리스", "MS": "모건스탠리",
    "WLFI": "WLFI 토큰",
    "YLDS": "YLDS",
}

ONE_LETTER_RIC_NAMES = {
    "C.N": "씨티그룹", "D.N": "도미니언 에너지", "F.N": "포드",
    "J.N": "제이콥스 솔루션스", "O.N": "리얼티인컴", "T.N": "AT&T",
    "V.N": "비자", "X.N": "US스틸",
}

EMPTY_MARKET_CODE_NAMES = {
    "XAU": "현물 금", "XAG": "현물 은", "XPD": "팔라듐 현물",
    "XPT": "백금 현물", "JPY": "엔·달러 환율", "EUR": "유로·달러 환율",
    "GBP": "파운드·달러 환율", "IDR": "인도네시아 루피아·달러 환율",
    "BRL": "브라질 헤알·달러 환율", "COP": "콜롬비아 페소·달러 환율",
    "MXN": "멕시코 페소·달러 환율", "PHP": "필리핀 페소·달러 환율",
    "MYR": "말레이시아 링깃·달러 환율", "BTC": "비트코인",
    "ETH": "이더리움", "KRW": "원·달러 환율", "USD": "달러",
    "CNY": "위안·달러 환율", "CNH": "역외 위안·달러 환율",
    "AUD": "호주달러·미국달러 환율", "NZD": "뉴질랜드달러·미국달러 환율",
    "TWD": "대만달러·미국달러 환율", "THB": "태국 바트·달러 환율",
    "ARS": "아르헨티나 페소·달러 환율", "INR": "인도 루피·달러 환율",
    "CHF": "스위스프랑·달러 환율", "CAD": "캐나다달러·미국달러 환율",
    "HKD": "홍콩달러·미국달러 환율", "SGD": "싱가포르달러·미국달러 환율",
}

NUMERIC_TICKER_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
    "9988": "알리바바",
    "688825": "CXMT",
}

LEADING_DOT_INDEX_NAMES = {
    "SPX": "S&P 500 지수", "IXIC": "나스닥 종합지수",
    "SOX": "필라델피아 반도체지수", "KS11": "코스피",
    "DJI": "다우존스 산업평균지수", "N225": "닛케이 225 지수",
    "TWII": "대만 가권지수", "SSEC": "상하이종합지수",
    "MILA00000PUS": "MSCI 라틴아메리카 주가지수", "BVSP": "브라질 보베스파지수",
    "STOXX": "STOXX 유럽 600 지수", "MSCIEF": "MSCI 신흥시장 주가지수",
    "MXX": "멕시코 IPC지수", "JKSE": "인도네시아 IDX 종합지수",
    "STI": "싱가포르 스트레이츠타임스지수", "CSI300": "중국 CSI 300 지수",
    "COLCAP": "콜롬비아 COLCAP지수", "SETI": "태국 SET지수",
    "PSI": "필리핀 PSEi", "KLSE": "말레이시아 KLCI",
    "MERV": "아르헨티나 메르발지수", "HSI": "항셍지수",
    "MIWD00000PUS": "MSCI 세계 주가지수", "SPIPSA": "칠레 IPSA지수",
    "MIEM00000CUS": "MSCI 신흥시장 통화지수",
    "MILA00000CUS": "MSCI 라틴아메리카 통화지수", "NSEI": "인도 니프티 50",
    "MISX00000PUS": "MSCI 일본 제외 아시아태평양지수", "TOPX": "토픽스",
    "FTSE": "FTSE 100 지수", "MIMS00000PUS": "MSCI 신흥 아시아 주가지수",
    "SPLRCT": "S&P 500 정보기술지수", "SPNY": "미국 에너지주 지수",
    "STAR50": "중국 STAR 50 지수", "FTMC": "FTSE 250 지수",
    "HSTECH": "항셍테크지수", "DXY": "달러지수", "VIX": "변동성지수",
    "AD.SPX": "S&P 500 등락 종목 폭", "RUT": "러셀 2000 지수",
    "DJT": "다우 운송지수", "MOVE": "미국 채권 변동성지수",
    "MIMS0IT00PUS": "MSCI 신흥 아시아 정보기술지수",
    "CSI930713": "중국 CSI 인공지능지수",
    "CSI931865": "중국 CSI 반도체지수",
    "CSI931079": "중국 CSI 5G 통신지수",
    "MISU00000PUS": "MSCI 아세안 주가지수",
    "SX8P": "유럽 기술주 지수",
    "MIWO00000PUS": "MSCI 전 세계 주가지수",
    "MILA00000CU": "MSCI 라틴아메리카 통화지수",
    "CSI399976": "중국 신에너지 자동차지수",
    "CSI399986": "중국 은행업종지수",
    "CSI930598": "중국 희토류업종지수",
    "FCHI": "프랑스 CAC 40 지수",
    "GDAXI": "독일 DAX 지수",
    "SPLRCL": "S&P 500 커뮤니케이션 서비스지수",
}

NON_TICKER_ACRONYMS = frozenset({
    "AI", "GPU", "CPU", "NPU", "TPU", "ASIC", "FPGA", "SOC",
    "HBM", "HBM2", "HBM2E", "HBM3", "HBM3E", "HBM4",
    "DRAM", "DDR", "DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR5",
    "LPDDR5X", "GDDR6", "CXL", "PCIE", "NVLINK",
    "NAND", "CPI", "PPI", "GDP",
    "ETF", "FX", "USD", "KRW", "JPY", "EUR", "GBP", "CNY", "CNH",
    "AUD", "NZD", "TWD", "THB", "ARS", "INR", "IDR", "BRL", "COP",
    "MXN", "PHP", "MYR", "CHF", "CAD", "HKD", "SGD",
    "API", "KST", "UTC",
    "ASML", "KLA", "TSMC",
    "KOSIS", "FRED", "SEC", "IMF", "BIS", "OECD", "EIA", "IEA",
    "BEA", "BLS", "FED", "BOJ", "ECB", "PBOC", "RBNZ", "CME",
    "WSJ", "CNBC", "USTR", "FDA", "FTC", "FCC", "EPA", "MOF", "NBS",
    "CEO", "IPO", "EPS", "EBITDA", "FCF", "PMI", "SOFR", "TIPS", "CRM",
    "BP", "TEAM", "MS",
    "JGB", "DXY", "WTI", "LNG", "ADR", "YTD", "QT", "TAM", "ASP",
    "MOU", "UAE", "EU", "GMT", "EDT", "SGT", "WLFI", "YLDS",
})
MIXED_CASE_TECH_ACRONYMS = frozenset({"SoC"})

TICKER_SUFFIX_RE = re.compile(r"\s*\((?P<ticker>[^()\s]{1,64})\)\s*$")
PARENTHESIZED_CODE_RE = re.compile(
    r"\(\s*(?P<code>[A-Za-z0-9][A-Za-z0-9=.-]{0,63})\s*\)", re.I)
READER_INTERNAL_RE = re.compile(
    r"(?:(?<![A-Za-z0-9_/?#=&])[A-Za-z0-9][A-Za-z0-9.,]*_[A-Za-z0-9_]+(?![A-Za-z0-9_])|"
    r"(?<![A-Za-z])(?:QoQ|MoM|YoY|DoD|WoW|CAPEX|backlog)(?![A-Za-z])|"
    r"@\d{4}-\d{2}(?:-\d{2})?|\d[\d,.]*\s*b원)",
    re.I,
)
READER_FINANCIAL_SHORTHAND_RE = re.compile(
    r"(?:\d[\d,.]*\s*USD\s*(?:/|per\s+)\s*\(?\s*"
    r"(?:TB/s|GB/s|MB/s|TBps|GBps|MBps|TB|GB|MB)\s*\)?|"
    r"\$\s*\d[\d,.]*\s*/\s*(?:TB/s|GB/s|MB/s|TBps|GBps|MBps|TB|GB|MB)|"
    r"[+\-−]?\d[\d,.]*%(?:\s*\(\s*\d+\s*M(?=\s*[,)]|$)|"
    r"\s+\d+\s*M(?=\s*[,)]|\s|$))|"
    r"(?<![A-Za-z0-9])ASP(?![A-Za-z0-9])|"
    r"Δ\s*[+\-−]?\d[\d,.]*%(?:p\b)?)",
    re.I,
)
RESEARCH_PROCESS_NARRATION_CORE = (
    r"(?:(?:이번|심층|추가)\s*)?(?:연구|조사)(?:에서는?|에서|는|가)\s*"
    r"(?:[^.!?。！？—–]{0,240}실패(?:한다|했다)|"
    r"[^.!?。！？—–]{0,240}검증되지\s*않았(?:음|다)"
    r"[^.!?。！？—–]{0,48}(?:보여준다|드러낸다)|"
    r"(?=[^.!?。！？—–]{0,120}(?:카드(?:의)?\s*핵심\s*판단|"
    r"현상\s*해석|해석(?:의)?\s*(?:핵심\s*)?전제|"
    r"헤드라인[^.!?。！？—–]{0,24}(?:검증|표현|수치)))"
    r"[^.!?。！？—–]{0,240}(?:뒤집(?:는다|었다)|정정(?:한다|했다)|"
    r"바꾼다|해소(?:한다|했다)|보여준다|드러낸다))"
)
READER_PROCESS_BOILERPLATE_RE = re.compile(
    r"(?:추가\s*연구(?:\s*(?:근거|결과|제한))?\s*[:：]?|"
    r"(?<![0-9A-Za-z가-힣])" + RESEARCH_PROCESS_NARRATION_CORE + r"|"
    r"(?:자세한|상세한?)\s*내용(?:은|을)?\s*원문(?:에서|으로)?\s*확인|"
    r"원문(?:\s*(?:데이터|카드|내용|근거))?(?:에서|을|에)?"
    r"[^.!?。！？]{0,24}(?:확인|참조|기록))",
    re.I,
)
READER_SCAN_FIRST_META_RE = re.compile(
    READER_PROCESS_BOILERPLATE_RE.pattern
    + r"|(?:조사\s*결과|연구\s*결과|근거\s*출처|"
      r"출처\s*(?:는|:|：)|〔(?:근거|계산):[^〕]*〕)",
    re.I,
)
READER_EQUALS_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]{1,31}="
    r"(?:[A-Za-z0-9][A-Za-z0-9._-]{0,63}|"
    r"[가-힣][A-Za-z0-9가-힣· /._-]{0,63})"
    r"(?![A-Za-z0-9가-힣])",
    re.I,
)
CONTEXTUAL_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:종목\s*코드|티커|ticker)"
    r"(?:\s*[:：]\s*|\s+)"
    r"[A-Za-z0-9][A-Za-z0-9=.-]{0,63}", re.I)

# 거래소 suffix만 점 표기 ticker로 본다. CXL2.0, Reuters.com, Node.js 같은
# 기술 세대·도메인을 임의의 ``word.suffix`` 규칙으로 지우지 않는다.
_EXCHANGE_SUFFIXES = (
    "O", "N", "L", "S", "SA", "KS", "KQ", "T", "AS", "DE", "PA",
    "MI", "HK", "SS", "SZ", "TO", "V", "AX", "JO", "NS", "BO", "SI",
    "TW", "TWO", "MX", "BR", "CO", "OL", "ST", "HE", "IC", "VI", "WA",
    "PR", "IR", "JK", "NYB", "TA", "I", "MC", "P", "K", "US",
)
_EXCHANGE_SUFFIX_PATTERN = "|".join(
    sorted((re.escape(value) for value in _EXCHANGE_SUFFIXES), key=len, reverse=True))
QUALIFIED_TICKER_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:"
    rf"[A-Za-z][A-Za-z0-9]{{0,15}}(?:-[A-Za-z0-9]{{1,8}})?\."
    rf"(?:{_EXCHANGE_SUFFIX_PATTERN})|"
    rf"(?-i:\d{{2,6}}[A-Z][A-Z0-9]{{0,5}})\."
    rf"(?:{_EXCHANGE_SUFFIX_PATTERN})|"
    rf"\d{{4,6}}\.(?:{_EXCHANGE_SUFFIX_PATTERN}))(?![A-Za-z0-9])",
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
    rf"(?:\d{{4,6}}\.(?:{_EXCHANGE_SUFFIX_PATTERN})|"
    r"(?<![A-Za-z0-9.])(?:LRCX|AMAT|KLAC|MU|SNPS|GOOGL|GOOG|MSFT|AMZN|ORCL|AVGO|"
    r"BRCM|META|NVDA|INTC|QCOM|AAPL|TSLA|TSM|BRK(?:-[AB])?)"
    rf"(?:\.(?:{_EXCHANGE_SUFFIX_PATTERN}))?(?![A-Za-z0-9.]))",
)

_KNOWN_MARKET_CODES = tuple(code for code in COMPANY_NAMES if "=" in code)
_KNOWN_MARKET_CODE_PATTERN = "|".join(
    sorted((re.escape(value) for value in _KNOWN_MARKET_CODES),
           key=len, reverse=True))
KNOWN_MARKET_CODE_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:{_KNOWN_MARKET_CODE_PATTERN})(?![A-Za-z0-9])",
    re.I,
)

# 원시 카드에서 새 동적 ticker를 배우는 규칙은 표시 문장 검사보다 의도적으로
# 좁다. URL·U.S.·CXL2.0·내부 key=value를 ticker로 오인하지 않고, 금융 데이터가
# 명시적으로 쓰는 강한 문맥만 인벤토리에 넣는다.
_EXPLICIT_EXCHANGE_ROOT = (
    r"(?:[CDFOVJTX]|[A-Z][A-Za-z0-9]{1,11}(?:-[A-Za-z0-9]{1,8})?|"
    r"\d{2,6}[A-Z][A-Z0-9]{0,5}|\d{4,6})"
)
_EXPLICIT_CONTEXT_ROOT = (
    r"(?:[A-Z][A-Z0-9]{1,11}(?:-[A-Z0-9]{1,8})?|"
    r"\d{2,6}[A-Z][A-Z0-9]{0,5}|\d{4,6})"
)
_EXPLICIT_MARKET_SUFFIXES = (
    "F", "X", "JBTC", "ECI", "STOXX", "RR", "TWEB", "CFXS", "KFTC",
    "EBS", "PBOC", "D3", "TP", "TH", "RASL", "IN", "R", "TE", "ICAP",
    "RTRS", "D4", "LME",
)
_EXPLICIT_MARKET_SUFFIX_PATTERN = "|".join(
    sorted((re.escape(value) for value in _EXPLICIT_MARKET_SUFFIXES),
           key=len, reverse=True))
_GEOGRAPHIC_ABBREVIATION_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]+-)?U\.S\.?", re.I)
_GEOGRAPHIC_FALSE_CODE_RE = re.compile(r"(?:[A-Z]+-)?U\.S", re.I)
_ONE_LETTER_RIC_PATTERN = "|".join(
    re.escape(value) for value in ONE_LETTER_RIC_NAMES)
KNOWN_ONE_LETTER_RIC_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:{_ONE_LETTER_RIC_PATTERN})(?![A-Za-z0-9])")
_REPEATED_INITIALS_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?!(?:{_ONE_LETTER_RIC_PATTERN})\.?)"
    r"(?:[A-Z]\.){2,}(?![A-Za-z0-9])")
_YIELD_CODE_RE = re.compile(
    r"^(?P<country>US|DE|FR|JP)(?P<years>\d+)(?:YT|YTN)$")
_YIELD_COUNTRY_NAMES = {"US": "미국", "DE": "독일", "FR": "프랑스", "JP": "일본"}
_DOLLAR_LITERAL_TOKENS = frozenset({"FILE"})
_READER_DOMAIN_RE = re.compile(
    r"(?<![A-Za-z0-9@])"
    r"(?:[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@)?"
    r"(?:www\.)?[A-Za-z0-9][A-Za-z0-9-]*"
    r"(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}"
    r"(?:[/?#][^\s]*)?"
)
_UNAMBIGUOUS_DOMAIN_TLDS = frozenset({
    "com", "org", "net", "info", "biz", "dev", "tech", "finance",
    "markets", "haus", "gov", "edu", "io", "uk", "mil", "mr", "ai",
    "news",
})
_READER_MEMORY_DEFINITION_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:HBM|LPDDR)=D(?=램)", re.I)
READER_ROUTING_METADATA_RE = re.compile(
    r"(?:\[(?:MKTS/GLOB|O/R|TOP/CMTY|US/|\.N)\]|"
    r"(?<![A-Za-z0-9])\.N(?![A-Za-z0-9]))",
    re.I,
)
_EXPLICIT_SOURCE_PHRASE_RULES = (
    (re.compile(r"엔비디아\s*\(\s*Nvidia\s*\)", re.I), "엔비디아"),
    (re.compile(r"알파벳\s*\(\s*Alphabet\s*\)", re.I), "알파벳"),
    (re.compile(r"구글\s*\(\s*Google\s*\)", re.I), "구글"),
    (re.compile(r"마이크로소프트\s*\(\s*Microsoft\s*\)", re.I),
     "마이크로소프트"),
    (re.compile(r"애플\s*\(\s*Apple\s*\)", re.I), "애플"),
    (re.compile(r"메타\s*\(\s*Meta(?:\s+Platforms)?\s*\)", re.I), "메타"),
    (re.compile(r"(?<![A-Za-z0-9])nVent\s+Electric(?![A-Za-z0-9])", re.I),
     "엔벤트 일렉트릭"),
    (re.compile(
        r"지멘스\s*\(\s*Siemens(?:\s+AG)?\s+SIEGn\.DE\s*\)",
        re.I,
    ), "지멘스"),
    (
        re.compile(
            r"(?<![A-Za-z0-9])(?:유럽\s+기술주\s+)?SX8P\s*\(\s*"
            r"SX8P=STOXX\s+유럽\s+기술업종\s*\)",
            re.I,
        ),
        "유럽 기술주 지수",
    ),
    (re.compile(r"(?<![A-Za-z0-9])DDR5=PC(?=·서버용\s+D램)", re.I),
     "DDR5는 PC"),
    (re.compile(r"(?<![A-Za-z0-9])DDR=D(?=램)", re.I), "DDR은 D"),
    (re.compile(
        r"(?<![A-Za-z0-9])(?P<family>HBM|LPDDR)=D(?=램)", re.I,
    ), r"\g<family>은 D"),
    (re.compile(r"(?<![A-Za-z0-9])Y2=HBM(?=\s*공장)", re.I), "신규 HBM"),
    (re.compile(r"(?<![A-Za-z0-9])WTI\s+CL=F(?![A-Za-z0-9])", re.I),
     "WTI 원유"),
    (re.compile(
        r"(?<![A-Za-z0-9])(?:Siemens(?:\s+AG)?|지멘스)\s+SIEGn\.DE"
        r"(?![A-Za-z0-9])",
        re.I,
    ), "지멘스"),
)

_LEADING_DOT_INDEX_ALIASES = {
    "N225": ("닛케이 225", "Nikkei 225", "Nikkei"),
    "TOPX": ("Topix",),
    "KS11": ("코스피(KOSPI)", "코스피"),
    "TWII": ("대만 가권지수", "TAIEX"),
    "SSEC": ("상하이 종합지수", "Shanghai Composite"),
    "STOXX": (
        "European STOXX 600",
        "STOXX Europe 600",
        "범유럽 STOXX 600 지수",
        "유럽 STOXX 600 지수",
    ),
    "MILA00000PUS": ("MSCI 라틴 아메리카 주식 지수",),
    "MIMS00000PUS": ("MSCI 아시아 신흥국 주가지수",),
    "MIMS0IT00PUS": ("EM 아시아 IT 지수",),
    "CSI930713": ("중국 CSI 인공지능 지수",),
    "CSI931865": ("중국 CSI 반도체 지수",),
    "CSI931079": ("중국 CSI 5G 통신 지수",),
    "MISU00000PUS": ("MSCI 광범위 ASEAN 지수",),
    "CSI300": ("CSI300 지수",),
    "SX8P": ("유럽 기술주", "유럽 기술업종"),
    "MIWO00000PUS": ("MSCI All Country World Index", "MSCI ACWI"),
    "MILA00000CU": ("MSCI Latin America Currency Index",),
    "CSI399976": ("신에너지 자동차 섹터",),
    "CSI399986": ("은행 섹터",),
    "CSI930598": ("희토류 섹터",),
    "FCHI": ("CAC 40",),
    "GDAXI": ("DAX",),
    "SPLRCL": ("커뮤니케이션 서비스",),
    "SPLRCT": ("S&P 500 정보기술 부문", "S&P 500 기술 섹터"),
    "STAR50": ("STAR50 지수",),
}

_MARKET_DISPLAY_ALIASES = {
    "DX-Y": ("달러지수", "달러인덱스"),
    "GSPC": ("S&P 500", "S&P500"),
    "IXIC": ("나스닥", "나스닥종합"),
    "TNX": ("미국 10년물 금리",),
    "CL=F": ("원유", "WTI", "WTI유가"),
    "CL": ("원유", "WTI", "WTI유가"),
    "KRW=X": ("원·달러", "원달러"),
    "JPY=X": ("엔·달러", "엔달러"),
    "JPY": ("엔화",),
    "EUR": ("유로화",),
    "NVDA": ("Nvidia Corporation", "Nvidia"),
    "META": (
        "Meta Platforms, Inc.", "Meta Platforms Inc", "Meta", "메타 플랫폼스",
    ),
    "GOOGL": ("Alphabet Inc.", "구글", "Google"),
    "GOOG": ("Alphabet Inc.", "구글", "Google"),
    "ORCL": ("Oracle Corp", "Oracle"),
    "AVGO": ("Broadcom Inc.", "Broadcom"),
    "AMZN": ("Amazon Web Services", "Amazon.com", "Amazon", "아마존닷컴"),
    "MU": ("마이크론 테크놀로지", "Micron Technology",),
    "MRVL": ("Marvell Technology", "Marvell"),
    "WDC": ("Western Digital", "웨스턴 디지털"),
    "035420": ("네이버", "Naver"),
    "SNDK": ("SanDisk Corporation", "SanDisk", "Sandisk"),
    "CRWV": ("CoreWeave", "코어Weave", "코어위브"),
    "SHOP": ("Shopify",),
    "SPCX": ("스페이스X", "SpaceX"),
    "0981": ("SMIC",),
    "285A": ("Kioxia",),
    "RIO": ("Rio Tinto",),
    "0285": ("BYD",),
    "002594": ("BYD",),
    "9888": ("Baidu",),
    "BIDU": ("Baidu",),
    "7203": ("Toyota Motor", "Toyota"),
    "TM": ("Toyota Motor", "Toyota"),
    "1398": ("ICBC",),
    "601398": ("ICBC",),
    "BABA": ("Alibaba",),
    "TEAM": ("아틀라시안", "Atlassian"),
    "MCHP": ("마이크로칩 Tech", "Microchip Technology", "Microchip"),
    "NEE": ("넥스트에라 에너지", "NextEra Energy"),
    "NYT": ("뉴욕타임스", "New York Times"),
    "MTZ": ("MasTec",),
    "KLAR": ("Klarna Group", "Klarna"),
    "APPL": ("애플", "Apple"),
    "9984": ("소프트뱅크", "SoftBank"),
    "9432": ("NTT",),
    "RHM": ("라인메탈", "Rheinmetall"),
    "GFS": ("GlobalFoundries",),
    "CBRS": ("세레브라스 시스템즈", "Cerebras Systems Inc", "Cerebras Systems"),
    "CRBS": ("세레브라스 시스템즈", "Cerebras Systems Inc", "Cerebras Systems"),
    "MS": ("Morgan Stanley",),
    "NOW": ("ServiceNow",),
    "688825": ("CXMT Corp", "CXMT"),
    "VZ": ("Verizon",),
    "ON": ("Onsemi", "ON Semiconductor"),
    "2330": ("Taiwan Semiconductor Manufacturing Co", "Taiwan Semiconductor", "TSMC"),
    "0700": ("Tencent",),
    "688836": ("Unitree",),
    "9618": ("JD.com",),
    "JD": ("JD.com",),
    "601939": ("China Construction Bank Corp", "China Construction Bank", "CCB"),
    "0939": ("China Construction Bank Corp", "China Construction Bank", "CCB"),
    "UPS": ("United Parcel Service",),
    "STLAM": ("Stellantis",),
    "STLA": ("Stellantis",),
    "GM": ("General Motors",),
    "7267": ("Honda",),
    "HMC": ("Honda",),
    "ALP": ("Alpha Compute",),
    "APLD": ("Applied Digital",),
    "BKNG": ("Booking Holdings",),
    "BMWG": ("BMW",),
    "CAT": ("Caterpillar",),
    "DBSM": ("DBS Group",),
    "DE": ("Deere",),
    "ENB": ("Enbridge",),
    "ETN": ("Eaton",),
    "EVRG": ("Evergy",),
    "HPQ": ("HP",),
    "HUT": ("Hut 8",),
    "LEGD": ("Legrand",),
    "LIN": ("Linde",),
    "LNT": ("Alliant Energy",),
    "MPWR": ("Monolithic Power Systems",),
    "MSTR": ("Strategy",),
    "NBIS": ("Nebius Group", "Nebius"),
    "OOGL": ("Alphabet",),
    "SHEL": ("Shell",),
    "SHW": ("Sherwin-Williams",),
    "SO": ("Southern Company", "Southern Company's"),
    "TTWO": ("Take-Two Interactive Software", "Take-Two Interactive"),
    "TXN": ("Texas Instruments",),
    "VOWG": ("Volkswagen",),
    "WMT": ("Walmart",),
    "XOM": ("Exxon Mobil", "ExxonMobil"),
    "BRKA": ("Berkshire Hathaway",),
    "BRK": ("Berkshire Hathaway",),
    "601398": ("Industrial and Commercial Bank of China", "ICBC"),
    "1398": ("Industrial and Commercial Bank of China", "ICBC"),
    "REP": ("Repsol",),
    "TSEM": ("Tower Semiconductor",),
    "KSP": ("Kingspan", "킨스판"),
    "D.N": ("Dominion Energy",),
    "USD": ("달러", "달러화", "달러 인덱스"),
    "KRW": ("원화", "원·달러", "원달러"),
    "PHP": ("필리핀 페소",),
}
EXPLICIT_EXCHANGE_TICKER_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<code>{_EXPLICIT_EXCHANGE_ROOT}\."
    rf"(?:{_EXCHANGE_SUFFIX_PATTERN}))(?![A-Za-z0-9])")
GLUED_ALPHA_TICKER_RE = re.compile(
    rf"(?<=[a-z])(?P<code>[A-Z][A-Z0-9]{{1,10}}(?:[a-z])?"
    rf"(?:-[A-Z0-9]{{1,8}})?\.(?:{_EXCHANGE_SUFFIX_PATTERN}))"
    rf"(?![A-Za-z0-9])")
_DUPLICATED_WORDMARK_ROOT_PATTERN = "|".join(sorted(
    (re.escape(code) for code in COMPANY_NAMES
     if re.fullmatch(r"[A-Z][A-Z0-9]{1,10}", code)),
    key=len,
    reverse=True,
))
GLUED_DUPLICATED_WORDMARK_RIC_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<label>(?:{_DUPLICATED_WORDMARK_ROOT_PATTERN}))"
    rf"(?P<code>(?P=label)\.(?:{_EXCHANGE_SUFFIX_PATTERN}))"
    rf"(?![A-Za-z0-9])"
)
GLUED_KOREAN_TICKER_RE = re.compile(
    rf"(?P<label>[가-힣][가-힣·]{{1,40}})"
    rf"(?P<code>[A-Z][A-Z0-9]{{1,10}}(?:[a-z])?"
    rf"(?:-[A-Z0-9]{{1,8}})?\.(?:{_EXCHANGE_SUFFIX_PATTERN}))"
    rf"(?![A-Za-z0-9])"
)
GLUED_NUMERIC_TICKER_RE = re.compile(
    rf"(?<=[A-Za-z])(?P<code>\d{{4,6}}\."
    rf"(?:{_EXCHANGE_SUFFIX_PATTERN}))(?![A-Za-z0-9])")
# wordmark와 다른 known ticker가 붙은 경우는 확인된 ``표시명+코드``
# pair 전체만 인식한다. ticker suffix만 찾으면 MAGS.P를 GS.P로, ABX.TO를
# BX.TO로 잘라 사실을 훼손할 수 있다.
_KNOWN_ALIAS_GLUE_PAIRS = tuple(sorted({
    (code, alias)
    for code, display in {**COMPANY_NAMES, **DOLLAR_TICKER_NAMES}.items()
    if re.fullmatch(r"[A-Z][A-Z0-9]{1,11}", code)
    for alias in (display, *_MARKET_DISPLAY_ALIASES.get(code, ()))
    if alias and len(alias) <= 80
    and re.sub(r"[^A-Za-z0-9가-힣]", "", alias).upper() != code.upper()
}, key=lambda item: -(len(item[0]) + len(item[1]))))
GLUED_KNOWN_ALIAS_TICKER_RES = tuple(
    re.compile(
        rf"(?<![A-Za-z0-9가-힣])(?P<label>{re.escape(alias)})"
        rf"(?P<code>{re.escape(code)}\.(?:{_EXCHANGE_SUFFIX_PATTERN}))"
        rf"(?![A-Za-z0-9])",
        re.I,
    )
    for code, alias in _KNOWN_ALIAS_GLUE_PAIRS
)
EXPLICIT_MARKET_TICKER_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<code>[A-Z^][A-Z0-9^.-]{{1,15}}="
    rf"(?:{_EXPLICIT_MARKET_SUFFIX_PATTERN}))(?![A-Za-z0-9])")
_EMPTY_MARKET_ROOT_PATTERN = "|".join(
    sorted((re.escape(value) for value in EMPTY_MARKET_CODE_NAMES),
           key=len, reverse=True))
EXPLICIT_EMPTY_MARKET_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<code>(?:{_EMPTY_MARKET_ROOT_PATTERN})=)"
    rf"(?![A-Za-z0-9])")
EXPLICIT_PREFIXED_EMPTY_MARKET_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<code>=(?:{_EMPTY_MARKET_ROOT_PATTERN}))"
    rf"(?![A-Za-z0-9])")
EXPLICIT_CARET_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<code>\^[A-Z][A-Z0-9.-]{1,15})(?![A-Za-z0-9])")
_LEADING_DOT_INDEX_PATTERN = "|".join(
    sorted((re.escape(value) for value in LEADING_DOT_INDEX_NAMES),
           key=len, reverse=True))
EXPLICIT_LEADING_DOT_INDEX_RE = re.compile(
    rf"(?<![A-Za-z0-9.])(?P<code>(?:"
    rf"\.(?:{_LEADING_DOT_INDEX_PATTERN})"
    rf"(?=(?:으로|은|는|이|가|을|를|과|와|로)(?![A-Za-z가-힣])|$|[^A-Za-z0-9가-힣])|"
    r"\.(?!(?:NET)(?![A-Z0-9]))[A-Z][A-Z0-9]{1,15}"
    r"(?=(?:으로|은|는|이|가|을|를|과|와|로)(?![A-Za-z가-힣])|$|[^A-Za-z0-9가-힣])))")
EXPLICIT_BRACKETED_INDEX_RE = re.compile(
    rf"(?P<open>[<(])\s*(?P<code>(?:\.(?!(?:NET)(?![A-Z0-9]))"
    rf"[A-Z][A-Z0-9]{{1,15}}|(?:{_LEADING_DOT_INDEX_PATTERN})))"
    rf"\s*(?P<close>[)>])",
)
EXPLICIT_DOLLAR_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])\$(?P<code>[A-Z][A-Z0-9]{0,7})"
    r"(?![A-Za-z0-9])")
READER_DOLLAR_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])\$(?P<code>[A-Z][A-Z0-9]{0,7})(?![A-Za-z0-9])")
_ALGEBRA_VARIABLE_CASHTAG_RE = re.compile(
    r"(?<![A-Za-z0-9])\$(?P<code>[XYZ])(?![A-Za-z0-9])")
PREFIXED_EXCHANGE_TICKER_RE = re.compile(
    r"\(\s*(?:NASDAQ|NYSE|AMEX|KRX|KOSPI|KOSDAQ)\s*:\s*"
    r"(?P<code>[A-Z][A-Z0-9.-]{0,15})\s*\)",
    re.I,
)


def _algebra_variable_cashtag_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Recognize the common paired ``$X``/``$Y`` explanatory variables."""
    matches = tuple(_ALGEBRA_VARIABLE_CASHTAG_RE.finditer(text))
    codes = {match.group("code") for match in matches}
    return tuple(match.span() for match in matches) if {"X", "Y"} <= codes else ()


def _naturalize_algebra_variables(text: str) -> str:
    spans = set(_algebra_variable_cashtag_spans(text))
    if not spans:
        return text
    return _ALGEBRA_VARIABLE_CASHTAG_RE.sub(
        lambda match: (f"변수 {match.group('code')}"
                       if match.span() in spans else match.group(0)),
        text,
    )
EXPLICIT_CONTEXT_TICKER_RE = re.compile(
    rf"(?:(?i:ticker)|종목\s*코드)(?:\s*[:：]\s*|\s+)(?P<code>"
    rf"{_EXPLICIT_CONTEXT_ROOT}(?:\.(?:{_EXCHANGE_SUFFIX_PATTERN}))?"
    rf"|[A-Z^][A-Z0-9^.-]{{1,15}}=[A-Z]{{1,8}}"
    rf"|\^[A-Z][A-Z0-9.-]{{1,15}})(?![A-Za-z0-9])")

_LEGITIMATE_COMPANY_PHRASES = (
    "Meta Platforms", "Lam Research Corporation", "Lam Research",
    "Applied Materials Inc", "Applied Materials", "Micron Technology",
)
_BARE_WORDMARK_TICKERS = frozenset({
    "AMD", "IBM", "SAP", "ARM", "ASML", "KLA", "KKR", "WLFI", "YLDS",
})

_GLOBAL_SAFE_READER_NAMES = {
    **GLOBAL_COMPANY_NAME_ALIASES,
    **ONE_LETTER_RIC_NAMES,
    **{
        code: company for code, company in COMPANY_NAMES.items()
        if "." in code or "=" in code
    },
}
_GLOBAL_SAFE_READER_NAMES_UPPER = {
    code.upper(): company for code, company in _GLOBAL_SAFE_READER_NAMES.items()
}
_GLOBAL_SAFE_NAME_PATTERN = "|".join(
    re.escape(code) for code in sorted(
        _GLOBAL_SAFE_READER_NAMES, key=len, reverse=True)
)
_GLOBAL_SAFE_PAREN_RE = re.compile(
    rf"\(\s*(?P<name>{_GLOBAL_SAFE_NAME_PATTERN})\s*\)", re.I)
_GLOBAL_SAFE_TOKEN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<name>{_GLOBAL_SAFE_NAME_PATTERN})"
    rf"(?![A-Za-z0-9])", re.I)
_GLOBAL_BARE_TICKER_PATTERN = "|".join(
    re.escape(code) for code in sorted(
        GLOBAL_BARE_TICKER_NAMES, key=len, reverse=True)
)
_GLOBAL_BARE_PAREN_RE = re.compile(
    rf"\(\s*(?P<name>{_GLOBAL_BARE_TICKER_PATTERN})"
    rf"(?:-[AB])?(?:\.(?:{_EXCHANGE_SUFFIX_PATTERN}))?\s*\)")
_GLOBAL_BARE_TOKEN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<name>{_GLOBAL_BARE_TICKER_PATTERN})"
    rf"(?:-[AB])?(?:\.(?:{_EXCHANGE_SUFFIX_PATTERN}))?"
    rf"(?:(?![A-Za-z0-9.=])|(?=\.(?:\s|$)))")

_STATIC_READER_NAMES = tuple(sorted({
    *COMPANY_NAMES.values(),
    *NUMERIC_TICKER_NAMES.values(),
    *DOLLAR_TICKER_NAMES.values(),
    *EMPTY_MARKET_CODE_NAMES.values(),
    *LEADING_DOT_INDEX_NAMES.values(),
}, key=len, reverse=True))
_STATIC_READER_NAME_PATTERN = "|".join(
    re.escape(name) for name in _STATIC_READER_NAMES if name)
_REPEATED_READER_NAME_RE = re.compile(
    rf"(?<![A-Za-z0-9가-힣])(?P<name>{_STATIC_READER_NAME_PATTERN})"
    rf"(?:\s+(?P=name))+(?P<particle>으로|에서|은|는|이|가|을|를|"
    rf"에|의|과|와|도|만|로)?(?=$|[^A-Za-z0-9가-힣])",
    re.I,
)
_GLUED_REPEATED_READER_NAME_RE = re.compile(
    rf"(?<![A-Za-z0-9가-힣])(?P<name>{_STATIC_READER_NAME_PATTERN})(?P=name)"
    rf"(?P<particle>으로|에서|은|는|이|가|을|를|에|의|과|와|도|만|로)?"
    rf"(?=$|[^A-Za-z0-9가-힣])",
    re.I,
)
_PAREN_REPEATED_READER_NAME_RE = re.compile(
    rf"(?<![A-Za-z0-9가-힣])(?P<name>{_STATIC_READER_NAME_PATTERN})\s*"
    rf"\(\s*(?P=name)(?:\s+(?P=name))*\s*\)"
    rf"(?P<particle>으로|에서|은|는|이|가|을|를|에|의|과|와|도|만|로)?"
    rf"(?=$|[^A-Za-z0-9가-힣])",
    re.I,
)
_STOCK_REPEATED_READER_NAME_RE = re.compile(
    rf"(?<![A-Za-z0-9가-힣])(?P<name>{_STATIC_READER_NAME_PATTERN})"
    rf"\s+Stock\s*(?:-\s*)?(?P=name)"
    rf"(?=$|[^A-Za-z0-9가-힣])",
    re.I,
)
_DELIMITED_REPEATED_READER_NAME_RE = re.compile(
    rf"(?<![A-Za-z0-9가-힣])(?P<name>{_STATIC_READER_NAME_PATTERN})"
    rf"(?P<separator>\s*[|/]\s*)(?P=name)(?=[|/]|$)",
    re.I,
)
_PAREN_REPEATED_READER_NAME_WITH_NUMBER_RE = re.compile(
    rf"(?<![A-Za-z0-9가-힣])(?P<name>{_STATIC_READER_NAME_PATTERN})\s*"
    rf"\(\s*(?P=name)\s+(?P<detail>[+-]?\d[\d,.]*\s*%[^()]*)\)",
    re.I,
)
_NUMERIC_PARTICLE_RE = re.compile(
    r"(?P<stem>\d[\d,.]*)(?P<particle>으로|은|는|이|가|을|를|과|와|로)"
    r"(?=$|[^A-Za-z가-힣])"
)


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
    if root.isdigit() or len(root) == 1:
        return (clean,) if clean != root else ()
    return tuple(dict.fromkeys((clean, root)))


def reader_identity(raw_name: object, *, kind: str = "stock") -> ReaderIdentity:
    """원본 이름에서 표시명·허용 alias·실제로 숨길 ticker를 한 번에 계산한다."""
    clean = _clean(raw_name) or "관련 대상"
    match = TICKER_SUFFIX_RE.search(clean)
    if match and kind != "stock":
        raw_code = match.group("ticker")
        code = raw_code.upper()
        code_root = re.split(r"[.\-=]", code, maxsplit=1)[0]
        code_root = code_root.split("-", 1)[0]
        mapped_display = (
            COMPANY_NAMES.get(code)
            or COMPANY_NAMES.get(code_root)
            or DOLLAR_TICKER_NAMES.get(code_root)
        )
        raw_base = clean[:match.start()].strip()
        aliases = {
            mapped_display or "",
            *_MARKET_DISPLAY_ALIASES.get(code, ()),
            *_MARKET_DISPLAY_ALIASES.get(code_root, ()),
        }
        normalize = lambda value: re.sub(  # noqa: E731
            r"[^A-Za-z0-9가-힣]", "", value).casefold()
        base_is_same_company = bool(
            raw_base and any(
                normalize(raw_base) == normalize(alias)
                for alias in aliases if alias
            )
        )
        if raw_code in NON_TICKER_ACRONYMS or raw_code in MIXED_CASE_TECH_ACRONYMS:
            match = None
        elif (not re.search(r"[0-9.=^$]", code)
              and not base_is_same_company):
            # sector의 ``유럽 자동차(DE)``·``일반 상품(CAT)``는 회사
            # ticker와 철자가 같아도 설명용 약어다. non-stock 이름에서는
            # 거래소/숫자처럼 자체로 명백한 시장 코드만 제거한다.
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
        display = replace_company_names(display)
    display = replace_qualified_tickers(display)
    display = KNOWN_RIC_RE.sub("", display)
    display = KNOWN_HYPHEN_TICKER_RE.sub("", display)
    display = re.sub(r"엔터프라이즈", "기업용", display)
    display = re.sub(r"레거시", "구형", display)
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
    # 거래소 접미사가 없는 beneficiary 말미의 코드는 AI·IT·ADR처럼
    # 일반 약어와 구분할 수 없다. 보고서 전체의 bare token을 금지하지
    # 않고 출처 이름에 나타난 괄호 표기만 구조적으로 숨긴다.
    structural_bare_ticker = bool(
        ticker
        and ticker == root
        and (
            len(root) <= 2
            or root in NON_TICKER_ACRONYMS
            or _token_is_part_of_name(root, (base,))
        )
    )
    if structural_bare_ticker:
        forbidden.append(f"({ticker})")
    for token in (() if structural_bare_ticker else ticker_tokens(ticker)):
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


def replace_ticker_token(
        text: str, ticker: str, replacement: str = "", *,
        ignore_case: bool = True) -> str:
    return re.sub(
        rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])",
        replacement,
        text,
        flags=re.I if ignore_case else 0,
    )


def repair_korean_particles(
        text: str, *, nouns: Iterable[str] = ()) -> str:
    """자연어 치환 뒤 알려진 명사와 조사의 공백·받침 호응을 교정한다."""
    choices = {
        "은": ("은", "는"),
        "는": ("은", "는"),
        "이": ("이", "가"),
        "가": ("이", "가"),
        "을": ("을", "를"),
        "를": ("을", "를"),
        "과": ("과", "와"),
        "와": ("과", "와"),
    }

    def corrected(stem: str, particle: str) -> str:
        pronunciation_stem = stem.rstrip()
        # ``보고서(Annual Review)는``처럼 영문 보충 설명 뒤의 조사는
        # 바깥 한국어 명사를 기준으로 고른다.
        parenthesized = re.search(
            r"(?P<outer>[가-힣]+)\([^()]*\)$", pronunciation_stem)
        if parenthesized:
            pronunciation_stem = parenthesized.group("outer")
        last = pronunciation_stem[-1]
        if pronunciation_stem.upper() == "3M":
            jongseong = 1
        elif "가" <= last <= "힣":
            jongseong = (ord(last) - 0xAC00) % 28
        elif last.isdigit():
            # 한국어 숫자 읽기의 마지막 음절 받침: 영·일·삼·육·칠·팔.
            jongseong = 8 if last in "178" else (1 if last in "036" else 0)
        elif (pronunciation_stem.isupper()
              and re.fullmatch(
                  r"[A-Z][A-Z0-9&.-]*", pronunciation_stem)):
            # IREN(아이렌)·ASML(에이에스엠엘)처럼 대문자 wordmark는
            # 마지막 알파벳 이름의 한국어 받침으로 조사 호응을 정한다.
            jongseong = 1 if last.upper() in "FHLMNRSX" else 0
        else:
            return particle
        if particle in {"으로", "로"}:
            return "으로" if jongseong not in {0, 8} else "로"
        with_batchim, without_batchim = choices[particle]
        return with_batchim if jongseong else without_batchim

    def replace(match: re.Match) -> str:
        stem = match.group("stem")
        particle = match.group("particle")
        return stem + corrected(stem, particle)

    text = _NUMERIC_PARTICLE_RE.sub(replace, text)

    known_nouns = {
        *COMPANY_NAMES.values(),
        *DOLLAR_TICKER_NAMES.values(),
        *EMPTY_MARKET_CODE_NAMES.values(),
        *LEADING_DOT_INDEX_NAMES.values(),
        *(str(noun).strip() for noun in nouns if str(noun).strip()),
    }
    for aliases in _LEADING_DOT_INDEX_ALIASES.values():
        known_nouns.update(aliases)
    pattern = _particle_noun_pattern(tuple(sorted(
        (noun for noun in known_nouns if noun), key=lambda item: (-len(item), item)
    )))
    return pattern.sub(replace, text) if pattern else text


@lru_cache(maxsize=128)
def _particle_noun_pattern(nouns: tuple[str, ...]) -> re.Pattern | None:
    if not nouns:
        return None
    alternatives = "|".join(re.escape(noun) for noun in nouns)
    return re.compile(
        rf"(?<![A-Za-z0-9가-힣])(?P<stem>{alternatives})"
        rf"(?P<particle>으로|은|는|이|가|을|를|과|와|로)"
        rf"(?=$|[^A-Za-z가-힣])",
        re.I,
    )


def collapse_repeated_reader_names(text: str) -> str:
    """여러 치환 단계가 같은 canonical 표시명을 연달아 만든 경우 하나로 접는다."""
    def replace(match: re.Match) -> str:
        return match.group("name") + (match.group("particle") or "")

    text = _GLUED_REPEATED_READER_NAME_RE.sub(replace, text)
    text = _PAREN_REPEATED_READER_NAME_RE.sub(replace, text)
    text = _STOCK_REPEATED_READER_NAME_RE.sub(
        lambda match: f"{match.group('name')} 주식", text)
    text = _DELIMITED_REPEATED_READER_NAME_RE.sub(
        lambda match: match.group("name"), text)
    text = _PAREN_REPEATED_READER_NAME_WITH_NUMBER_RE.sub(
        lambda match: f"{match.group('name')}({match.group('detail').strip()})",
        text,
    )
    text = _REPEATED_READER_NAME_RE.sub(replace, text)
    return collapse_repeated_company_headers(text)


def _is_reader_domain_literal(value: str) -> bool:
    """Ticker와 구분 가능한 웹/이메일 문맥만 domain으로 보존한다.

    `VRT.DE`와 `example.de`는 형태가 겹친다. 따라서 email·path·query,
    여러 단계 hostname, 소문자 domain, 거래소와 겹치지 않는 TLD를
    명시적 근거로 삼고 전부 대문자인 모호한 `.CO`·`.US`는 ticker로 남겨 둔다.
    """
    match = _READER_DOMAIN_RE.fullmatch(value.strip())
    if not match:
        return False
    raw = match.group(0)
    head = re.split(r"[/?#]", raw, maxsplit=1)[0]
    has_tail = len(head) != len(raw)
    has_email = "@" in head
    host = head.rsplit("@", 1)[-1]
    if host.lower().startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) < 2 or not (2 <= len(labels[-1]) <= 24):
        return False
    root = labels[-2]
    suffix = labels[-1]
    if (suffix.upper() in _EXCHANGE_SUFFIXES
            and (
                root.upper() in COMPANY_NAMES
                or re.search(
                    r"[a-z](?:[A-Z][A-Z0-9]{1,10}(?:[a-z])?|\d{4,6})$",
                    root,
                )
            )):
        return False
    # Reuters의 유사 RIC은 회사 코드 끝에 소문자 주식 종류를 두기도
    # 한다(`SIEGn.DE`, `ENR1n.DE`). Title-case domain과 구분한다.
    if re.fullmatch(
            rf"[A-Z][A-Z0-9]{{1,11}}[a-z]\.(?:{_EXCHANGE_SUFFIX_PATTERN})",
            host):
        return False
    if has_tail or has_email or len(labels) >= 3:
        return True
    if labels[-1].lower() in _UNAMBIGUOUS_DOMAIN_TLDS:
        return True
    return any(character.islower() for character in host)


def _reader_domain_spans(text: str) -> tuple[tuple[int, int], ...]:
    return tuple(
        match.span() for match in _READER_DOMAIN_RE.finditer(text)
        if _is_reader_domain_literal(match.group(0))
    )


def is_reader_literal_token(value: str) -> bool:
    """괄호 안에서도 보존해야 하는 지리 약어·출처 도메인인지 판별한다."""
    clean = value.strip()
    return bool(
        _GEOGRAPHIC_ABBREVIATION_RE.fullmatch(clean)
        or _is_reader_domain_literal(clean)
        or _REPEATED_INITIALS_RE.fullmatch(clean)
    )


def protect_reader_literals(text: str) -> tuple[str, list[tuple[str, str]]]:
    protected: list[tuple[str, str]] = []

    def protect(match: re.Match) -> str:
        marker = f"〔보존문구{len(protected)}〕"
        protected.append((marker, match.group(0)))
        return marker

    result = _GEOGRAPHIC_ABBREVIATION_RE.sub(protect, text)

    def protect_domain(match: re.Match) -> str:
        return protect(match) if _is_reader_domain_literal(match.group(0)) else match.group(0)

    result = _READER_DOMAIN_RE.sub(protect_domain, result)
    result = _REPEATED_INITIALS_RE.sub(protect, result)
    return result, protected


def restore_reader_literals(
        text: str, protected: Iterable[tuple[str, str]]) -> str:
    for marker, original in protected:
        text = text.replace(marker, original)
    return text


def replace_qualified_tickers(text: str, replacement: str = "") -> str:
    """거래소 ticker만 치환하고 지리 약어·출처 도메인은 그대로 보존한다."""
    protected_text, protected = protect_reader_literals(text)
    result = QUALIFIED_TICKER_RE.sub(replacement, protected_text)
    return restore_reader_literals(result, protected)


def replace_company_names(text: str) -> str:
    """알려진 회사·지표 코드를 읽는 이름으로 바꾸되 URL은 원형을 보존한다."""
    # 잘린 Reuters 문장 끝의 ``(MU.`` 같은 미완성 ticker 주석은 회사명으로
    # 풀기 전에 원자적으로 걷어낸다. 괄호와 회사명이 따로 남는 일을 막는다.
    text = _reader_re_sub(
        rf"\s*\(\s*\$?(?:{_GLOBAL_BARE_TICKER_PATTERN})\.?\s*$",
        "",
        text,
        flags=re.I,
    )

    # 영문 회사명이 곧바로 자기 ticker를 설명하는 두 vendor 포맷은 회사명
    # 하나로 접는다. 소유격은 한국어 조사로 바꾸고, 내부 증권사 wrapper는
    # 독자 문장에 노출하지 않는다.
    for code, display in GLOBAL_BARE_TICKER_NAMES.items():
        aliases = _display_aliases(code, display)
        for alias in aliases:
            text = _reader_re_sub(
                rf"{re.escape(alias)}\s*[’']s\s*\(\s*{re.escape(code)}\s*\)",
                f"{display}의",
                text,
                flags=re.I,
            )
            text = _reader_re_sub(
                rf"{re.escape(alias)}\s*\(\s*"
                rf"(?:NASDAQ|NYSE|AMEX|KRX|KOSPI|KOSDAQ)\s*:\s*"
                rf"{re.escape(code)}\s*\|\s*{re.escape(code)}\s+"
                r"Price\s+Prediction\s*\)",
                display,
                text,
                flags=re.I,
            )

    # ``아마존 웹 서비스(Amazon Web Services)``처럼 양쪽이 같은 회사를
    # 가리키면 영문 설명을 제거한다. 정규화한 한국어 이름이 일치하는 경우에
    # 한정해 일반적인 번역·용어 괄호는 보존한다.
    english_aliases = {
        alias: display
        for alias, display in GLOBAL_COMPANY_NAME_ALIASES.items()
        if re.search(r"[A-Za-z]", alias)
    }
    if english_aliases:
        alias_pattern = "|".join(
            re.escape(alias) for alias in sorted(
                english_aliases, key=len, reverse=True)
        )
        bilingual = _compiled_reader_pattern(
            rf"(?P<label>[가-힣][가-힣 ]{{1,60}})"
            rf"\(\s*(?P<alias>{alias_pattern})\s*\)",
            re.I,
        )

        def collapse_bilingual_company(match: re.Match) -> str:
            label = match.group("label")
            display = english_aliases.get(match.group("alias"))
            if display is None:
                display = next((
                    mapped for alias, mapped in english_aliases.items()
                    if alias.casefold() == match.group("alias").casefold()
                ), "")
            normalize = lambda value: re.sub(  # noqa: E731
                r"[^A-Za-z0-9가-힣]", "", value).casefold()
            return (label if display and normalize(label).endswith(normalize(display))
                    else match.group(0))

        text = bilingual.sub(collapse_bilingual_company, text)

    text, protected = protect_reader_literals(text)
    def replace_safe(match: re.Match) -> str:
        return _GLOBAL_SAFE_READER_NAMES_UPPER[match.group("name").upper()]

    def replace_bare(match: re.Match) -> str:
        return GLOBAL_BARE_TICKER_NAMES[match.group("name")]

    text = _GLOBAL_SAFE_PAREN_RE.sub(replace_safe, text)
    text = _GLOBAL_SAFE_TOKEN_RE.sub(replace_safe, text)
    text = _GLOBAL_BARE_PAREN_RE.sub(replace_bare, text)
    text = _GLOBAL_BARE_TOKEN_RE.sub(replace_bare, text)
    return restore_reader_literals(text, protected)


def source_ticker_replacements(items: Iterable[tuple[object, str]]) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for raw_name, kind in items:
        identity = reader_identity(raw_name, kind=kind)
        for token in identity.forbidden_tokens:
            replacements[token] = identity.display_name
    return replacements


def _iter_source_strings(value: object, *, field: str = ""):
    """읽기 결과와 URL을 제외한 원시 카드 문자열만 순회한다."""
    if field in {"brief", "readerCopy", "url"}:
        return
    if isinstance(value, str):
        yield value
        return
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_source_strings(item, field=str(key))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_source_strings(item, field=field)


def _explicit_ticker_parts(raw_code: str) -> tuple[str, str, str]:
    full = raw_code.strip().lstrip("$").upper()
    if full.startswith("^"):
        root = full[1:]
        generic = "해당 시장 지표"
    elif full.startswith("."):
        root = full[1:]
        generic = "해당 시장 지표"
    elif full.startswith("="):
        root = full[1:]
        generic = "해당 시장 지표"
    elif "=" in full:
        root = full.split("=", 1)[0]
        generic = "해당 시장 지표"
    else:
        root = full.split(".", 1)[0]
        generic = "해당 기업"
    yield_match = _YIELD_CODE_RE.fullmatch(root)
    yield_display = (
        f"{_YIELD_COUNTRY_NAMES[yield_match.group('country')]} "
        f"{int(yield_match.group('years'))}년물 국채금리"
        if yield_match else ""
    )
    display = (
        COMPANY_NAMES.get(full)
        or COMPANY_NAMES.get(root)
        or NUMERIC_TICKER_NAMES.get(root)
        or ONE_LETTER_RIC_NAMES.get(full)
        or EMPTY_MARKET_CODE_NAMES.get(root)
        or LEADING_DOT_INDEX_NAMES.get(root)
        or DOLLAR_TICKER_NAMES.get(root)
        or yield_display
        or generic
    )
    return full, root, display


_SOURCE_LABEL_STOPWORDS = frozenset({
    "오늘", "시장", "주가", "회사", "기업", "투자자", "지수", "종목",
    "데이터", "관련", "해당", "매출", "실적", "전망", "수요", "공급",
    "이어", "이어진", "각각", "다음으로", "반면", "또", "이후",
})

_GENERIC_BILINGUAL_LABEL_ENDINGS = frozenset({
    "가격", "개념", "경제", "공급", "기사", "기술", "뉴스", "데이터",
    "매출", "발표", "보고서", "산업", "설명", "서비스", "섹터", "수요",
    "시장", "실적", "업무", "업종", "용어", "전망", "제품", "절차", "회의",
    "행사",
    "주가", "지표", "투자",
})
_ENGLISH_COMPANY_GLOSS_WORDS = frozenset({
    "ag", "bank", "bancorp", "company", "corp", "corporation", "energy",
    "devices", "electronics", "financial", "group", "holdings", "inc", "limited", "ltd",
    "materials", "networks", "nv", "plc", "power", "sa", "se", "securities",
    "semiconductor", "service", "services", "systems", "technologies",
    "technology", "telecom",
})
_BILINGUAL_COMPANY_GLOSS_RE = re.compile(
    r"\(\s*(?P<gloss>[A-Z][A-Za-z0-9&.,'’\-]*"
    r"(?:\s+(?:[A-Z][A-Za-z0-9&.,'’\-]*|of|and|the|for|de|da|del|von)){0,7})"
    r"\s*\)$"
)
_BILINGUAL_COMPANY_OPEN_RE = re.compile(
    r"\(\s*(?P<gloss>[A-Z][A-Za-z0-9&.,'’\-]*"
    r"(?:\s+(?:[A-Z][A-Za-z0-9&.,'’\-]*|of|and|the|for|de|da|del|von)){0,7})"
    r"\s*(?P<separator>,?)\s*$"
)


def _source_company_display_before_ticker(
        text: str, start: int, root: str, *,
        source_strings: Iterable[str] = (),
        allow_unconfirmed_bilingual: bool = False) -> tuple[str, bool]:
    """Return a safe source-provided company display and whether it was inferred.

    Two structures are strong enough without a symbol registry: a duplicated
    wordmark (``IREN IREN.O``), and Reuters' bilingual company spelling
    (``버라이즌(Verizon) VZ.N``). Multi-word English definitions are accepted
    only when they contain a corporate noun, which keeps ``설명(Artificial
    Intelligence) AI.N`` and ``보고서(Annual Review) AR.N`` intact.
    """
    prefix = text[:start].rstrip()

    unwrapped = prefix.rstrip("<(").rstrip()
    wordmark = re.search(
        r"(?<![A-Za-z0-9])(?P<label>[A-Z][A-Z0-9-]{1,15})$", unwrapped)
    if wordmark and wordmark.group("label").upper() == root.upper():
        return wordmark.group("label"), True

    open_gloss = _BILINGUAL_COMPANY_OPEN_RE.search(prefix)
    if open_gloss and root.upper() not in NON_TICKER_ACRONYMS:
        outer = prefix[:open_gloss.start()].rstrip()
        outer_match = re.search(
            r"(?P<label>[가-힣][A-Za-z0-9가-힣&.'’·\-]*"
            r"(?:\s+[A-Za-z0-9가-힣&.'’·\-]+){0,7})$",
            outer,
        )
        if outer_match:
            outer_label = outer_match.group("label").strip()
            outer_tail = outer_label.split()[-1]
            if not (
                    outer_label in _SOURCE_LABEL_STOPWORDS
                    or outer_label in _GENERIC_BILINGUAL_LABEL_ENDINGS
                    or outer_tail in _SOURCE_LABEL_STOPWORDS
                    or outer_tail in _GENERIC_BILINGUAL_LABEL_ENDINGS):
                had_separator = prefix.rstrip().endswith(",")
                gloss = re.sub(
                    r"\s+", " ", open_gloss.group("gloss")).strip().rstrip(",")
                gloss_words = [
                    word.strip(".,").casefold() for word in gloss.split()
                ]
                known_display = (
                    COMPANY_NAMES.get(root.upper())
                    or DOLLAR_TICKER_NAMES.get(root.upper())
                )
                # ``회사명(English CODE)``에서 닫는 괄호는 ticker 뒤에
                # 나오므로 회사 주석처럼 보이지만, 장소·보고서·기술 설명도
                # 같은 모양을 만들 수 있다. 알려진 종목이거나 영문 gloss에
                # 명백한 회사형 단어가 있을 때만 회사 정체성으로 학습한다.
                if (known_display
                        or any(word in _ENGLISH_COMPANY_GLOSS_WORDS
                               for word in gloss_words)
                        or bool(re.fullmatch(
                            r"[A-Z][A-Z0-9&.-]{1,15}", gloss))
                        or (root.isdigit()
                            and (had_separator
                                 or bool(open_gloss.group("separator"))))):
                    return known_display or gloss, True

    gloss_match = _BILINGUAL_COMPANY_GLOSS_RE.search(prefix)
    if gloss_match and root.upper() not in NON_TICKER_ACRONYMS:
        outer = prefix[:gloss_match.start()].rstrip()
        outer_match = re.search(
            r"(?P<label>[가-힣][A-Za-z0-9가-힣&.'’·\-]*"
            r"(?:\s+[A-Za-z0-9가-힣&.'’·\-]+){0,7})$",
            outer,
        )
        if outer_match:
            outer_label = outer_match.group("label").strip()
            outer_tail = outer_label.split()[-1]
            if not (
                    outer_label in _SOURCE_LABEL_STOPWORDS
                    or outer_label in _GENERIC_BILINGUAL_LABEL_ENDINGS
                    or outer_tail in _SOURCE_LABEL_STOPWORDS
                    or outer_tail in _GENERIC_BILINGUAL_LABEL_ENDINGS):
                # Bilingual company spelling followed by a full RIC is already
                # a strong Reuters annotation. The Korean outer label guard is
                # what distinguishes Rio Tinto from definitions such as
                # ``보고서(Annual Review) AR.N``.
                gloss = re.sub(
                    r"\s+", " ", gloss_match.group("gloss")).strip()
                gloss_words = [
                    word.strip(".,").casefold() for word in gloss.split()
                ]
                if (any(word in _ENGLISH_COMPANY_GLOSS_WORDS
                        for word in gloss_words)
                        or bool(re.fullmatch(
                            r"[A-Z][A-Z0-9&.-]{1,15}", gloss))
                        or allow_unconfirmed_bilingual):
                    return gloss, True

    # A directly adjacent readable label is also usable when it has a company
    # shape. Keep this deliberately narrower than arbitrary Title Case prose.
    english = re.search(
        r"(?<![A-Za-z0-9])(?P<label>[A-Z][A-Za-z0-9&.'’\-]{1,30}"
        r"(?:\s+[A-Z][A-Za-z0-9&.'’\-]{1,30}){0,3})$",
        prefix,
    )
    if english:
        label = english.group("label")
        words = [word.strip(".,").casefold() for word in label.split()]
        internally_capitalized = bool(re.search(r"[a-z][A-Z]", label))
        if (internally_capitalized
                or (len(words) > 1 and any(
                    word in _ENGLISH_COMPANY_GLOSS_WORDS for word in words))
                or (allow_unconfirmed_bilingual
                    and label.isupper()
                    and label.upper() not in NON_TICKER_ACRONYMS)):
            return label, True

    # Arbitrary Korean noun phrases are not evidence of a company identity.
    # Unknown Korean companies stay generic until a registry alias, duplicated
    # wordmark, corporate English form, or multi-listing annotation confirms it.
    return "", False


def _parenthesized_multi_code_display(text: str, start: int) -> str:
    """Return the readable label before ``(CODE1, CODE2)`` annotations."""
    prefix = text[:start].rstrip()
    if not prefix.endswith("("):
        return ""
    before = prefix[:-1].rstrip()
    match = re.search(
        r"(?P<label>[A-Za-z0-9가-힣][A-Za-z0-9가-힣&.'’·\-]{1,50}"
        r"(?:\s+[A-Za-z0-9가-힣&.'’·\-]+){0,5})$",
        before,
    )
    if not match:
        return ""
    label = match.group("label").strip()
    tail = label.split()[-1]
    if (label in _SOURCE_LABEL_STOPWORDS
            or label in _GENERIC_BILINGUAL_LABEL_ENDINGS
            or tail in _SOURCE_LABEL_STOPWORDS
            or tail in _GENERIC_BILINGUAL_LABEL_ENDINGS
            or label.upper() in NON_TICKER_ACRONYMS):
        return ""
    return label


def _alternate_listing_displays(
        text: str, *, source_strings: Iterable[str] = ()) -> dict[str, str]:
    """Infer one identity for comma-only alternate-listing RIC sequences."""
    domain_spans = _reader_domain_spans(text)
    matches = [
        match for match in EXPLICIT_EXCHANGE_TICKER_RE.finditer(text)
        if not any(match.start() < end and match.end() > start
                   for start, end in domain_spans)
    ]
    inferred: dict[str, str] = {}
    index = 0
    while index < len(matches):
        group = [matches[index]]
        cursor = index + 1
        while (cursor < len(matches)
               and re.fullmatch(r"\s*,\s*", text[group[-1].end():matches[cursor].start()])):
            group.append(matches[cursor])
            cursor += 1
        index = cursor
        if len(group) < 2 or not re.match(
                r"\)?\s*(?:으로|에서|은|는|이|가|을|를|에|의|와|과|도|만|로)"
                r"(?=$|[^A-Za-z가-힣])",
                text[group[-1].end():]):
            continue
        first_full, first_root, first_display = _explicit_ticker_parts(
            group[0].group("code"))
        source_display, _unused = _source_company_display_before_ticker(
            text, group[0].start(), first_root,
            source_strings=source_strings,
            allow_unconfirmed_bilingual=True)
        parenthesized_display = _parenthesized_multi_code_display(
            text, group[0].start())
        if first_display.startswith("해당 "):
            first_display = source_display or parenthesized_display or first_display
        if not first_display or first_display.startswith("해당 "):
            continue
        compatible = True
        for match in group[1:]:
            full, root, display = _explicit_ticker_parts(match.group("code"))
            # Same root on another exchange is intrinsically the same
            # instrument. Different roots need an explicit registry mapping to
            # the same display; a readable first company alone does not prove
            # the following code is its alternate listing.
            if not (root == first_root
                    or (not display.startswith("해당 ")
                        and display == first_display)
                    or (source_display
                        and display.startswith("해당 "))
                    or (parenthesized_display
                        and display.startswith("해당 "))):
                compatible = False
                break
            inferred[full] = first_display
        if compatible:
            inferred[first_full] = first_display
        else:
            for match in group[1:]:
                inferred.pop(_explicit_ticker_parts(match.group("code"))[0], None)
    return inferred


def _collapse_alternate_listing_codes(
        text: str, replacements: Mapping[str, str]) -> str:
    """Keep only the first code when a sequence maps to one company."""
    lookup = {str(token).upper(): str(display)
              for token, display in replacements.items()}
    matches = list(EXPLICIT_EXCHANGE_TICKER_RE.finditer(text))
    removals: list[tuple[int, int]] = []
    index = 0
    while index < len(matches):
        group = [matches[index]]
        cursor = index + 1
        while (cursor < len(matches)
               and re.fullmatch(r"\s*,\s*", text[group[-1].end():matches[cursor].start()])):
            group.append(matches[cursor])
            cursor += 1
        index = cursor
        if len(group) < 2:
            continue
        displays = []
        for match in group:
            full = _explicit_ticker_parts(match.group("code"))[0]
            displays.append(lookup.get(full.upper(), ""))
        if (not displays[0] or displays[0].startswith("해당 ")
                or any(display != displays[0] for display in displays[1:])):
            continue
        removals.append((group[0].end(), group[-1].end()))
    for start, end in reversed(removals):
        text = text[:start] + text[end:]
    return text


def _adjacent_source_company_label(text: str, start: int) -> str:
    """강한 RIC 바로 앞의 회사 표면명이 명확할 때만 보존 이름으로 쓴다."""
    prefix = text[:start].rstrip()
    if not prefix or prefix.endswith(","):
        return ""
    prefix = prefix.rstrip("<(").rstrip()
    # URL·도메인은 앞 단계에서 보존 marker가 된다. Amazon.com처럼
    # 회사명이 곧 도메인인 경우에도 뒤따르는 RIC만 제거할 수 있어야 한다.
    protected = re.search(r"(?P<label>〔보존문구\d+〕)$", prefix)
    if protected:
        return protected.group("label")
    mixed = re.search(
        r"(?P<label>(?:[A-Z0-9]{1,5})?[가-힣][A-Za-z0-9가-힣&.'-]{1,30})$",
        prefix,
    )
    if mixed:
        label = mixed.group("label")
        if label in _SOURCE_LABEL_STOPWORDS:
            return ""
        # `회사는`·`주가가`처럼 일반 명사에 조사가 붙은 문장 성분은
        # 회사명으로 보지 않는다. 한화·기아·이베이처럼 동일 음절로
        # 끝나는 진짜 회사명은 보존한다.
        for particle in ("으로", "에서", "은", "는", "이", "가", "을", "를",
                         "에", "의", "와", "과", "도", "만", "로"):
            if label.endswith(particle) and label[:-len(particle)] in _SOURCE_LABEL_STOPWORDS:
                return ""
        return label
    english = re.search(
        r"(?P<label>[A-Z0-9][A-Za-z0-9&.'-]{1,30}"
        r"(?:\s+[A-Z][A-Za-z0-9&.'-]{1,30}){0,3})$",
        prefix,
    )
    return english.group("label") if english else ""


def explicit_source_ticker_replacements(values: Iterable[object]) -> dict[str, str]:
    """카드 원문에 명시된 동적 ticker의 전체 코드와 bare root를 반환한다."""
    replacements: dict[str, str] = {}
    for value in values:
        source_strings = tuple(_iter_source_strings(value))
        for text in source_strings:
            consumed_spans: list[tuple[int, int]] = []
            domain_spans = _reader_domain_spans(text)
            variable_spans = _algebra_variable_cashtag_spans(text)
            alternate_displays = _alternate_listing_displays(
                text, source_strings=source_strings)
            for pattern in (
                    *GLUED_KNOWN_ALIAS_TICKER_RES,
                    GLUED_DUPLICATED_WORDMARK_RIC_RE,
                    GLUED_KOREAN_TICKER_RE,
                    GLUED_ALPHA_TICKER_RE,
                    GLUED_NUMERIC_TICKER_RE,
                    EXPLICIT_EXCHANGE_TICKER_RE,
                    EXPLICIT_MARKET_TICKER_RE,
                    EXPLICIT_EMPTY_MARKET_RE,
                    EXPLICIT_PREFIXED_EMPTY_MARKET_RE,
                    EXPLICIT_CARET_TICKER_RE,
                    EXPLICIT_LEADING_DOT_INDEX_RE,
                    EXPLICIT_BRACKETED_INDEX_RE,
                    EXPLICIT_DOLLAR_TICKER_RE,
                    PREFIXED_EXCHANGE_TICKER_RE,
                    EXPLICIT_CONTEXT_TICKER_RE):
                for match in pattern.finditer(text):
                    blocked_spans = (
                        (*consumed_spans, *variable_spans)
                        if pattern in GLUED_KNOWN_ALIAS_TICKER_RES
                        else (*consumed_spans, *domain_spans, *variable_spans)
                    )
                    if any(match.start() < end and match.end() > start
                           for start, end in blocked_spans):
                        continue
                    raw_code = match.group("code").strip().lstrip("$")
                    full, root, display = _explicit_ticker_parts(raw_code)
                    if full in alternate_displays:
                        display = alternate_displays[full]
                    if _GEOGRAPHIC_FALSE_CODE_RE.fullmatch(full):
                        continue
                    if (len(root) == 1
                            and pattern is not EXPLICIT_DOLLAR_TICKER_RE
                            and full not in ONE_LETTER_RIC_NAMES):
                        continue
                    if (pattern is EXPLICIT_DOLLAR_TICKER_RE
                            and (root in _BARE_WORDMARK_TICKERS
                                 or root in _DOLLAR_LITERAL_TOKENS
                                 or (root in NON_TICKER_ACRONYMS
                                     and root not in DOLLAR_TICKER_NAMES))):
                        continue
                    if display == "해당 기업":
                        source_display, _inferred_display = (
                            _source_company_display_before_ticker(
                                text, match.start(), root,
                                source_strings=source_strings))
                        if source_display:
                            display = source_display
                    if (display == "해당 기업" and root.isdigit()):
                        display = _adjacent_source_company_label(
                            text, match.start()) or display
                    consumed_spans.append(match.span())
                    stored_full = (
                        f"${full}" if pattern is EXPLICIT_DOLLAR_TICKER_RE
                        else full
                    )
                    strong_market_token = bool(
                        pattern is EXPLICIT_DOLLAR_TICKER_RE
                        or full.startswith((".", "^", "="))
                        or "." in full
                        or "=" in full
                    )
                    # ``Nasdaq: AZIO`` 같은 unknown bare symbol은 같은 문서의
                    # 읽을 수 있는 AZIO wordmark까지 지울 수 있다. full RIC만
                    # 정리 대상으로 저장하고, bare context는 그대로 둔다.
                    if not display.startswith("해당 ") or strong_market_token:
                        replacements.setdefault(stored_full, display)
                    without_code = text[:match.start("code")] + text[match.end("code"):]
                    root_is_written_company_name = (
                        root not in LEADING_DOT_INDEX_NAMES
                        and _token_is_part_of_name(root, (without_code,))
                    )
                    if (root and not root.isdigit()
                            and root not in NON_TICKER_ACRONYMS
                            and root not in _BARE_WORDMARK_TICKERS
                            and len(root) > 1
                            and not (
                                pattern in {
                                    EXPLICIT_LEADING_DOT_INDEX_RE,
                                    EXPLICIT_BRACKETED_INDEX_RE,
                                }
                                and root not in LEADING_DOT_INDEX_NAMES
                            )
                            and not (pattern is EXPLICIT_DOLLAR_TICKER_RE
                                     and len(root) == 1)
                            and not root_is_written_company_name):
                        # Reuters codes can have a significant lower-case letter
                        # (`SIEGn.DE`). Preserve that source spelling for the
                        # case-sensitive bare-token pass, and keep uppercase for
                        # all-uppercase generated variants.
                        raw_root = (
                            root if raw_code.startswith((".", "^"))
                            else re.split(r"[.\-=]", raw_code, maxsplit=1)[0]
                        )
                        if raw_root:
                            replacements.setdefault(raw_root, display)
                        if raw_root != root:
                            replacements.setdefault(root, display)
    return replacements


@lru_cache(maxsize=4096)
def _display_aliases(token: str, display: str) -> tuple[str, ...]:
    full, root, _unused = _explicit_ticker_parts(token)
    aliases = {display}
    if display.endswith(" 지수"):
        aliases.add(display[:-3])
    aliases.update(_LEADING_DOT_INDEX_ALIASES.get(root, ()))
    aliases.update(_MARKET_DISPLAY_ALIASES.get(full, ()))
    aliases.update(_MARKET_DISPLAY_ALIASES.get(root, ()))
    # GLOBAL_COMPANY_NAME_ALIASES의 key는 ticker가 아니라 실제 회사 표기다.
    # 한 단어 영문명(Alphabet, Amazon 등)도 ``회사명 RIC`` 중복 제거에
    # 필요하므로 공백이 든 이름으로 제한하지 않는다.
    aliases.update(
        name for name, mapped in GLOBAL_COMPANY_NAME_ALIASES.items()
        if mapped == display
    )
    return tuple(sorted((alias for alias in aliases if alias), key=len, reverse=True))


@lru_cache(maxsize=1)
def _company_header_patterns() -> tuple[tuple[re.Pattern, str], ...]:
    """Compile same-company Reuters header pairs once per worker process."""
    groups: dict[str, set[str]] = {}
    for code, display in {**COMPANY_NAMES, **DOLLAR_TICKER_NAMES}.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,11}", code) or not display:
            continue
        groups.setdefault(display, set()).update(_display_aliases(code, display))
        groups[display].add(display)

    patterns: list[tuple[re.Pattern, str]] = []
    for display, aliases in groups.items():
        usable = sorted(
            (alias for alias in aliases if len(alias) >= 2),
            key=len,
            reverse=True,
        )
        if not usable:
            continue
        alias_pattern = "|".join(re.escape(alias) for alias in usable)
        patterns.append((re.compile(
            rf"(?<![A-Za-z0-9가-힣])(?P<left>{alias_pattern})\s*:"
            rf"\s*(?P<right>{alias_pattern})"
            rf"(?P<tail>\s+(?:CEO|CFO|COO|CTO|회장|대표|임원)"
            rf"(?:으로|에서|은|는|이|가|을|를|에|의|와|과|도|만|로)?"
            rf"(?=$|[^A-Za-z가-힣])|(?=\s*[,，]))",
            re.I,
        ), display))
    return tuple(patterns)


def collapse_repeated_company_headers(text: str) -> str:
    """Collapse ``회사: 같은 회사 CEO`` Reuters headers to one identity."""
    for pattern, _display in _company_header_patterns():
        text = pattern.sub(
            lambda match: match.group("right") + match.group("tail"),
            text,
        )
    return text


def _is_full_market_code(token: str) -> bool:
    return token.startswith((".", "^")) or "." in token or "=" in token


def replace_source_tickers(
        text: str, replacements: dict[str, str], *,
        protected_context: Iterable[tuple[str, str]] = ()) -> str:
    text = _naturalize_algebra_variables(text)
    text = _collapse_alternate_listing_codes(text, replacements)
    inferred_reader_nouns: set[str] = set()

    def naturalize_known_glued_code(match: re.Match) -> str:
        return _explicit_ticker_parts(match.group("code"))[2]

    def naturalize_duplicated_wordmark_code(match: re.Match) -> str:
        display = _explicit_ticker_parts(match.group("code"))[2]
        return match.group("label") if display.startswith("해당 ") else display

    # A malformed Reuters heading can concatenate a domain-like company alias
    # and its RIC (``AMAZON.COMAMZN.O``). Resolve exact known pairs before the
    # literal-domain protector can hide the middle ``.COM`` fragment.
    for pattern in GLUED_KNOWN_ALIAS_TICKER_RES:
        text = pattern.sub(naturalize_known_glued_code, text)
    text = GLUED_DUPLICATED_WORDMARK_RIC_RE.sub(
        naturalize_duplicated_wordmark_code, text)

    # Reuters 원문의 ``한글명(English Name) RIC``는 세 표기가 모두 같은
    # 회사를 가리킨다. URL처럼 보이는 JD.com도 literal 보호 전에 처리해
    # 바깥의 읽기 좋은 이름 하나만 남긴다. ``<RIC>`` 포장과 붙어 버린
    # ``)RIC``도 같은 구조로 다룬다.
    for token, display in sorted(
            replacements.items(), key=lambda item: -len(item[0])):
        if not display or not _is_full_market_code(token):
            continue
        aliases = _display_aliases(token, display)
        if not aliases:
            continue
        alias_pattern = "|".join(re.escape(alias) for alias in aliases)
        text = _reader_re_sub(
            rf"(?P<label>[A-Za-z0-9가-힣〕])\s*"
            rf"\(\s*(?:{alias_pattern})\s*\)\s*"
            rf"(?:<\s*)?\$?{re.escape(token)}(?:\s*>)?",
            r"\g<label>",
            text,
            flags=re.I,
        )

    # 장소·문서명·기술 설명 괄호 안의 unknown RIC는 회사명이 아니다.
    # generic 표기를 끼워 넣지 말고 라우팅 코드만 제거해 원문 의미를
    # 보존한다: ``보고서(Annual Review AR.N)`` -> ``보고서(Annual Review)``.
    for token, display in sorted(
            replacements.items(), key=lambda item: -len(item[0])):
        if not display.startswith("해당 ") or not _is_full_market_code(token):
            continue
        parenthesized_prose = _compiled_reader_pattern(
            rf"(?P<outer>[가-힣]{{1,30}})"
            rf"(?P<gloss>\([A-Za-z][A-Za-z0-9&.,'’\-]*"
            rf"(?:\s+[A-Za-z][A-Za-z0-9&.,'’\-]*){{0,7}})"
            rf"\s+<?\s*\$?{re.escape(token)}\s*>?(?=\s*\))",
            flags=re.I,
        )

        def keep_parenthesized_prose(match: re.Match) -> str:
            readable = match.group("outer") + match.group("gloss")
            inferred_reader_nouns.add(readable + ")")
            return readable

        text = parenthesized_prose.sub(keep_parenthesized_prose, text)

    # 기사 제목 끝의 ``$SPCX $NVDA`` 군집은 검색/라우팅 태그다. 태그의
    # 회사가 제목 본문에 언급되지 않았더라도 독자 문장 끝에 새 주체로
    # 삽입하지 않는다. 태그 앞에 남은 쉼표·마침표도 문장 완성 단계가
    # 다시 일관되게 붙일 수 있도록 함께 정리한다.
    trailing_cluster = re.search(
        r"\s*[,.;，。；]?\s*(?P<tags>\$[A-Z][A-Z0-9]{0,7}"
        r"(?:\s+\$[A-Z][A-Z0-9]{0,7})*)\s*[.;。；]?$",
        text,
    )
    if trailing_cluster and text[:trailing_cluster.start()].strip(" ,.;，。；"):
        trailing_codes = {
            match.group("code")
            for match in EXPLICIT_DOLLAR_TICKER_RE.finditer(
                trailing_cluster.group("tags"))
        }
        if trailing_codes and not (trailing_codes & _DOLLAR_LITERAL_TOKENS):
            text = text[:trailing_cluster.start()].rstrip()

    for code, display in COMPANY_NAMES.items():
        if not display:
            continue
        for alias in _MARKET_DISPLAY_ALIASES.get(code, ()):
            if alias.casefold() == display.casefold():
                continue
            text = _reader_re_sub(
                rf"(?P<label>{re.escape(display)})\s*[.,]?\s+"
                rf"{re.escape(alias)}(?=$|[^A-Za-z0-9])",
                r"\g<label>",
                text,
                flags=re.I,
            )
    text, protected_literals = protect_reader_literals(text)
    literal_context = (*protected_context, *protected_literals)
    replacement_lookup = {
        token.upper(): display for token, display in replacements.items()
    }
    for pattern, replacement in _EXPLICIT_SOURCE_PHRASE_RULES:
        text = pattern.sub(replacement, text)
    text = _reader_re_sub(
        rf"\s*{PREFIXED_EXCHANGE_TICKER_RE.pattern}"
        r"(?=(?:으로|은|는|이|가|을|를|과|와|로)(?![A-Za-z가-힣]))",
        "",
        text,
        flags=re.I,
    )
    text = PREFIXED_EXCHANGE_TICKER_RE.sub(" ", text)

    ordered = sorted(replacements.items(), key=lambda item: -len(item[0]))
    all_ordered = ordered

    # source inventory가 없어도 알고 있는 bare ticker가 회사명 뒤의 괄호
    # 주석으로 쓰이면 표시명을 새로 삽입하지 않고 코드만 걷어낸다.
    # ``엔비디아(NVDA, 설명)``은 설명 괄호를 유지한다.
    for token, display in GLOBAL_BARE_TICKER_NAMES.items():
        escaped = re.escape(token)
        for alias in _display_aliases(token, display):
            alias_pattern = re.escape(alias)
            text = _reader_re_sub(
                rf"(?P<label>{alias_pattern})\s*\(\s*{escaped}\s*\)",
                r"\g<label>",
                text,
                flags=re.I,
            )
            text = _reader_re_sub(
                rf"(?P<label>{alias_pattern})\s*\(\s*{escaped}\s*,\s*",
                r"\g<label>(",
                text,
                flags=re.I,
            )

    # beneficiary `회사명 (CODE)`에서 배운 bare code는 괄호 포장만
    # 지운다. 표시명을 새로 삽입하면 `C3.ai C3.ai`,
    # `Micron Technology 마이크론`같은 중복이 생긴다.
    structural_tokens = {
        token for token, _display in ordered
        if re.fullmatch(r"\([A-Z][A-Z0-9-]{0,15}\)", token)
    }
    for token, display in ordered:
        single = re.fullmatch(r"\(([A-Z])\)", token)
        if not single or not display:
            continue
        code = single.group(1)
        text = _reader_re_sub(
            rf"(?P<label>{re.escape(display)})\s+{re.escape(code)}"
            rf"(?![A-Za-z0-9-])",
            r"\g<label>",
            text,
        )
    for token in structural_tokens:
        text = _reader_re_sub(
            rf"\s*{re.escape(token)}(?![A-Za-z0-9])",
            "",
            text,
        )

    ordered = [item for item in ordered if item[0] not in structural_tokens]

    # ``한글명(English Name RIC)``은 회사별 예외가 아니라 source inventory의
    # canonical alias로 일반 처리한다. 바깥의 읽는 이름 하나만 남긴다.
    for token, display in ordered:
        if not display or not _is_full_market_code(token):
            continue
        aliases = _display_aliases(token, display)
        if not aliases:
            continue
        alias_pattern = "|".join(re.escape(alias) for alias in aliases)
        text = _reader_re_sub(
            rf"(?P<label>(?:{alias_pattern}))\s*\(\s*(?:{alias_pattern})\s+"
            rf"\$?{re.escape(token)}(?:\s*,[^()]*)?\s*\)",
            r"\g<label>",
            text,
            flags=re.I,
        )

    # ``NvidiaNVDA.O``처럼 회사명과 RIC 사이 공백만 빠진 경우에는
    # 회사명은 보존하고 코드 부분만 지운다.
    def remove_korean_glued_code(match: re.Match) -> str:
        label = match.group("label")
        display = replacement_lookup.get(
            match.group("code").upper(), "해당 기업")
        normalized_prefix = re.sub(
            r"[^A-Za-z0-9가-힣]", "", text[:match.start("code")]).casefold()
        normalized_display = re.sub(
            r"[^A-Za-z0-9가-힣]", "", display).casefold()
        # 코드의 알려진 표시명이 실제 접두 회사명과 일치할 때만 코드만
        # 제거한다. 그 외에는 label과 generic/company identity를 둘 다 남겨
        # ``미국은ABCD.O`` 같은 입력에서 주체를 잃지 않는다.
        if (display and not display.startswith("해당 ")
                and normalized_prefix.endswith(normalized_display)):
            inferred_reader_nouns.add(label)
            return label
        return f"{label} {display}"

    for pattern in GLUED_KNOWN_ALIAS_TICKER_RES:
        text = pattern.sub(naturalize_known_glued_code, text)
    text = GLUED_KOREAN_TICKER_RE.sub(remove_korean_glued_code, text)
    text = GLUED_ALPHA_TICKER_RE.sub("", text)
    text = GLUED_NUMERIC_TICKER_RE.sub("", text)

    def replace_dollar_code(match: re.Match) -> str:
        code = match.group("code").upper()
        if code in _DOLLAR_LITERAL_TOKENS:
            return match.group(0)
        if code in _BARE_WORDMARK_TICKERS:
            return code
        explicit_display = replacements.get(f"${code}")
        if (explicit_display and not explicit_display.startswith("해당 ")
                and (code not in NON_TICKER_ACRONYMS
                     or code in DOLLAR_TICKER_NAMES)):
            return explicit_display
        if code in NON_TICKER_ACRONYMS:
            return code
        return (
            replacements.get(code)
            or DOLLAR_TICKER_NAMES.get(code)
            or "해당 기업"
        )

    # 괄호·꺾쇠 표기는 포장까지 없애고 읽는 이름만 남긴다.
    for token, display in ordered:
        if not display:
            continue
        escaped = re.escape(token)
        if _is_full_market_code(token):
            aliases = _display_aliases(token, display)
            if aliases:
                alias_pattern = "|".join(re.escape(alias) for alias in aliases)
                text = _reader_re_sub(
                    rf"(?P<label>[가-힣][A-Za-z0-9가-힣&.'’·\-]*"
                    rf"(?:\s+[A-Za-z0-9가-힣&.'’·\-]+){{0,7}})"
                    rf"\(\s*(?:{alias_pattern})\s*(?:,\s*|\s+)\$?{escaped}"
                    rf"(?:\s*,[^()]*)?\s*\)",
                    r"\g<label>",
                    text,
                    flags=re.I,
                )
            # Reuters 원문의 ``한글 회사명(English Name) RIC``는 괄호와
            # RIC가 같은 회사의 중복 표기라는 강한 구조다. 일반 설명 괄호와
            # AI·GDP 같은 약어 괄호는 callback에서 보존한다.
            glossed_code = _compiled_reader_pattern(
                rf"(?<=[A-Za-z0-9가-힣〕])\s*\(\s*"
                rf"(?P<gloss>[A-Z][A-Za-z0-9&.,'’\-]*"
                rf"(?:\s+[A-Z][A-Za-z0-9&.,'’\-]*){{0,5}})\s*\)"
                rf"\s+\$?{escaped}(?![A-Za-z0-9])",
                re.I,
            )

            def remove_company_gloss_and_code(match: re.Match) -> str:
                gloss = re.sub(r"\s+", " ", match.group("gloss")).strip()
                if gloss.upper() in NON_TICKER_ACRONYMS:
                    return match.group(0)
                normalized_gloss = re.sub(
                    r"[^A-Za-z0-9]", "", gloss).upper()
                full, _root, _reader_display = _explicit_ticker_parts(token)
                alias_matches = any(
                    normalized_gloss == re.sub(
                        r"[^A-Za-z0-9]", "", alias).upper()
                    for alias in _display_aliases(full, display)
                )
                return "" if alias_matches else match.group(0)

            text = glossed_code.sub(remove_company_gloss_and_code, text)
        if token.startswith("$"):
            for alias in _display_aliases(token, display):
                # Vendor descriptions sometimes repeat the same symbol as
                # ``UMC 2303/$UMC`` or ``GlobalFoundries $GFS``. Preserve the
                # readable wordmark and remove the routing annotation.
                text = _reader_re_sub(
                    rf"(?P<label>{re.escape(alias)})"
                    rf"(?:\s+\d{{3,6}}/)?\s*{escaped}(?![A-Za-z0-9])",
                    r"\g<label>",
                    text,
                    flags=re.I,
                )
        if token.startswith("=") or token.endswith("="):
            for alias in _display_aliases(token, display):
                text = _reader_re_sub(
                    rf"(?P<label>{re.escape(alias)})"
                    rf"(?P<tail>\s+[가-힣]{{1,12}})?\s*"
                    rf"<\s*{escaped}\s*>",
                    r"\g<label>\g<tail>",
                    text,
                    flags=re.I,
                )
        if token.startswith((".", "^")):
            if token.startswith("."):
                readable_wrapper_label = (
                    r"(?P<label>[A-Za-z가-힣0-9][A-Za-z가-힣0-9 &·.'-]{0,80}?"
                    r"(?:지수|지표|증시|관련주|기업|소비재|금속|통화|"
                    r"닛케이|코스피|나스닥|항셉|토픽스))"
                )
                text = _reader_re_sub(
                    rf"{readable_wrapper_label}\s*(?:\(\s*{escaped}\s*\)|"
                    rf"<\s*{escaped}\s*>)",
                    r"\g<label>",
                    text,
                    flags=re.I,
                )
                # `금융(.CSI...)`처럼 강한 wrapper앞에 이미 읽을 수 있는
                # 대상명이 있으면 라우팅 코드만 없앤다. 문장 시작의
                # standalone `.CODE`는 아래에서 canonical/generic 지표명으로 바꾸다.
                text = _reader_re_sub(
                    rf"(?<=[A-Za-z0-9가-힣])\s*(?:\(\s*{escaped}\s*\)|"
                    rf"<\s*{escaped}\s*>)",
                    "",
                    text,
                    flags=re.I,
                )
            index_label = (
                r"(?<![A-Za-z0-9가-힣])"
                r"(?P<label>(?:[A-Za-z가-힣0-9][A-Za-z가-힣0-9 &·.'-]{0,80}?"
                r"(?:지수|지표|증시)|"
                r"닛케이|코스피|나스닥|항셉|토픽스))"
            )
            index_particle = (
                r"(?P<particle>으로|은|는|이|가|을|를|과|와|로)?"
                r"(?=$|[^A-Za-z가-힣])"
            )

            def keep_index_label(match: re.Match) -> str:
                readable = match.group("label")
                suffix = match.group("particle") or ""
                return repair_korean_particles(
                    readable + suffix, nouns=(readable,))

            text = _reader_re_sub(
                rf"{index_label}\s*(?:\(\s*{escaped}\s*\)|"
                rf"<\s*{escaped}\s*>|{escaped})"
                rf"{index_particle}",
                keep_index_label,
                text,
                flags=re.I,
            )
        text = _reader_re_sub(
            rf",\s*{escaped}(?=\s*\))",
            "",
            text,
            flags=re.I,
        )
        for alias in _display_aliases(token, display):
            text = _reader_re_sub(
                rf"(?P<label>{re.escape(alias)})(?P<poss>[’']s)\s*"
                rf"{escaped}(?![A-Za-z0-9])",
                r"\g<label>\g<poss>",
                text,
                flags=re.I,
            )
            text = _reader_re_sub(
                rf"(?P<label>{re.escape(alias)})"
                rf"(?P<particle>으로|에서|은|는|이|가|을|를|에|의|와|과|도|만|로)"
                rf"\s*{escaped}(?![A-Za-z0-9])",
                r"\g<label>\g<particle>",
                text,
                flags=re.I,
            )
            text = _reader_re_sub(
                rf"(?P<label>{re.escape(alias)})\s*"
                rf"\(\s*\$?{escaped}(?:\s*,[^()]*)?\s*\)",
                r"\g<label>",
                text,
                flags=re.I,
            )
            text = _reader_re_sub(
                rf"(?P<label>{re.escape(alias)})\s*<\s*{escaped}\s*>",
                r"\g<label>",
                text,
                flags=re.I,
            )
        # 알려진 alias가 아닌 새 회사명에 붙은 ``(RIC)``도 주석으로 본다.
        # alias 규칙을 먼저 적용해야 ``nVent Electric(NVT.N, NYSE)``처럼
        # 쉼표 뒤가 거래소 metadata인 괄호는 통째로 사라진다. 미지의 설명은
        # 코드만 제거하고 보존한다.
        text = _reader_re_sub(
            rf"(?<=[A-Za-z0-9가-힣〕])\s*\(\s*<?\s*\$?{escaped}"
            rf"\s*>?\s*\)",
            "",
            text,
            flags=re.I,
        )
        text = _reader_re_sub(
            rf"(?<=[A-Za-z0-9가-힣〕])\s*\(\s*\$?{escaped}\s*,\s*",
            "(",
            text,
            flags=re.I,
        )
        wrapped = _compiled_reader_pattern(
            rf"(?:\(\s*\$?{escaped}(?:\s*,[^()]*)?\s*\)|"
            rf"<\s*\$?{escaped}\s*>)",
            re.I,
        )
        text = wrapped.sub(display, text)

    text = EXPLICIT_DOLLAR_TICKER_RE.sub(replace_dollar_code, text)

    # full RIC를 먼저 처리한다. 이미 읽는 이름이 바로 앞에 있으면 코드만
    # 지우고, 단독 코드라면 표시명으로 바꾼다.
    for token, display in ordered:
        if not _is_full_market_code(token):
            continue
        escaped = re.escape(token)
        if display and not display.startswith("해당 "):
            # Amazon.com처럼 회사명이 domain literal로 보호된 경우에는
            # marker 원문이 해당 code의 명시 alias일 때만 RIC를 제거한다.
            # Reuters.com NVDA.O 같은 출처-domain+회사 code는 보존한다.
            aliases = {alias.casefold() for alias in _display_aliases(token, display)}
            for marker, original in literal_context:
                if original.casefold() not in aliases:
                    continue
                text = _reader_re_sub(
                    rf"(?P<label>{re.escape(marker)})\s+{escaped}"
                    rf"(?![A-Za-z0-9])",
                    display,
                    text,
                    flags=re.I,
                )
        for alias in _display_aliases(token, display):
            text = _reader_re_sub(
                rf"(?P<label>{re.escape(alias)})\s*{escaped}(?![A-Za-z0-9])",
                r"\g<label>",
                text,
                flags=re.I,
            )

        text = replace_ticker_token(text, token, display)

    # 치환으로 생긴 ``원유 WTI 원유`` 같은 인접 중복을 원래 읽는 이름 하나로
    # 접는다. 그 뒤 표시명을 보호해 STOXX 같은 정식 wordmark를 bare ticker로
    # 다시 치환하지 않는다.
    for token, display in ordered:
        if not display:
            continue
        for alias in _display_aliases(token, display):
            text = _reader_re_sub(
                rf"(?P<label>{re.escape(alias)})\s*{re.escape(display)}"
                rf"(?![A-Za-z0-9])",
                r"\g<label>",
                text,
                flags=re.I,
            )

    protected_labels: list[tuple[str, str]] = []

    def protect_label(match: re.Match) -> str:
        marker = f"〔표시명보존{len(protected_labels)}〕"
        protected_labels.append((marker, match.group(0)))
        return marker

    for token, display in ordered:
        if not display or display.startswith("해당 "):
            continue
        for alias in _display_aliases(token, display):
            text = _reader_re_sub(
                rf"(?<![A-Za-z0-9가-힣]){re.escape(alias)}"
                rf"(?![A-Za-z0-9])",
                protect_label,
                text,
                flags=re.I,
            )

    for token, display in ordered:
        if _is_full_market_code(token):
            continue
        if display.endswith("지수"):
            text = _reader_re_sub(
                rf"(?<![A-Za-z0-9]){re.escape(token)}\s+지수"
                rf"(?P<particle>으로|에서|은|는|이|가|을|를|에|의|와|과|도|만|로)?"
                rf"(?![A-Za-z0-9가-힣])",
                rf"{display}\g<particle>",
                text,
                flags=0,
            )
        text = replace_ticker_token(
            text, token, display, ignore_case=False)

    for marker, original in protected_labels:
        text = text.replace(marker, original)

    for _token, display in ordered:
        if display:
            text = _reader_re_sub(
                rf"(?P<label>{re.escape(display)})\s*{re.escape(display)}"
                rf"(?![A-Za-z0-9])",
                r"\g<label>",
                text,
                flags=re.I,
            )
    text = _reader_re_sub(r"\s+", " ", text).strip()
    text = repair_korean_particles(
        text,
        nouns=(
            *(alias for token, display in all_ordered
              for alias in _display_aliases(token, display)),
            *inferred_reader_nouns,
        ),
    )
    return restore_reader_literals(text, protected_literals)


def iter_reader_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_reader_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from iter_reader_strings(item)


def reader_scan_first_problem(value) -> bool:
    """요약·브리프에 작성 과정이나 출처 안내가 섞였는지 검사한다."""
    return any(READER_SCAN_FIRST_META_RE.search(text)
               for text in iter_reader_strings(value))


def contains_token(text: str, token: str) -> bool:
    flags = re.I if _is_full_market_code(token) else 0
    return bool(re.search(
        rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text, flags))


@lru_cache(maxsize=32)
def _reader_surface_patterns(
        items: tuple[tuple[str, str], ...]
        ) -> tuple[tuple[re.Pattern, ...], tuple[re.Pattern, ...],
                   tuple[re.Pattern, ...]]:
    """한 리포트의 모든 읽기 필드가 동일한 ticker 패턴 묶음을 공유한다."""
    single_display_patterns = tuple(
        re.compile(
            rf"(?<![A-Za-z0-9가-힣]){re.escape(display)}\s+"
            rf"{re.escape(single.group(1))}(?![A-Za-z0-9-])",
        )
        for token, display in items
        if display and (single := re.fullmatch(r"\(([A-Z])\)", token))
    )
    allowed_alias_patterns = tuple(
        re.compile(
            rf"(?<![A-Za-z0-9가-힣]){re.escape(alias)}"
            rf"(?![A-Za-z0-9])",
            re.I,
        )
        for token, display in items
        if display
        for alias in _display_aliases(token, display)
    )
    forbidden_patterns = tuple(
        re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])",
            re.I if _is_full_market_code(token) else 0,
        )
        for token, _display in items
    )
    return single_display_patterns, allowed_alias_patterns, forbidden_patterns


def reader_text_problem(text: str) -> bool:
    if KNOWN_ONE_LETTER_RIC_RE.search(text):
        return True
    ticker_scan, _protected = protect_reader_literals(text)
    if (READER_INTERNAL_RE.search(ticker_scan)
            or READER_FINANCIAL_SHORTHAND_RE.search(ticker_scan)
            or CONTEXTUAL_TICKER_RE.search(text)
            or READER_EQUALS_CODE_RE.search(ticker_scan)
            or QUALIFIED_TICKER_RE.search(ticker_scan)
            or EXPLICIT_MARKET_TICKER_RE.search(ticker_scan)
            or EXPLICIT_EMPTY_MARKET_RE.search(ticker_scan)
            or EXPLICIT_PREFIXED_EMPTY_MARKET_RE.search(ticker_scan)
            or EXPLICIT_CARET_TICKER_RE.search(ticker_scan)
            or EXPLICIT_LEADING_DOT_INDEX_RE.search(ticker_scan)
            or EXPLICIT_BRACKETED_INDEX_RE.search(ticker_scan)
            or PREFIXED_EXCHANGE_TICKER_RE.search(ticker_scan)
            or KNOWN_RIC_RE.search(ticker_scan)
            or KNOWN_HYPHEN_TICKER_RE.search(ticker_scan)
            or KNOWN_MARKET_CODE_RE.search(ticker_scan)
            or _READER_MEMORY_DEFINITION_RE.search(ticker_scan)
            or READER_ROUTING_METADATA_RE.search(ticker_scan)):
        return True
    if any(match.group("code").upper() not in _DOLLAR_LITERAL_TOKENS
           for match in READER_DOLLAR_TOKEN_RE.finditer(ticker_scan)):
        return True
    scrubbed = ticker_scan
    for phrase in _LEGITIMATE_COMPANY_PHRASES:
        scrubbed = re.sub(re.escape(phrase), " ", scrubbed, flags=re.I)
    if KNOWN_TICKER_RE.search(scrubbed):
        return True
    mixed_acronyms = {
        value.upper(): value for value in MIXED_CASE_TECH_ACRONYMS
    }
    for match in PARENTHESIZED_CODE_RE.finditer(ticker_scan):
        raw_code = match.group("code")
        if raw_code in NON_TICKER_ACRONYMS or raw_code in MIXED_CASE_TECH_ACRONYMS:
            continue
        if raw_code.upper() in NON_TICKER_ACRONYMS or raw_code.upper() in mixed_acronyms:
            return True
    return False


def reader_surface_problem(
        value: object,
        *,
        forbidden_tokens: Iterable[str] | Mapping[str, str] = (),
) -> bool:
    if isinstance(forbidden_tokens, Mapping):
        replacements = {
            str(token): str(display)
            for token, display in forbidden_tokens.items() if token
        }
    else:
        replacements = {
            str(token): "" for token in forbidden_tokens if token
        }
    # A report can carry hundreds of source tickers. Keep compiled objects for
    # the whole surface scan and reuse the same bundle across all reader fields.
    (single_display_patterns,
     allowed_alias_patterns,
     forbidden_patterns) = _reader_surface_patterns(
        tuple(replacements.items())
    )
    for text in iter_reader_strings(value):
        if reader_text_problem(text):
            return True
        if any(pattern.search(text) for pattern in single_display_patterns):
            return True
        token_scan = text
        protected: list[tuple[str, str]] = []
        for pattern in allowed_alias_patterns:
            marker = f"〔허용표시명{len(protected)}〕"

            def protect(match: re.Match, *, value=marker) -> str:
                protected.append((value, match.group(0)))
                return value

            token_scan = pattern.sub(protect, token_scan)
        if any(pattern.search(token_scan) for pattern in forbidden_patterns):
            return True
    return False
