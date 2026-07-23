"""casemem 골드셋 평가 — 국면매칭 검색 품질 실측 (kg 서베이 P1).

골드셋(casemem_goldset.jsonl): 질의(signals+as_of) → 기대 사례/국면 + 룩어헤드 금지 목록.
메트릭: hit@1 / hit@3 / MRR / 국면 정확도 / 룩어헤드 위반(하드 게이트 — 있으면 exit 1).

실행:
  결정적 기준선:  .venv/bin/python -m evals.casemem_eval
  LLM 리랭크 비교: .venv/bin/python -m evals.casemem_eval --rerank
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.query import query_case_memory
from casemem.store import CaseStore

_HERE = Path(__file__).parent
GOLDSET_PATH = _HERE / "casemem_goldset.jsonl"
_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "storage" / "rag" / "case_memory"


def load_goldset(path: Path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        rows.append(json.loads(line))
    return rows


def _eval_one(row: dict, matches) -> dict:
    ids = [m.episode_id for m in matches]
    expect = row.get("expect_top")
    res: dict = {"qid": row["qid"], "got": ids[:3], "rank": None,
                 "hit1": None, "hit3": None, "rr": None, "phase_ok": None,
                 "forbid_hits": [f for f in row.get("forbid", []) if f in ids]}
    if expect:
        # accept: 사례 경계가 겹칠 때 복수 정답 허용(예: 2016 저점 = 2014-16 회복기이자
        # 2016-19 진입기) — 첫 등장 정답의 순위로 채점
        accepted = row.get("accept") or [expect]
        found = [ids.index(a) + 1 for a in accepted if a in ids]
        rank = min(found) if found else None
        res["rank"] = rank
        res["hit1"] = rank == 1
        res["hit3"] = rank is not None and rank <= 3
        res["rr"] = (1.0 / rank) if rank else 0.0
        if row.get("expect_phase") is not None:
            ph = next((m.matched_phase_order for m in matches
                       if m.episode_id == expect), None)
            res["phase_ok"] = ph == row["expect_phase"]
    return res


def _summarize(results: list[dict]) -> dict:
    def _avg(key):
        vals = [r[key] for r in results if r[key] is not None]
        return round(sum(1.0 if v is True else 0.0 if v is False else v
                         for v in vals) / len(vals), 3) if vals else None

    n_expect = sum(1 for r in results if r["hit1"] is not None)
    return {
        "n": len(results), "n_expect": n_expect,
        "hit@1": _avg("hit1"), "hit@3": _avg("hit3"), "mrr": _avg("rr"),
        "phase_acc": _avg("phase_ok"),
        "forbid_violations": sum(len(r["forbid_hits"]) for r in results),
    }


def evaluate_rows(store: CaseStore, rows: list[dict], *, k: int = 5,
                  query_fn=None) -> tuple[dict, list[dict]]:
    """query_fn 주입 시(리랭크 등) 그걸 쓰고, 기본은 결정적 검색."""
    if query_fn is None:
        def query_fn(signals, as_of, sector, k):
            return query_case_memory(store, signals=signals, as_of=as_of,
                                     sector=sector, k=k)
    results = []
    for row in rows:
        out = query_fn(row["signals"], row["as_of"],
                       row.get("sector", "memory"), k)
        results.append(_eval_one(row, out.matches))
    return _summarize(results), results


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(_DEFAULT_ROOT))
    ap.add_argument("--goldset", default=str(GOLDSET_PATH))
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--rerank", action="store_true",
                    help="LLM 구조 리랭크 포함(라이브 콜 — role casemem_rerank)")
    ap.add_argument("--json", help="요약+행별 결과 JSON 저장 경로")
    args = ap.parse_args(argv)

    store = CaseStore(args.root)
    rows = load_goldset(Path(args.goldset))

    query_fn = None
    if args.rerank:
        import asyncio

        from casemem.async_query import query_case_memory_async
        from providers import Role
        role = Role("casemem_rerank")

        def query_fn(signals, as_of, sector, k):
            return asyncio.run(query_case_memory_async(
                store, signals=signals, as_of=as_of, sector=sector, k=k,
                role=role))

    summary, results = evaluate_rows(store, rows, k=args.k, query_fn=query_fn)

    for r in results:
        mark = ("PASS" if r["hit1"] else "rank%s" % r["rank"] if r["rank"]
                else "MISS") if r["hit1"] is not None else "probe"
        forbid = f"  !!룩어헤드위반 {r['forbid_hits']}" if r["forbid_hits"] else ""
        print(f"{r['qid']:>4} {mark:>6}  top3={r['got']}{forbid}")
    print(json.dumps(summary, ensure_ascii=False))

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"summary": summary, "results": results, "rerank": args.rerank},
            ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if summary["forbid_violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
