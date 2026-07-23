# engine/evals/build_chain_cases.py
"""chain eval 케이스 도구 — capture(전향 즉시 가동)/list/validate."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from evals.bundle import capture_bundle
from sector.api import _get_store

_HERE = Path(__file__).parent

# auto-live 기본 티커셋 (proven 케이스용 quote 채널)
_AUTO_LIVE_TICKERS = ["005930.KS", "000660.KS", "MU", "NVDA", "^KS11", "KRW=X"]


def _collect_live_prices() -> dict:
    """yahoo.quote으로 기본 티커셋 시세 수집 — asyncio.run 래핑."""
    from tools.price.yahoo import quote
    rows = asyncio.run(quote(_AUTO_LIVE_TICKERS))
    return {"quotes": rows}


def _collect_live_macro() -> dict:
    """macro.collect_macro로 매크로 수집 — asyncio.run 래핑."""
    from tools.price.macro import collect_macro
    return asyncio.run(collect_macro())


def cmd_list(args) -> None:
    """store의 magnitude≥2 카드를 --since 이후 날짜순 출력 + 주별 분포."""
    store = _get_store()
    cards = store.read_cards(days=None, limit=100_000)

    since = getattr(args, "since", None)
    if since:
        cards = [c for c in cards if c.ts[:10] >= since]

    cards = [c for c in cards if c.magnitude >= 2]
    cards.sort(key=lambda c: c.ts)

    # 주별 분포
    from collections import Counter
    week_counts: Counter = Counter()
    for c in cards:
        try:
            import datetime as _dt
            d = _dt.date.fromisoformat(c.ts[:10])
            week_key = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
        except Exception:
            week_key = "unknown"
        week_counts[week_key] += 1

    print(f"총 {len(cards)}건 (magnitude≥2{', since=' + since if since else ''})")
    print()
    for c in cards:
        print(f"{c.ts[:10]}  [{c.magnitude}] {c.axis:8s}  {c.title[:80]}")
    print()
    print("── 주별 분포 ──")
    for week in sorted(week_counts):
        print(f"  {week}: {week_counts[week]}건")


def cmd_validate(args) -> None:
    from evals.bundle import EvalBundle, resolve_bundle_path
    rows = [json.loads(l) for l in (_HERE / "golden_chain.jsonl").read_text().splitlines()
            if l.strip()]
    errs: list[str] = []
    for r in rows:
        if "split" not in r:
            errs.append(f"{r['id']}: split 필드 없음")
            continue
        b = EvalBundle(resolve_bundle_path(r, base=_HERE))
        if not b.verify_hash():
            errs.append(f"{r['id']}: bundle hash 불일치")
        if r["availability"] != b.manifest["availability"]:
            errs.append(f"{r['id']}: availability 불일치 (case vs manifest)")   # B10
        if r["split"] == "holdout" and r["availability"] != "proven":
            errs.append(f"{r['id']}: holdout은 proven만")                        # B10
        if r["as_of"] != b.manifest["as_of"]:
            errs.append(f"{r['id']}: as_of 불일치")
        btxt = b.bundle_text(max_chars=200_000)
        for ev in r["rubric"]["evidence"]:
            if ev not in btxt:
                errs.append(f"{r['id']}: rubric evidence '{ev}'가 bundle에 없음")
        if not b.manifest["card_ids"]:
            errs.append(f"{r['id']}: 빈 bundle")
    if errs:
        raise SystemExit("\n".join(errs))
    print(f"OK: {len(rows)} cases")


def cmd_capture(args) -> None:
    # --auto-live + --prices/--macro 동시 지정은 혼동 방지로 에러 거부
    if args.auto_live and (args.prices or args.macro):
        raise SystemExit(
            "오류: --auto-live와 --prices/--macro 파일 인자는 동시에 사용할 수 없습니다. "
            "자동 수집 또는 파일 지정 중 하나만 선택하세요."
        )

    # proven인데 수집 소스가 없으면 명확한 에러
    if args.availability == "proven" and not args.auto_live and not (args.prices or args.macro):
        raise SystemExit(
            "오류: proven 캡처는 --auto-live 또는 --prices/--macro 파일이 필요합니다. "
            "(prices·macro 채널 없으면 capture_bundle이 거부합니다)"
        )

    # ra_docs 로드
    ra_docs: list[dict] = (
        json.loads(Path(args.ra_docs).read_text()) if args.ra_docs else []
    )

    # prices·macro: auto-live이면 수집, 파일이면 파일 로드
    if args.auto_live:
        prices = _collect_live_prices()
        macro = _collect_live_macro()
    else:
        prices = json.loads(Path(args.prices).read_text()) if args.prices else {}
        macro = json.loads(Path(args.macro).read_text()) if args.macro else {}

    # --allow-empty-ra 처리
    empty_reasons: dict[str, str] = {}
    if args.allow_empty_ra:
        empty_reasons["ra"] = args.allow_empty_ra

    # thesis 자동 배선 — store root에 theses.jsonl 있으면 포함, --no-thesis로 옵트아웃 (2부 T7).
    # kwarg는 실제로 배선할 때만 전달 — thesis_store 파라미터가 없는 구형 capture_bundle
    # 스텁(테스트 monkeypatch)과의 하위호환 유지.
    store = _get_store()
    capture_kwargs: dict = {}
    root = getattr(store, "root", None)
    if (root is not None and not getattr(args, "no_thesis", False)
            and (Path(root) / "theses.jsonl").exists()):
        from sector.thesis_store import ThesisStore
        capture_kwargs["thesis_store"] = ThesisStore(root)

    out = capture_bundle(
        store, _HERE / "bundles" / args.case,
        as_of=args.as_of, availability=args.availability,
        ra_docs=ra_docs,
        prices=prices,
        macro=macro,
        empty_reasons=empty_reasons if empty_reasons else None,
        **capture_kwargs,
    )
    print(f"captured: {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    # list 서브커맨드
    p_list = sub.add_parser("list", help="magnitude≥2 카드를 날짜순 출력 + 주별 분포")
    p_list.add_argument("--since", default="", help="YYYY-MM-DD 이후 카드만 (포함)")

    # validate 서브커맨드
    sub.add_parser("validate", help="golden_chain.jsonl 전 케이스 검증")

    # capture 서브커맨드
    p = sub.add_parser("capture")
    p.add_argument("--case", required=True)
    p.add_argument("--as-of", dest="as_of", required=True)
    p.add_argument("--availability", required=True, choices=["proven", "unproven"])
    p.add_argument("--ra-docs", dest="ra_docs", default="")
    p.add_argument("--prices", default="")
    p.add_argument("--macro", default="")
    p.add_argument("--auto-live", action="store_true",
                   help="quotes·macro를 yahoo/collect_macro로 자동 수집 (proven 필수)")
    p.add_argument("--allow-empty-ra", default="",
                   help="RA 빈 채널 사유 — capture_bundle empty_reasons['ra']로 전달")
    p.add_argument("--no-thesis", dest="no_thesis", action="store_true",
                   help="store root에 theses.jsonl이 있어도 thesis 자동 배선을 끔 (2부 T7)")

    args = ap.parse_args()
    {"capture": cmd_capture, "list": cmd_list, "validate": cmd_validate}[args.cmd](args)


if __name__ == "__main__":
    main()
