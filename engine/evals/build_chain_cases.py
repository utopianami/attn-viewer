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

    out = capture_bundle(
        _get_store(), _HERE / "bundles" / args.case,
        as_of=args.as_of, availability=args.availability,
        ra_docs=ra_docs,
        prices=prices,
        macro=macro,
        empty_reasons=empty_reasons if empty_reasons else None,
    )
    print(f"captured: {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
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
    args = ap.parse_args()
    {"capture": cmd_capture}[args.cmd](args)


if __name__ == "__main__":
    main()
