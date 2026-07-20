# engine/evals/build_chain_cases.py
"""chain eval 케이스 도구 — capture(전향 즉시 가동)/list/validate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.bundle import capture_bundle
from sector.api import _get_store

_HERE = Path(__file__).parent


def cmd_capture(args) -> None:
    out = capture_bundle(
        _get_store(), _HERE / "bundles" / args.case,
        as_of=args.as_of, availability=args.availability,
        ra_docs=json.loads(Path(args.ra_docs).read_text()),
        prices=json.loads(Path(args.prices).read_text()),
        macro=json.loads(Path(args.macro).read_text()))
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
    # cmd_capture 배선: --auto-live면 quotes/macro 자동 수집 결과를 prices·macro로,
    # --allow-empty-ra면 empty_reasons={"ra": 사유}. proven인데 --auto-live도
    # --prices/--macro 파일도 없으면 capture_bundle이 ValueError로 거부 (r3-B4)


if __name__ == "__main__":
    main()
