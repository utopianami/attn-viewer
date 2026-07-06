"""SaveTicker — P1 1차 뉴스 소스 (계획 §2-7, 2026-07-06 실측).

목록(미리보기 83자)으로 감지 → 키워드 필터 → 관련 항목만 detail(무인증 전문).
search= 파라미터는 인덱스가 비실시간이라 사용 금지. 비공식 API — 저강도, UA 명시.
"""
from __future__ import annotations

import re

import httpx

from sector.contracts import CollectorResult, MetricObservation, RawNewsItem
from sector.store import SectorStore

NAME = "saveticker"
KIND = "news"
_BASE = "https://api.saveticker.com/api"
_UA = {"User-Agent": "attn-viewer-sector/0.1 (personal research)"}

# 엔티티/주제 키워드 — 제목+미리보기에 하나라도 걸리면 후보 (계획 §1 축 엔티티)
_KEYWORDS = (
    "하이닉스", "삼성전자", "마이크론", "micron", "삼전", "메모리", "hbm", "d램", "dram",
    "낸드", "nand", "반도체", "tsmc", "엔비디아", "nvidia", "openai", "오픈ai", "오픈에이아이",
    "앤트로픽", "anthropic", "구글", "마이크로소프트", "ms", "아마존", "메타", "애플",
    "오라클", "데이터센터", "capex", "설비투자", "gpu", "수출통제", "관세",
)
_STAR = re.compile(r"★")


def _relevant(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in _KEYWORDS)


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, headers=_UA)
    items: list[RawNewsItem] = []
    obs: list[MetricObservation] = []
    detail_fail = 0
    try:
        resp = await client.get(f"{_BASE}/news/list", params={"page_size": 50})
        resp.raise_for_status()
        rows = resp.json().get("news_list", []) or []
        last_id = int(store.get_state("saveticker_last_id") or 0)
        max_id = last_id
        for row in rows:
            try:
                rid = int(row.get("id", 0))
            except (TypeError, ValueError):
                continue
            max_id = max(max_id, rid)
            if rid <= last_id:
                continue
            title = row.get("title") or ""
            preview = row.get("content") or ""
            if not _relevant(f"{title} {preview}"):
                continue
            content = preview
            source = row.get("source") or ""
            try:
                d = await client.get(f"{_BASE}/news/detail/{rid}")
                d.raise_for_status()
                news = d.json().get("news", {}) or {}
                blocks = news.get("content")
                if isinstance(blocks, list):
                    content = "\n".join(
                        (b.get("content") or "").strip() for b in blocks
                        if isinstance(b, dict) and (b.get("content") or "").strip())
                source = news.get("source") or source
            except Exception:  # noqa: BLE001 — detail 실패는 미리보기로 진행
                detail_fail += 1
            items.append(RawNewsItem(
                id=f"st-{rid}", title=title, preview=preview, content=content,
                source=source, url=f"https://www.saveticker.com/news?id={rid}",
                published_at=row.get("created_at") or "",
                grade_hint="D" if "(카더라)" in title else None,
                extra={"provider": "saveticker"}))
        if max_id > last_id:
            store.set_state("saveticker_last_id", max_id)

        # 매크로 캘린더 (향후 14일) — ★ 개수 = 중요도
        import datetime as _dt
        today = _dt.date.today()
        cal = await client.get(f"{_BASE}/calendar/events", params={
            "start_date": today.isoformat(),
            "end_date": (today + _dt.timedelta(days=14)).isoformat()})
        if cal.status_code == 200:
            for ev in cal.json().get("events", []) or []:
                stars = len(_STAR.findall(ev.get("title") or ""))
                if stars >= 2:
                    obs.append(MetricObservation(
                        metric="macro_calendar", ts=(ev.get("event_date") or "")[:10],
                        value=float(stars), unit="stars",
                        meta={"title": ev.get("title") or "", "provider": "saveticker"}))
        status = "ok" if detail_fail == 0 else "degraded"
        detail = "" if detail_fail == 0 else f"detail_fail={detail_fail}"
        return CollectorResult(name=NAME, kind=KIND, items=items,
                               observations=obs, status=status, detail=detail)
    finally:
        if own:
            await client.aclose()
