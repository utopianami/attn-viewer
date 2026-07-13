"""지표 레지스트리 — 단일 소스 (2026-07-13 LLM 쿼리 플래너 P1).

플래너 메뉴 / 규칙 폴백 keywords / 요약 라벨이 전부 이 dict 하나를 쓴다.
새 지표는 수집기 추가 시점에 여기 한 줄 등록.
"""
from __future__ import annotations

METRIC_REGISTRY: dict[str, dict] = {
    "kr_semi_export": {
        "label": "한국 반도체 수출액",
        "desc": "관세청 10일 단위 수출액 — 삼성·하이닉스 매출 선행 proxy",
        "keywords": ("수출",)},
    "kr_semi_export_share": {
        "label": "반도체 수출 비중",
        "desc": "전체 수출 중 반도체 비중(%)",
        "keywords": ("수출 비중",)},
    "kr_semi_production_index": {
        "label": "한국 반도체 생산·재고지수",
        "desc": "통계청 생산·출하·재고지수 — 재고 사이클 판단",
        "keywords": ("재고", "생산지수")},
    "hyperscaler_capex": {
        "label": "하이퍼스케일러 CAPEX",
        "desc": "MS·구글·메타·아마존 등 분기 설비투자(10억달러) — AI 인프라 수요",
        "keywords": ("capex", "캐펙스", "설비투자", "인프라 투자")},
    "memory_capex": {
        "label": "메모리 3사 CAPEX",
        "desc": "삼성·하이닉스·마이크론 분기 설비투자 — 공급 증설 리스크",
        "keywords": ("증설", "공급 과잉")},
    "ai_chip_revenue": {
        "label": "AI 칩 기업 매출",
        "desc": "NVDA·AMD·AVGO 분기 매출(10억달러) — HBM 수요 선행",
        "keywords": ("엔비디아 매출", "ai 칩")},
    "equip_revenue": {
        "label": "반도체 장비사 매출",
        "desc": "ASML 등 장비사 분기 매출 — 6~12개월 뒤 공급 증가 신호",
        "keywords": ("장비", "asml")},
    "tw_monthly_revenue": {
        "label": "대만 ODM·TSMC 월매출",
        "desc": "TSMC·콴타·위윈 등 월매출(kTWD, YoY/MoM) — AI 서버 수요 proxy",
        "keywords": ("tsmc", "월매출", "대만", "odm")},
    "memory_price_usd_per_gb": {
        "label": "메모리 현물가",
        "desc": "D램·낸드 USD/GB 현물가 — 사이클 방향의 핵심",
        "keywords": ("현물가", "가격", "고정가")},
    "token_price": {
        "label": "LLM 토큰 단가",
        "desc": "모델별 1M 토큰 가격 — 토큰 경제/inference 수요 방향",
        "keywords": ("토큰 가격", "api 가격")},
    "openrouter_daily_tokens": {
        "label": "OpenRouter 일별 토큰 사용량",
        "desc": "모델별 일일 처리 토큰 — AI 사용량 proxy",
        "keywords": ("토큰 사용량", "사용량", "오픈라우터")},
    "sdk_downloads": {
        "label": "AI SDK 다운로드",
        "desc": "주요 AI SDK 다운로드 수 — 개발자 수요 proxy",
        "keywords": ("sdk", "다운로드")},
    "app_rank": {
        "label": "AI 앱 순위",
        "desc": "앱스토어 AI 앱 순위 — 소비자 수요 proxy",
        "keywords": ("앱 순위",)},
    "search_interest_kr": {
        "label": "한국 검색 관심도",
        "desc": "네이버 데이터랩 검색 트렌드 — 국내 관심도",
        "keywords": ("검색량", "관심도")},
    "stock_price": {
        "label": "종목 주가",
        "desc": "메모리·AI 관련 종목 일별 주가",
        "keywords": ("주가",)},
    "earnings_calendar": {
        "label": "실적 발표 일정",
        "desc": "관련 기업 실적 발표 예정일",
        "keywords": ("실적 발표", "실적 일정", "컨콜")},
    "macro_calendar": {
        "label": "매크로 일정",
        "desc": "FOMC·CPI 등 거시 이벤트 일정",
        "keywords": ("fomc", "cpi", "금리 결정")},
    "ai_status_incidents": {
        "label": "AI 서비스 장애",
        "desc": "주요 AI 서비스 장애 횟수 — capacity 압박 신호",
        "keywords": ("장애", "다운")},
}

_GROUP_KEYS = ("name", "item", "token", "model", "category")


def _group_key(meta: dict) -> str:
    for k in _GROUP_KEYS:
        v = meta.get(k)
        if v:
            return str(v)
    return ""


def metric_summary(store, metric: str) -> str:
    """지표 최신 관측 요약 한 줄 — 합성 컨텍스트 주입용. 실패·부재 시 ""."""
    info = METRIC_REGISTRY.get(metric)
    if not info:
        return ""
    try:
        rows = store.read_metric(metric, last_n=400)
    except Exception:  # noqa: BLE001 — never-raise
        return ""
    if not rows:
        return ""
    groups: dict[str, list] = {}
    for o in rows:  # read_metric이 ts 오름차순 보장
        groups.setdefault(_group_key(o.meta), []).append(o)
    top = sorted(groups.values(), key=lambda rs: rs[-1].ts, reverse=True)[:5]
    parts = []
    for rs in top:
        last = rs[-1]
        chg = ""
        if len(rs) >= 2 and rs[-2].value:
            chg = f", 직전 대비 {(float(last.value) / float(rs[-2].value) - 1) * 100:+.1f}%"
        gk = _group_key(last.meta)
        head = f"{gk} " if gk else ""
        parts.append(f"{head}{float(last.value):,.4g} {last.unit} ({last.ts}{chg})")
    return f"[섹터 지표] {info['label']}: " + " · ".join(parts)
