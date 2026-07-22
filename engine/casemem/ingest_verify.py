"""추출된 CaseEpisode 검증·적재 — 인용 원문대조(verbatim check) 포함.

에이전트가 뽑은 JSON을 그대로 믿지 않는다:
 1) pydantic 계약 검증
 2) 모든 evidence.quote가 코퍼스 원문에 실제로 존재하는지 substring 대조
 3) evidence.knowable_at이 해당 콜 날짜와 일치하는지
통과한 에피소드만 스토어에 적재. 실패는 사유와 함께 리포트(무성 누락 금지).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import CaseEpisode  # noqa: E402
from casemem.store import CaseStore  # noqa: E402


def load_corpus(corpus_path: Path) -> list[dict]:
    rows = []
    for line in corpus_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def verify_episode(ep: CaseEpisode, corpus: list[dict]) -> list[str]:
    """실패 사유 목록 반환(빈 리스트=통과)."""
    problems: list[str] = []

    def _norm(t: str) -> str:
        return " ".join(t.split())          # 공백·줄바꿈 정규화 후 대조

    by_date: dict[str, str] = {}
    for r in corpus:
        d = str(r["date"])[:10]
        by_date[d] = by_date.get(d, "") + "\n" + _norm(r["content"])   # 같은 날짜 문서 병합
    all_content = _norm(" ".join(r["content"] for r in corpus))

    for ph in ep.phases:
        for ev in ph.evidence:
            q = _norm(ev.quote)
            if len(q) < 20:
                problems.append(f"phase{ph.order}: 인용이 너무 짧음({len(q)}c): {q[:40]}")
                continue
            # 1차: 해당 콜 날짜 원문에서 대조, 2차: 전체 코퍼스에서 대조
            target = by_date.get(ev.knowable_at, "")
            if q in target:
                continue
            if q in all_content:
                problems.append(
                    f"phase{ph.order}: 인용은 실존하나 knowable_at({ev.knowable_at}) 콜 원문엔 없음: {q[:50]}")
            else:
                problems.append(f"phase{ph.order}: 인용 원문대조 실패(발명 의심): {q[:60]}")
    orders = [p.order for p in ep.phases]
    if orders != sorted(orders):
        problems.append(f"국면 순서 비정렬: {orders}")
    return problems


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    src_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if src_dir is None:
        print("usage: ingest_verify.py <dir with out-*.json> [--corpus <glob>...] [--wipe]")
        raise SystemExit(2)
    # --corpus 뒤 인자들 = 코퍼스 jsonl 경로(글롭 가능). 없으면 MU 기본.
    corpus_paths: list[Path] = []
    if "--corpus" in sys.argv:
        i = sys.argv.index("--corpus")
        for a in sys.argv[i + 1:]:
            if a.startswith("--"):
                break
            corpus_paths.extend(sorted(Path().glob(a)) or [Path(a)])
    if not corpus_paths:
        corpus_paths = [repo / "storage/rag/case_memory/corpus/mu_earnings_transcripts.jsonl"]
    corpus: list[dict] = []
    for cp in corpus_paths:
        corpus.extend(load_corpus(cp))
    print(f"[corpus] {len(corpus_paths)}개 파일, 문서 {len(corpus)}건")
    wipe = "--wipe" in sys.argv

    store_root = repo / "storage/rag/case_memory"
    if wipe:
        idx = store_root / "index.jsonl"
        if idx.exists():
            idx.unlink()
        for f in (store_root / "cases").rglob("*.json"):
            f.unlink()
        print("[wipe] 라이브 스토어 초기화(가짜 시드 제거)")

    store = CaseStore(store_root)
    ok = failed = 0
    for f in sorted(src_dir.glob("out-*.json")):
        try:
            ep = CaseEpisode.model_validate_json(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {f.name}: pydantic 검증 실패 — {e}")
            failed += 1
            continue
        problems = verify_episode(ep, corpus)
        if problems:
            print(f"[FAIL] {f.name} ({ep.id}) — {len(problems)}건:")
            for p in problems:
                print("   -", p)
            failed += 1
            continue
        added = store.append_episodes([ep])
        nev = sum(len(p.evidence) for p in ep.phases)
        print(f"[OK] {ep.id}: 국면 {len(ep.phases)}개, 검증된 인용 {nev}개, 적재 {added}")
        ok += 1
    print(f"\n결과: {ok} 적재 / {failed} 실패")


if __name__ == "__main__":
    main()
