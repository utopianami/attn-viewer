"""수집기 레지스트리 — 1소스 1파일 (원칙 6). 모듈 규약: NAME, KIND, async collect(store, client=None)."""
from __future__ import annotations


def registry() -> list:
    from sector.collectors import (app_charts, brave_matrix, customs_kr, dart_edgar,
                                   datalab, ecos, kosis, mops_tw, openrouter, rss,
                                   saveticker, sdk_downloads, status_pages, yahoo_metrics)
    return [saveticker, brave_matrix, rss, dart_edgar,
            openrouter, status_pages, sdk_downloads, app_charts,
            mops_tw, customs_kr, kosis, ecos, datalab, yahoo_metrics]
