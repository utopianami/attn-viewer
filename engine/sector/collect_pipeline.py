"""One-shot memory-sector collection entry point for the scheduler worker."""

from __future__ import annotations

import asyncio
import logging

from sector.api import _get_store
from sector.runner import collect_all

logger = logging.getLogger(__name__)


async def _run() -> int:
    try:
        results = await collect_all(_get_store())
    except Exception:  # noqa: BLE001 - CLI boundary must return a useful status
        logger.exception("sector collection pipeline failed")
        return 1
    failures = sum(result.status == "error" for result in results)
    logger.info(
        "sector collection pipeline completed: collectors=%d errors=%d",
        len(results),
        failures,
    )
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
