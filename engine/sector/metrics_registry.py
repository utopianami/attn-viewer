"""지표 레지스트리 — 단일 소스 (2026-07-13 LLM 쿼리 플래너 P1).

플래너 메뉴 / 규칙 폴백 keywords / 요약 라벨이 전부 이 dict 하나를 쓴다.
새 지표는 수집기 추가 시점에 여기 한 줄 등록.
"""
from __future__ import annotations

METRIC_REGISTRY: dict[str, dict] = {
    "kr_semi_export": {
        "label": "한국 반도체 수출액",
        "origin": "관세청 수출입무역통계 API (apis.data.go.kr)",
        "desc": "관세청 10일 단위 수출액 — 삼성·하이닉스 매출 선행 proxy",
        "keywords": ("수출",)},
    "kr_semi_export_share": {
        "label": "반도체 수출 비중",
        "origin": "관세청 수출입무역통계 API (apis.data.go.kr)",
        "desc": "전체 수출 중 반도체 비중(%)",
        "keywords": ("수출 비중",)},
    "kr_semi_production_index": {
        "label": "한국 반도체 생산·재고지수",
        "origin": "통계청 KOSIS 국가통계포털 (kosis.kr)",
        "desc": "통계청 생산·출하·재고지수 — 재고 사이클 판단",
        "keywords": ("재고", "생산지수")},
    # 사실성 감사 5.2/5.3: Yahoo 분기값은 전사 연결 수치 — 'AI 전용/메모리 전용'으로
    # 오독되지 않게 라벨에 프록시 정체 명시(직전 대비 Δ는 QoQ, b_local은 통화 혼재)
    "hyperscaler_capex": {
        "label": "하이퍼스케일러 전사 CAPEX 프록시(AI 전용 아님)",
        "origin": "Yahoo Finance 분기 재무제표 (query1.finance.yahoo.com)",
        "desc": "MS·구글·메타·아마존 등 분기 전사 설비투자(10억달러) — AI 인프라 수요 방향 프록시",
        "keywords": ("capex", "캐펙스", "설비투자", "인프라 투자")},
    "memory_capex": {
        "label": "메모리 3사 전사 CAPEX 프록시(메모리 전용 아님·통화 혼재)",
        "origin": "Yahoo Finance 분기 재무제표 (query1.finance.yahoo.com)",
        "desc": "삼성(원)·하이닉스(원)·마이크론(달러) 분기 전사 설비투자 — 공급 증설 방향 프록시",
        "keywords": ("증설", "공급 과잉")},
    "ai_chip_revenue": {
        "label": "AI 칩 기업 전사 매출 프록시(비AI 사업 포함)",
        "origin": "Yahoo Finance 분기 재무제표 (query1.finance.yahoo.com)",
        "desc": "NVDA·AMD·AVGO 분기 전사 매출(10억달러) — HBM 수요 선행 방향 프록시",
        "keywords": ("엔비디아 매출", "ai 칩")},
    "equip_revenue": {
        "label": "반도체 장비사 매출",
        "origin": "Yahoo Finance 분기 재무제표 (query1.finance.yahoo.com)",
        "desc": "ASML 등 장비사 분기 매출 — 6~12개월 뒤 공급 증가 신호",
        "keywords": ("장비", "asml")},
    "tw_monthly_revenue": {
        "label": "대만 ODM·TSMC 월매출",
        "origin": "대만 증권거래소 MOPS 공시 (mopsfin.twse.com.tw)",
        "desc": "TSMC·콴타·위윈 등 월매출(kTWD, YoY/MoM) — AI 서버 수요 proxy",
        "keywords": ("tsmc", "월매출", "대만", "odm")},
    "memory_price_usd_per_gb": {
        # 사실성 감사 5.1: Keepa 시리즈는 Amazon 소비자 신품 최저 '호가'(listing,
        # 표본 소수) — '산업 현물가/실현 ASP'로 오독되지 않게 라벨에 정체 명시
        "label": "메모리 소비자 리테일 최저호가 프록시(Keepa)·HBM 추정",
        "origin": "Stanford DRAM 가격 데이터셋 (dam.stanford.edu — McCallum 히스토리·Keepa 리테일 통합)",
        "desc": "Amazon 소비자 DIMM 최저 호가 기반 프록시 — 계약가·실현 ASP 아님, 방향성 참고",
        "keywords": ("현물가", "가격", "고정가")},
    "token_price": {
        "label": "LLM 토큰 단가",
        "origin": "OpenRouter 공개 API (openrouter.ai)",
        "desc": "모델별 1M 토큰 가격 — 토큰 경제/inference 수요 방향",
        "keywords": ("토큰 가격", "api 가격")},
    "openrouter_daily_tokens": {
        "label": "OpenRouter 일별 토큰 사용량",
        "origin": "OpenRouter 공개 API (openrouter.ai)",
        "desc": "모델별 일일 처리 토큰 — AI 사용량 proxy",
        "keywords": ("토큰 사용량", "사용량", "오픈라우터")},
    "sdk_downloads": {
        "label": "AI SDK 다운로드",
        "origin": "npm 레지스트리 (api.npmjs.org) · PyPI Stats (pypistats.org)",
        "desc": "주요 AI SDK 다운로드 수 — 개발자 수요 proxy",
        "keywords": ("sdk", "다운로드")},
    "app_rank": {
        "label": "AI 앱 순위",
        "origin": "Apple App Store RSS (rss.marketingtools.apple.com)",
        "desc": "앱스토어 AI 앱 순위 — 소비자 수요 proxy",
        "keywords": ("앱 순위",), "delta_pct": False, "unit": "rank"},
    "search_interest_kr": {
        "label": "한국 검색 관심도",
        "origin": "네이버 데이터랩 API (openapi.naver.com)",
        "desc": "네이버 데이터랩 검색 트렌드 — 국내 관심도",
        "keywords": ("검색량", "관심도"), "unit": "index"},
    "stock_price": {
        "label": "종목 주가",
        "origin": "Yahoo Finance 시세 (query1.finance.yahoo.com)",
        "desc": "메모리·AI 관련 종목 일별 주가",
        "keywords": ("주가",)},
    "earnings_calendar": {
        "label": "실적 발표 일정",
        "origin": "Nasdaq API (api.nasdaq.com)",
        "desc": "관련 기업 실적 발표 예정일",
        "keywords": ("실적 발표", "실적 일정", "컨콜"), "delta_pct": False},
    "macro_calendar": {
        "label": "매크로 일정",
        "origin": "SaveTicker firehose",
        "desc": "FOMC·CPI 등 거시 이벤트 일정",
        "keywords": ("fomc", "cpi", "금리 결정"), "delta_pct": False},
    "ai_status_incidents": {
        "label": "AI 서비스 장애",
        "origin": "각 서비스 status 페이지 (status.claude.com/status.openai.com 등)",
        "desc": "주요 AI 서비스 장애 횟수 — capacity 압박 신호",
        "keywords": ("장애", "다운"), "delta_pct": False},
}

