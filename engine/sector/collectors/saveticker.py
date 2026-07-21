"""SaveTicker — firehose id-walk + raw 코퍼스 (2026-07-21 재작성).

구 /api/news/list sunset(2026-07-07) → detail/{id} 순회로 firehose 복원.
전량 raw 저장 + 키워드 통과분만 카드 경로. 상태 scan_hwm/observed_anchor/
cutover_floor/pending, 무손실=(cutover_floor, scan_hwm].
스펙: docs/superpowers/specs/2026-07-21-saveticker-firehose-raw-corpus-design.md (v9)
"""
from __future__ import annotations

import asyncio
import random
import re
import time

import httpx

from sector.contracts import CollectorResult, MetricObservation, RawNewsDoc, RawNewsItem
from sector.store import SectorStore

NAME = "saveticker"
KIND = "news"
_BASE = "https://api.saveticker.com/api"
_UA = {"User-Agent": "attn-viewer-sector/0.1 (personal research)"}

MISS_STOP = 40
CYCLE_CAP = 800
MAX_ELAPSED_S = 300
DETAIL_TIMEOUT_S = 8
REQUEST_INTERVAL_S = 0.15
RETRY_TRANSIENT = 1
PENDING_MAX = 300
PENDING_BUDGET = 400
PENDING_ELAPSED_S = 120
CANARY_SAMPLE = 3
CARD_CANDIDATE_CAP = 40

# 엔티티/주제 키워드 — 카드 경로용(raw는 무필터). 제목+미리보기에 하나라도 걸리면 후보.
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


class _Budget:
    """실제 HTTP 요청(transient 재시도 포함)·시간 예산. CYCLE_CAP·MAX_ELAPSED_S 하드 상한."""

    def __init__(self, max_req: int, max_elapsed: float, interval: float):
        self._max_req, self._max_elapsed, self._interval = max_req, max_elapsed, interval
        self._req = 0
        self._t0 = time.monotonic()
        self._last = 0.0

    def requests(self) -> int:
        return self._req

    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def ok(self) -> bool:
        return self._req < self._max_req and self.elapsed() < self._max_elapsed

    async def throttle(self) -> None:
        if self._interval:
            wait = self._interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last = time.monotonic()

    def spend(self) -> None:
        self._req += 1


def _to_text(news: dict) -> str:
    c = news.get("content")
    if isinstance(c, list):
        return "\n".join((b.get("content") or "").strip() for b in c
                         if isinstance(b, dict) and (b.get("content") or "").strip())
    return c if isinstance(c, str) else ""


def _doc_from(news: dict) -> RawNewsDoc:
    nid = str(news.get("id") or "")
    return RawNewsDoc(id=nid, title=news.get("title") or "",
                      created_at=news.get("created_at") or "", content=_to_text(news),
                      source=news.get("source") or "",
                      url=f"https://www.saveticker.com/news/{nid}",
                      tag_names=news.get("tag_names") or [])


def _raw_news_item(news: dict) -> RawNewsItem:
    nid = str(news.get("id") or "")
    text = _to_text(news)
    title = news.get("title") or ""
    return RawNewsItem(
        id=f"st-{nid}", title=title, preview=text[:200], content=text,
        source=news.get("source") or "",
        url=f"https://www.saveticker.com/news/{nid}",
        published_at=news.get("created_at") or "",
        grade_hint="D" if "(카더라)" in title else None,
        extra={"provider": "saveticker"})


async def _classify_detail(client: httpx.AsyncClient, rid: int, budget: _Budget):
    """(kind, news|None). kind ∈ valid/deleted/not_found/transient/invalid."""
    attempts = 1 + RETRY_TRANSIENT
    for attempt in range(attempts):
        if not budget.ok():
            return "transient", None
        await budget.throttle()
        budget.spend()
        try:
            r = await client.get(f"{_BASE}/news/detail/{rid}", timeout=DETAIL_TIMEOUT_S)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt < attempts - 1:
                await asyncio.sleep(0.5 + random.random() * 0.3)
                continue
            return "transient", None
        sc = r.status_code
        if sc == 404:
            return "not_found", None
        if sc == 429 or sc >= 500:
            if attempt < attempts - 1:
                await asyncio.sleep(0.5 + random.random() * 0.3)
                continue
            return "transient", None
        if sc != 200:
            return "invalid", None
        try:
            news = r.json().get("news")
        except Exception:  # noqa: BLE001
            if attempt < attempts - 1:
                await asyncio.sleep(0.5 + random.random() * 0.3)
                continue
            return "transient", None
        if not isinstance(news, dict) or not news:
            return "invalid", None
        if news.get("is_deleted"):
            return "deleted", None
        if not (str(news.get("id") or "") and news.get("title") and news.get("created_at")):
            return "invalid", None
        return "valid", news
    return "transient", None


