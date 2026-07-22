"""증류 규칙(DistilledRule+evidence) 검증·적재 — 인용 원문대조 후 rules.jsonl append.

usage: ingest_rules.py <rules-*.jsonl가 있는 디렉토리> --corpus <glob>... [--index]
  --index: evidence를 코퍼스가 아니라 case_memory/index.jsonl(이미 검증된 인용)과 대조
규칙은 dict로 다루되 필수 키·evidence 원문대조를 강제. status는 candidate 고정.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED = ("id", "situation", "triggers", "connection", "provenance",
            "event_time", "knowable_at", "evidence")


def _norm(t: str) -> str:
    t = str(t)
    for a, b in (("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'),
                 ("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " ")):
        t = t.replace(a, b)
    return " ".join(t.split())


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    src_dir = Path(sys.argv[1])
    use_index = "--index" in sys.argv

    hay = ""
    if use_index:
        hay = _norm((repo / "storage/rag/case_memory/index.jsonl").read_text(encoding="utf-8"))
    elif "--corpus" in sys.argv:
        i = sys.argv.index("--corpus")
        for a in sys.argv[i + 1:]:
            if a.startswith("--"):
                break
            for p in (sorted(Path().glob(a)) or [Path(a)]):
                for line in p.read_text(encoding="utf-8").split("\n"):
                    if line.strip():
                        hay += " " + _norm(json.loads(line).get("content", ""))
    if not hay:
        print("코퍼스/인덱스 비었음")
        raise SystemExit(2)

    rules_path = repo / "storage/rag/case_memory/rules.jsonl"
    known = set()
    if rules_path.exists():
        for line in rules_path.read_text(encoding="utf-8").splitlines():
            try:
                known.add(json.loads(line)["id"])
            except Exception:  # noqa: BLE001
                continue

    ok = failed = 0
    with rules_path.open("a", encoding="utf-8") as out:
        for f in sorted(src_dir.glob("rules-*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except Exception as e:  # noqa: BLE001
                    print(f"[FAIL] {f.name}: JSON 파싱 실패 — {e}")
                    failed += 1
                    continue
                missing = [k for k in REQUIRED if k not in r]
                if missing:
                    print(f"[FAIL] {r.get('id','?')}: 필수키 누락 {missing}")
                    failed += 1
                    continue
                bad = [ev for ev in r["evidence"]
                       if len(_norm(ev.get("quote", ""))) < 20
                       or _norm(ev["quote"]) not in hay]
                if bad:
                    print(f"[FAIL] {r['id']}: 인용 원문대조 실패 {len(bad)}건 — {_norm(bad[0].get('quote',''))[:60]}")
                    failed += 1
                    continue
                if r["id"] in known:
                    continue
                r["status"] = "candidate"      # 검증 게이트 전 승격 금지
                known.add(r["id"])
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
                print(f"[OK] {r['id']}: 인용 {len(r['evidence'])}개 검증")
                ok += 1
    print(f"\n결과: {ok} 적재 / {failed} 실패")


if __name__ == "__main__":
    main()
