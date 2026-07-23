"""토스 회사 뉴스 상세 응답의 오프라인 계약 테스트."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.toss.models import NewsDetailResult  # noqa: E402


def test_localized_news_blocks_become_full_text():
    detail = NewsDetailResult.model_validate({
        "availableLanguages": ["kr"],
        "kr": {
            "content": [
                {"type": "summary", "content": "목록 요약", "caption": None},
                {"type": "image", "content": "https://example.test/image.jpg", "caption": "사진"},
                {"type": "text", "content": "첫 번째 본문 문단", "caption": None},
                {"type": "text", "content": "두 번째 본문 문단", "caption": None},
            ],
        },
    })

    assert detail.full_text() == "첫 번째 본문 문단\n\n두 번째 본문 문단"
    assert "image.jpg" not in detail.full_text()
    assert "목록 요약" not in detail.full_text()


def test_legacy_content_text_remains_supported():
    detail = NewsDetailResult.model_validate({"contentText": "구형 기사 본문"})

    assert detail.full_text() == "구형 기사 본문"


def test_summary_is_fallback_when_text_blocks_are_absent():
    detail = NewsDetailResult.model_validate({
        "kr": {"content": [{"type": "summary", "content": "요약만 있는 기사"}]},
    })

    assert detail.full_text() == "요약만 있는 기사"