async def _newest(client: httpx.AsyncClient, budget: _Budget):
    """top-stories → (max_id|None, known_ids). 스키마 붕괴/빈 값이면 (None, [])."""
    await budget.throttle()
    budget.spend()
    try:
        r = await client.get(f"{_BASE}/news/top-stories", timeout=DETAIL_TIMEOUT_S)
        r.raise_for_status()
        lst = r.json().get("news_list") or []
    except Exception:  # noqa: BLE001
        return None, []
    ids = []
    for it in lst:
        try:
            ids.append(int(it.get("id")))
        except (TypeError, ValueError):
            continue
    if not ids:
        return None, []
    return max(ids), ids


async def _collect_calendar(client: httpx.AsyncClient, budget: _Budget):
    """매크로 캘린더(향후 14일, ★≥2 또는 연준 발언). (obs, ok). 비200이면 ([], False)."""
    import datetime as _dt
    await budget.throttle()
    budget.spend()
    today = _dt.date.today()
    try:
        cal = await client.get(f"{_BASE}/calendar/events", params={
            "start_date": today.isoformat(),
            "end_date": (today + _dt.timedelta(days=14)).isoformat()},
            timeout=DETAIL_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return [], False
    if cal.status_code != 200:
        return [], False
    obs: list[MetricObservation] = []
    for ev in cal.json().get("events", []) or []:
        title = ev.get("title") or ""
        stars = len(_STAR.findall(title))
        is_fed = "투표권" in title
        if stars >= 2 or is_fed:
            obs.append(MetricObservation(
                metric="macro_calendar", ts=(ev.get("event_date") or "")[:10],
                value=float(stars), unit="stars",
                meta={"title": title, "provider": "saveticker",
                      "kind": "fed_speech" if is_fed else "macro"}))
    return obs, True


async def _frontier_probe(client, anchor: int, budget: _Budget, counts: dict) -> int:
    """anchor 위로 MISS_STOP 연속 404까지 → 마지막 valid(없으면 anchor)."""
    idx, miss, last_valid = anchor + 1, 0, anchor
    while budget.ok() and miss < MISS_STOP:
        k, _news = await _classify_detail(client, idx, budget)
        counts[k] = counts.get(k, 0) + 1
        if k == "valid":
            last_valid = idx
            miss = 0
        elif k == "not_found":
            miss += 1
        else:
            miss = 0
        idx += 1
    return last_valid


def _liveness(counts, pending_len, anchor_advanced, valid_ct, cal_ok):
    if pending_len >= PENDING_MAX:
        return "error", f"pending overflow={pending_len}"
    if anchor_advanced and valid_ct == 0:
        return "error", "anchor advanced but 0 valid"
    seen_cls = counts.get("valid", 0) + counts.get("invalid", 0)
    if seen_cls and counts.get("invalid", 0) / seen_cls > 0.3:
        return "error", "invalid ratio high"
    if counts.get("transient", 0) > 0 or pending_len > 0 or not cal_ok:
        return "degraded", (f"transient={counts.get('transient', 0)} "
                            f"pending={pending_len} cal_ok={cal_ok}")
    return "ok", ""


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(headers=_UA)
    try:
        budget = _Budget(CYCLE_CAP, MAX_ELAPSED_S, REQUEST_INTERVAL_S)
        counts = {k: 0 for k in ("valid", "deleted", "not_found", "transient", "invalid")}
        docs: list[dict] = []

        anchor_now, known = await _newest(client, budget)
        cal_obs, cal_ok = await _collect_calendar(client, budget)
        if anchor_now is None:
            return CollectorResult(name=NAME, kind=KIND, observations=cal_obs,
                                   status="error", detail="top-stories drift",
                                   stats={"calendar_ok": cal_ok})

        # canary (seen 미오염 — 별도 호출)
        canary_kinds = [(await _classify_detail(client, k, budget))[0]
                        for k in known[:CANARY_SAMPLE]]
        if canary_kinds and all(k in ("not_found", "invalid") for k in canary_kinds):
            return CollectorResult(name=NAME, kind=KIND, observations=cal_obs,
                                   status="error", detail="detail canary fail",
                                   stats={"canary": canary_kinds, "calendar_ok": cal_ok})

        cursor = store.get_state("saveticker_scan_hwm")
        observed_anchor = store.get_state("saveticker_observed_anchor") or 0
        cutover_floor = store.get_state("saveticker_cutover_floor")
        anchor = max(observed_anchor, anchor_now)

        if cursor is None:                                     # 시딩
            hwm = await _frontier_probe(client, anchor, budget, counts)
            store.set_states({"saveticker_scan_hwm": hwm,
                              "saveticker_observed_anchor": max(anchor, hwm),
                              "saveticker_cutover_floor": hwm,
                              "saveticker_pending": {}, "saveticker_retry_pos": 0})
            return CollectorResult(name=NAME, kind=KIND, observations=cal_obs,
                                   status="degraded", detail=f"seeded={hwm}",
                                   stats={"seeded": hwm, "calendar_ok": cal_ok, **counts})

        pending = dict(store.get_state("saveticker_pending") or {})
        retry_pos = int(store.get_state("saveticker_retry_pos") or 0)
        seen: set[int] = set()
        overflow = False

        # (1) pending 재시도 — 실제 요청수·시간 예약
        pids = sorted(int(k) for k in pending)
        rot = []
        if pids:
            off = retry_pos % len(pids)
            rot = pids[off:] + pids[:off]
        start_req = budget.requests()
        max_req_item = 1 + RETRY_TRANSIENT
        processed = 0
        for pid in rot:
            if (not budget.ok()
                    or budget.requests() - start_req + max_req_item > PENDING_BUDGET
                    or budget.elapsed() >= PENDING_ELAPSED_S):
                break
            seen.add(pid)
            k, news = await _classify_detail(client, pid, budget)
            counts[k] += 1
            if k == "valid":
                docs.append(news)
                pending.pop(str(pid), None)
            elif k in ("deleted", "not_found"):
                pending.pop(str(pid), None)
            else:
                prev = pending.get(str(pid), {}).get("attempts", 0)
                pending[str(pid)] = {"kind": k, "attempts": prev + 1}
            processed += 1
        retry_pos += processed

        # (2) region A: scan_hwm+1 .. anchor
        idx = int(cursor) + 1
        while idx <= anchor and budget.ok():
            if idx in seen or str(idx) in pending:
                idx += 1
                continue
            seen.add(idx)
            k, news = await _classify_detail(client, idx, budget)
            counts[k] += 1
            if k == "valid":
                docs.append(news)
            elif k in ("deleted", "not_found"):
                pass
            else:
                if len(pending) >= PENDING_MAX:
                    overflow = True
                    break
                pending[str(idx)] = {"kind": k, "attempts": 1}
            idx += 1
        scan_hwm = min(idx - 1, anchor)
        max_valid = scan_hwm

        # (3) region B: anchor+1 .. frontier (overflow면 생략)
        stop_reason = "budget"
        if not overflow:
            miss = 0
            while budget.ok() and miss < MISS_STOP:
                if idx in seen or str(idx) in pending:
                    idx += 1
                    continue
                seen.add(idx)
                k, news = await _classify_detail(client, idx, budget)
                counts[k] += 1
                if k == "valid":
                    docs.append(news)
                    max_valid = idx
                    anchor = idx
                    miss = 0
                elif k == "not_found":
                    miss += 1
                elif k == "deleted":
                    miss = 0
                else:
                    if len(pending) >= PENDING_MAX:
                        overflow = True
                        break
                    pending[str(idx)] = {"kind": k, "attempts": 1}
                    miss = 0
                idx += 1
            scan_hwm = max(scan_hwm, max_valid)
            if miss >= MISS_STOP:
                stop_reason = "frontier"

        added = store.append_raw_news([_doc_from(n) for n in docs])
        new_anchor = max(anchor, max_valid, observed_anchor, anchor_now)
        store.set_states({"saveticker_scan_hwm": scan_hwm,
                          "saveticker_observed_anchor": new_anchor,
                          "saveticker_pending": pending, "saveticker_retry_pos": retry_pos})

        cands = sorted((n for n in docs
                        if _relevant((n.get("title") or "") + " " + _to_text(n)[:200])),
                       key=lambda n: int(n.get("id") or 0), reverse=True)[:CARD_CANDIDATE_CAP]
        items = [_raw_news_item(n) for n in cands]

        status, detail = _liveness(counts, len(pending),
                                   new_anchor > observed_anchor, counts["valid"], cal_ok)
        if overflow:
            status, detail = "error", f"pending overflow={len(pending)}"
        stats = {**counts, "scan_hwm": scan_hwm, "observed_anchor": new_anchor,
                 "cutover_floor": cutover_floor, "backlog": new_anchor - scan_hwm,
                 "scanned": budget.requests(), "stop_reason": stop_reason,
                 "pending_len": len(pending), "raw_added": added, "calendar_ok": cal_ok}
        return CollectorResult(name=NAME, kind=KIND, items=items, observations=cal_obs,
                               status=status, detail=detail, stats=stats)
    finally:
        if own:
            await client.aclose()
