"""Micron 10-K MD&A 수집 — EDGAR 인덱스(corpus/edgar_micron_submissions*.json) 기반.

기존 corpus/micron_10k.jsonl에 없는 연도의 10-K 본문을 내려받아 MD&A 구간을
추출해 append. 스키마 {date, source, url, content}는 기존 항목과 동일.

  .venv/bin/python scripts/fetch_micron_10k.py [--dry-run]

SEC 요건: User-Agent 필수, 초당 10요청 미만(여기선 0.5s 간격).
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "storage/rag/case_memory/corpus"
OUT = CORPUS / "micron_10k.jsonl"
CIK = "723125"
UA = {"User-Agent": "attn-viewer research yeongnam@t1.gg"}

MDA_START = re.compile(r"MANAGEMENT[’'`]?S\s+DISCUSSION\s+AND\s+ANALYSIS", re.I)
# 종료 1순위: Item 7A(1997~). 2순위(초기 연도 폴백): Item 8 — 본문 상호참조로
# 조기 매칭될 수 있어 1순위가 없을 때만 사용.
MDA_END1 = re.compile(
    r"QUANTITATIVE\s+AND\s+QUALITATIVE\s+DISCLOSURES?\s+ABOUT\s+MARKET\s+RISK"
    r"|ITEM\s+7A\b", re.I)
MDA_END2 = re.compile(
    r"ITEM\s+8[.\s]|FINANCIAL\s+STATEMENTS\s+AND\s+SUPPLEMENTARY", re.I)
TAG = re.compile(r"<[^>]+>")


def list_10ks() -> list[tuple[str, str, str]]:
    out = []
    for f in ("edgar_micron_submissions.json", "edgar_micron_submissions_001.json"):
        d = json.loads((CORPUS / f).read_text())
        r = d.get("filings", {}).get("recent") or d
        for fo, a, doc, dt in zip(r.get("form", []), r.get("accessionNumber", []),
                                  r.get("primaryDocument", []), r.get("filingDate", [])):
            if fo in ("10-K", "10-K405"):      # 10-K405 = 1996~2002 당시 양식명
                out.append((dt, a, doc))
    return sorted(set(out))


def doc_url(acc: str, doc: str) -> str:
    if doc:
        return (f"https://www.sec.gov/Archives/edgar/data/{CIK}/"
                f"{acc.replace('-', '')}/{doc}")
    return f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc}.txt"


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)</(p|div|tr|br|h\d|li|table)>", "\n", html)
    text = unescape(TAG.sub(" ", html))
    text = text.replace(" ", " ")
    lines = [" ".join(ln.split()) for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def extract_mda(text: str) -> str | None:
    """MD&A 구간 — 목차 항목을 피하려고 '구간 길이가 유의미한' 마지막 시작점 채택."""
    starts = [m.start() for m in MDA_START.finditer(text)]
    best = ""
    for s in reversed(starts):
        m_end = MDA_END1.search(text, s + 100) or MDA_END2.search(text, s + 100)
        seg = text[s:m_end.start()] if m_end else text[s:]
        if len(seg) > 10_000:
            return seg[:400_000]
        best = max(best, seg, key=len)
    return best[:400_000] if len(best) > 5_000 else None


def main() -> int:
    dry = "--dry-run" in sys.argv
    have_years = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            have_years.add(json.loads(line)["date"][:4])

    added = 0
    with OUT.open("a", encoding="utf-8") as fout:
        for dt, acc, doc in list_10ks():
            if dt[:4] in have_years:
                continue
            url = doc_url(acc, doc)
            try:
                req = urllib.request.Request(url, headers=UA)
                raw = urllib.request.urlopen(req, timeout=60).read().decode(
                    "utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001
                print(f"{dt} 다운로드 실패: {exc} ({url})")
                continue
            mda = extract_mda(html_to_text(raw) if "<" in raw[:2000] else raw)
            if not mda:
                print(f"{dt} MD&A 추출 실패 (본문 {len(raw)}b) — 건너뜀")
                continue
            fy = int(dt[:4]) if int(dt[5:7]) >= 9 else int(dt[:4])
            row = {"date": dt, "source": f"Micron 10-K FY{fy}", "url": url,
                   "content": mda}
            print(f"{dt} FY{fy}: MD&A {len(mda):,}자 {'(dry)' if dry else ''}")
            if not dry:
                fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                added += 1
            time.sleep(0.5)
    print(f"추가 {added}건 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
