# engine/sector/collectors/dart_edgar.py
"""공시 — DART(키 필요) + SEC EDGAR(키 불필요, UA 필수). 공시=S급, 100% 관련."""
from __future__ import annotations

import datetime as _dt
import io
import re
import zipfile

import httpx

from app.settings import settings
from sector.contracts import CollectorResult, MetricObservation, RawNewsItem
from sector.store import SectorStore

NAME = "dart_edgar"
KIND = "news"
_DART_CORPS = [("삼성전자", "00126380"), ("SK하이닉스", "00164779")]
_EDGAR_CIKS = [("MU", 723125), ("NVDA", 1045810), ("MSFT", 789019), ("META", 1326801)]
_EDGAR_FORMS = {"8-K", "10-Q", "10-K", "20-F"}
_EDGAR_UA = {"User-Agent": "attn-viewer research dev@vault.haus"}

# 기업설명회(IR) 공시 본문에서 개최 날짜 추출 → 실적 캘린더 confirmed 승격
_IR_DATE_PATTERNS = [
    re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
    re.compile(r"(20\d{2})[.\-/]\s?(\d{1,2})[.\-/]\s?(\d{1,2})"),
]


def parse_ir_date(text: str, min_date: _dt.date) -> _dt.date | None:
    """본문에서 개최 날짜 — 접수일(min_date) 이전 날짜는 오탐으로 버림, 못 찾으면 None."""
    for pat in _IR_DATE_PATTERNS:
        for m in pat.finditer(text):
            try:
                d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            if d >= min_date:
                return d
    return None


async def _fetch_ir_date(client: httpx.AsyncClient, rcept_no: str,
                         min_date: _dt.date) -> _dt.date | None:
    resp = await client.get("https://opendart.fss.or.kr/api/document.xml", params={
        "crtfc_key": settings.dart_api_key, "rcept_no": rcept_no})
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        text = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist())
    return parse_ir_date(re.sub(r"<[^>]+>", " ", text), min_date)


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    items: list[RawNewsItem] = []
    obs: list[MetricObservation] = []
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
                        report_nm = row.get("report_nm", "")
                        items.append(RawNewsItem(
                            id=f"dart-{rno}", title=f"[공시] {corp} {report_nm}",
                            source="dart.fss.or.kr", grade_hint="S",
                            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rno}",
                            published_at=row.get("rcept_dt", ""), extra={"corp": corp}))
                        # IR 개최 공시 → 실적 캘린더 confirmed (파싱 실패는 방출 없이 스킵)
                        if "기업설명회" in report_nm:
                            try:
                                rdt = row.get("rcept_dt", "")
                                min_d = (_dt.datetime.strptime(rdt, "%Y%m%d").date()
                                         if rdt else today)
                                ir_d = await _fetch_ir_date(client, rno, min_d)
                            except Exception:  # noqa: BLE001
                                ir_d = None
                                notes.append(f"ir_fetch_fail:{rno}")
                            if ir_d:
                                obs.append(MetricObservation(
                                    metric="earnings_calendar", ts=ir_d.isoformat(),
                                    value=1.0, unit="event",
                                    meta={"item": corp, "name": corp,
                                          "event": "기업설명회(IR)", "kind": "confirmed",
                                          "provider": "dart", "time": ""}))
                            else:
                                notes.append(f"ir_parse_skip:{rno}")
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
        return CollectorResult(name=NAME, kind=KIND, items=items, observations=obs,
                               status="ok", detail="; ".join(notes)[:300])
    finally:
        if own:
            await client.aclose()