# 수집기별 실제 meta 키 전수: app_rank=app, sdk_downloads=pkg, macro_calendar=title,
# ai_status_incidents=provider. 누락되면 서로 다른 시계열이 한 그룹으로 뭉쳐
# 허위 변화율이 나온다 (codex 리뷰 H1). title을 provider보다 앞에 — 캘린더는
# 같은 provider 아래 여러 이벤트.
_GROUP_KEYS = ("name", "item", "app", "pkg", "title", "model", "token", "provider", "category")


def _group_key(meta: dict) -> str:
    for k in _GROUP_KEYS:
        v = meta.get(k)
        if v:
            return str(v)
    return ""


def metric_summary(store, metric: str, *, cutoff=None) -> str:
    """지표 최신 관측 요약 한 줄 — 합성 컨텍스트 주입용. 실패·부재 시 ""."""
    info = METRIC_REGISTRY.get(metric)
    if not info:
        return ""
    try:
        rows = store.read_metric(metric, last_n=400)
        if cutoff is not None:                  # look-ahead 차단(리포트 경로, SF1)
            cut = (cutoff.date().isoformat() if hasattr(cutoff, "date")
                   else str(cutoff)[:10])
            rows = [o for o in rows
                    if ((o.ts + "-01") if len(o.ts) == 7 else o.ts[:10]) <= cut]
        if not rows:
            return ""
        groups: dict[str, list] = {}
        for o in rows:  # read_metric이 ts 오름차순 보장
            groups.setdefault(_group_key(o.meta), []).append(o)
        top = sorted(groups.values(), key=lambda rs: rs[-1].ts, reverse=True)[:5]
        parts = []
        for rs in top:
            last = rs[-1]
            # null value 방어: 일부 수집기가 검증 우회 후 null 입력 가능성
            if last.value is None:
                continue
            chg = ""
            # 순위·캘린더·장애 카운트는 전기 대비율이 무의미 (delta_pct: False)
            if info.get("delta_pct", True) and len(rs) >= 2 and rs[-2].value:
                chg = f", 직전 대비 {(float(last.value) / float(rs[-2].value) - 1) * 100:+.1f}%"
            gk = _group_key(last.meta)
            head = f"{gk} " if gk else ""
            parts.append(f"{head}{float(last.value):,.4g} {last.unit} ({last.ts}{chg})")
        return f"[섹터 지표] {info['label']}: " + " · ".join(parts)
    except Exception:  # noqa: BLE001 — never-raise: 그룹화·서식 단계 실패 시 ""
        return ""
