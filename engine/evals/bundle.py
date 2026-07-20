# engine/evals/bundle.py
"""frozen evidence bundle (스펙 1부). capture는 불변 — 덮어쓰기 거부 + content hash."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


def _content_hash(root: Path, manifest: dict) -> str:
    """상대경로+파일 내용 + content_hash 제외 manifest 정규형을 함께 해시 (r2-B3 —
    manifest의 as_of/availability/urls 변조도 hash로 잡는다)."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    canon = {k: v for k, v in manifest.items() if k != "content_hash"}
    h.update(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()[:16]


def capture_bundle(store, out_dir: Path | str, *, as_of: str, availability: str,
                   ra_docs: list[dict], prices: dict, macro: dict,
                   empty_reasons: dict[str, str] | None = None) -> Path:
    """proven 불변식은 이 함수가 강제한다 (r3-B4 — CLI·운영 문구가 아니라 코드):
    proven인데 채널이 비면 empty_reasons에 채널별 사유 필수, 없으면 ValueError."""
    out = Path(out_dir)
    empty_reasons = empty_reasons or {}
    if out.exists():
        raise FileExistsError(f"bundle exists — 불변성 위반 금지: {out}")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if availability == "proven":
        if as_of != today:
            raise ValueError(f"proven은 as_of=captured_at({today})만 허용 (스펙 r4-B4)")
        for ch, empty in (("ra", not ra_docs), ("quotes", not prices.get("quotes")),
                          ("macro", not macro)):
            if empty and ch not in empty_reasons:
                raise ValueError(f"proven인데 {ch} 채널이 비어 있음 — 사유 필수 (r3-B4)")
    (out / "metrics").mkdir(parents=True)
    cards = [c for c in store.read_cards(days=None, limit=100_000)
             if c.ts[:10] <= as_of]                     # limit=500 함정 회피 (B4)
    (out / "cards.jsonl").write_text("\n".join(c.model_dump_json() for c in cards))
    metric_names = sorted(p.stem for p in (Path(store.root) / "metrics").glob("*.jsonl"))
    for m in metric_names:
        rows = [o for o in store.read_metric(m, last_n=100_000) if o.ts[:10] <= as_of]
        (out / "metrics" / f"{m}.jsonl").write_text(
            "\n".join(o.model_dump_json() for o in rows))
    dated = [d for d in ra_docs
             if (d.get("published_at") or "")[:10] and d["published_at"][:10] <= as_of]
    (out / "ra_docs.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in dated))
    (out / "prices.json").write_text(json.dumps(prices, ensure_ascii=False))
    (out / "macro.json").write_text(json.dumps(macro, ensure_ascii=False))
    manifest = {"as_of": as_of, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                             time.gmtime()),
                "availability": availability, "card_ids": [c.id for c in cards],
                "urls": sorted({c.url for c in cards if c.url}
                               | {d["url"] for d in dated if d.get("url")}),
                "metric_names": metric_names, "thesis_revisions": [],  # 2부에서 채움
                "news_ids": [d["id"] for d in dated if d.get("id")],
                # 실제 ref는 yahoo:{q["symbol"]} (price_macro.py:42) — token 폴백 없음
                # (r6: symbol 없는 quote 행은 provenance 등록 불가 = 인용 불가가 맞다)
                "quote_symbols": [q["symbol"] for q in prices.get("quotes", [])
                                  if q.get("symbol")],
                "macro_keys": sorted(macro.keys()),
                "empty_channel_reasons": empty_reasons,   # proven 검증용 (r3-B4)
                "dropped_undated_docs": len(ra_docs) - len(dated)}
    manifest["content_hash"] = _content_hash(out, manifest)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    return out
