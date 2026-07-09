"""골든셋 실행기 — `.venv/bin/python -m evals.run_eval --limit 5 --type fact_lookup`.

질문마다 run_qa를 돌려 layer/final을 수집, metrics 레코드를 JSONL로 저장.
요약(md)에 유형별 평균 + 수동 샘플링용 무작위 5문항 답변 전문 포함.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from pathlib import Path

from evals.metrics import keyword_check, question_metrics
from orchestrator import run_qa

_HERE = Path(__file__).parent


async def _one(row: dict) -> dict:
    layers, final = [], None
    async for ev in run_qa(row["question"]):
        if ev.get("kind") == "layer":
            layers.append(ev)
        elif ev.get("kind") == "final":
            final = ev
    meta = (final or {}).get("meta") or {}
    answer = (final or {}).get("answer", "")
    rec = {"id": row["id"], "type": row["type"], "question": row["question"],
           **question_metrics(layers, meta)}
    ok, missing, hit = keyword_check(answer, row.get("must_include", []),
                                     row.get("must_not", []))
    rec.update({"keyword_ok": ok, "missing": missing, "must_not_hit": hit,
                "answer_md": answer})
    return rec


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--type", default="")
    args = ap.parse_args()
    rows = [json.loads(l) for l in (_HERE / "golden.jsonl").read_text().splitlines() if l.strip()]
    if args.type:
        rows = [r for r in rows if r["type"] == args.type]
    if args.limit:
        rows = rows[:args.limit]
    out_dir = _HERE / "out"
    out_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    records = []
    for row in rows:  # 순차 — 비용·레이트리밋 통제 (병렬 금지)
        rec = await _one(row)
        records.append(rec)
        print(f"[{rec['id']}] verified={rec['verified_ratio']} "
              f"elapsed={rec['elapsed_s']}s cost=${rec['cost_usd']}")
    (out_dir / f"report-{ts}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records))
    # 요약 + 수동 샘플링 5문항
    lines = [f"# eval {ts} — {len(records)}문항", ""]
    for t in sorted({r["type"] for r in records}):
        sub = [r for r in records if r["type"] == t]
        vr = [r["verified_ratio"] for r in sub if r["verified_ratio"] is not None]
        lines.append(f"- **{t}** n={len(sub)} verified_avg="
                     f"{round(sum(vr)/len(vr), 3) if vr else 'n/a'} "
                     f"elapsed_avg={round(sum(r['elapsed_s'] for r in sub)/len(sub), 1)}s "
                     f"cost_avg=${round(sum(r['cost_usd'] for r in sub)/len(sub), 3)}")
    lines.append("\n## 수동 샘플링 (5문항 — 눈으로 확인)")
    for r in random.sample(records, min(5, len(records))):
        lines.append(f"\n### {r['id']} {r['question']}\n\n{r['answer_md'][:3000]}")
    (out_dir / f"report-{ts}.md").write_text("\n".join(lines))
    print(f"saved: evals/out/report-{ts}.jsonl / .md")


if __name__ == "__main__":
    asyncio.run(main())
