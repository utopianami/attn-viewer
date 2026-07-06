# engine/sector/collectors/dart_edgar.py
"""공시 — DART(키 필요) + SEC EDGAR(키 불필요, UA 필수). 공시=S급, 100% 관련."""
from __future__ import annotations

import datetime as _dt

import httpx

from app.settings import settings
from sector.contracts import CollectorResult, RawNewsItem
from sector.store import SectorStore

NAME = "dart_edgar"
KIND = "news"
_DART_CORPS = [("삼성전자", "00126380"), ("SK하이닉스", "00164779")]
_EDGAR_CIKS = [("MU", 723125), ("NVDA", 1045810), ("MSFT", 789019), ("META", 1326801)]
_EDGAR_FORMS = {"8-K", "10-Q", "10-K", "20-F"}
_EDGAR_UA = {"User-Agent": "attn-viewer research dev@vault.haus"}


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    items: list[RawNewsItem] = []
    notes: list[str] = []
    today = _dt.date.today()
    week_ago = today - _dt.timedelta(days=7)
    try:
        if settings.dart_api_key:
            for corp, code in _DART_CORPS:
                try:
                    resp = await client.get("https://opendart.fss.or.kr/api/list.json", params={
                        "crtfc_key": settings.dart_api_key, "corp_code": code,
                        "bgn_de": week_ago.strftime("%Y%m%d"), "end_de": today.strftime("%Y%m%d"),
                        "page_count": 20})
                    data = resp.json()
                    if data.get("status") != "000":
                        notes.append(f"dart:{corp}={data.get('status')}")
                        continue
                    for row in data.get("list", []) or []:
                        rno = row.get("rcept_no", "")
                        items.append(RawNewsItem(
                            id=f"dart-{rno}", title=f"[공시] {corp} {row.get('report_nm', '')}",
                            source="dart.fss.or.kr", grade_hint="S",
                            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rno}",
                            published_at=row.get("rcept_dt", ""), extra={"corp": corp}))
                except Exception:  # noqa: BLE001
                    notes.append(f"dart:{corp}=error")
        else:
            notes.append("dart: missing_key")
        for ticker, cik in _EDGAR_CIKS:
            try:
                resp = await client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                                        headers=_EDGAR_UA)
                resp.raise_for_status()
                recent = (resp.json().get("filings") or {}).get("recent") or {}
                forms = recent.get("form", [])
                dates = recent.get("filingDate", [])
                accs = recent.get("accessionNumber", [])
                descs = recent.get("primaryDocDescription", [""] * len(forms))
                for form, fdate, acc, desc in zip(forms, dates, accs, descs):
                    if form not in _EDGAR_FORMS or fdate < week_ago.isoformat():
                        continue
                    items.append(RawNewsItem(
                        id=f"edgar-{acc}", title=f"[filing] {ticker} {form} {desc}".strip(),
                        source="sec.gov", grade_hint="S", published_at=fdate,
                        url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}",
                        extra={"ticker": ticker, "form": form}))
            except Exception:  # noqa: BLE001
                notes.append(f"edgar:{ticker}=error")
        return CollectorResult(name=NAME, kind=KIND, items=items, status="ok",
                               detail="; ".join(notes)[:300])
    finally:
        if own:
            await client.aclose()
