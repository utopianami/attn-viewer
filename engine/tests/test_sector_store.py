"""메모리 섹터 저장소 — 카드/지표 jsonl append·dedup·조회 (P1 Task 1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import CollectorResult, MetricObservation, RawNewsDoc, RawNewsItem, SectorCard  # noqa: E402
from sector.store import SectorStore  # noqa: E402


def _card(cid="c1", ts="2026-07-06T09:00:00Z", axis="B"):
    return SectorCard(
        id=cid, ts=ts, axis=axis, entities=["META"], edge="B->A",
        event_type="demand_signal", memory_segment="hbm", direction="neg",
        magnitude=2, time_horizon="immediate", source_grade="B",
        title="t", raw_quote="rq", interpreted_signal="is", url="http://x", source="reuters.com",
    )


def test_card_defaults():
    c = _card()
    assert c.speaker is None and c.numeric is None


def test_append_and_read_cards_dedup(tmp_path):
    s = SectorStore(tmp_path)
    n1 = s.append_cards([_card("a"), _card("b")])
    n2 = s.append_cards([_card("b"), _card("c")])   # b는 중복
    assert (n1, n2) == (2, 1)
    got = s.read_cards(days=None)
    assert sorted(c.id for c in got) == ["a", "b", "c"]


def test_read_raw_news_sorted_by_parsed_time(tmp_path):
    s = SectorStore(tmp_path)
    s.append_raw_news([
        RawNewsDoc(id="1", title="BOJ", created_at="2026-07-21T16:23:13+09:00"),  # 07:23Z
        RawNewsDoc(id="2", title="MU",  created_at="2026-07-21T09:00:00+00:00"),  # 09:00Z (더 최신)
    ])
    got = s.read_raw_news()                     # months=None, limit=None → 전체 무제한
    assert [d.id for d in got] == ["2", "1"]    # 파싱 datetime 내림차순 (문자열 정렬이면 틀림)
    assert s.read_raw_news(months=[]) == []     # 빈 리스트는 "선택 없음"(전체 아님)


def test_read_raw_news_dedups_by_id_across_partitions(tmp_path):
    s = SectorStore(tmp_path)
    (s.root / "news_raw").mkdir(parents=True, exist_ok=True)
    (s.root / "news_raw" / "2026-06.jsonl").write_text(
        RawNewsDoc(id="dup", title="jun", created_at="2026-06-30T23:00:00+00:00").model_dump_json() + "\n",
        encoding="utf-8")
    (s.root / "news_raw" / "2026-07.jsonl").write_text(
        RawNewsDoc(id="dup", title="jul", created_at="2026-07-01T01:00:00+00:00").model_dump_json() + "\n",
        encoding="utf-8")
    got = s.read_raw_news()
    assert [d.id for d in got] == ["dup"]       # 교차파티션 중복 1건으로
    assert got[0].title == "jul"                # 최신(파싱시각 큰) 것이 남음


def test_read_cards_filters(tmp_path):
    s = SectorStore(tmp_path)
    s.append_cards([_card("a", ts="2026-07-06T09:00:00Z", axis="B"),
                    _card("b", ts="2020-01-01T00:00:00Z", axis="C")])
    assert [c.id for c in s.read_cards(days=30)] == ["a"]
    assert [c.id for c in s.read_cards(days=None, axis="C")] == ["b"]
    assert [c.id for c in s.read_cards(days=None, entity="META")] and \
           s.read_cards(days=None, entity="NVDA") == []


def test_observations_dedup_and_read(tmp_path):
    s = SectorStore(tmp_path)
    o = MetricObservation(metric="token_price", ts="2026-07-06", value=15.0,
                          unit="usd_per_1m", meta={"model": "sonnet"})
    n1 = s.append_observations([o]); n2 = s.append_observations([o])
    assert (n1, n2) == (1, 0)
    rows = s.read_metric("token_price", last_n=10)
    assert rows[0].value == 15.0


def test_state_roundtrip(tmp_path):
    s = SectorStore(tmp_path)
    assert s.get_state("cursor") is None
    s.set_state("cursor", 161424)
    assert SectorStore(tmp_path).get_state("cursor") == 161424


def test_status_roundtrip(tmp_path):
    s = SectorStore(tmp_path)
    r = CollectorResult(name="saveticker", kind="news", status="ok", took_ms=12)
    s.write_status([r])
    st = s.read_status()
    assert st["saveticker"]["status"] == "ok"


def test_raw_news_item_defaults():
    it = RawNewsItem(id="1", title="t")
    assert it.grade_hint is None and it.extra == {}


def test_metric_observation_source_roundtrips_with_and_without():
    """2부 T1 — source 필드는 기본값 ""로 하위호환, 값이 있으면 보존."""
    bare = MetricObservation(metric="token_price", ts="2026-07-06", value=1.0)
    assert bare.source == ""
    assert MetricObservation.model_validate_json(bare.model_dump_json()) == bare

    with_source = MetricObservation(metric="token_price", ts="2026-07-06", value=1.0,
                                     source="openrouter")
    assert with_source.source == "openrouter"
    assert MetricObservation.model_validate_json(with_source.model_dump_json()) == with_source

    # 기존 저장분(키 없음)도 그대로 로드돼야 함
    legacy = MetricObservation.model_validate({"metric": "token_price", "ts": "2026-07-06",
                                                "value": 1.0})
    assert legacy.source == ""


def test_read_cards_skips_corrupted_lines(tmp_path):
    """index.jsonl에 손상 줄이 있어도 valid 카드는 정상 반환 (I2 resilience)."""
    s = SectorStore(tmp_path)
    s.append_cards([_card("good1"), _card("good2")])
    # 중간에 garbage 줄 삽입
    with open(s._index, "a", encoding="utf-8") as f:
        f.write("not json\n")
    # good2 뒤에 또 다른 정상 카드를 raw jsonl로 삽입
    extra = _card("good3")
    with open(s._index, "a", encoding="utf-8") as f:
        f.write(extra.model_dump_json() + "\n")
    cards = s.read_cards(days=None)
    ids = {c.id for c in cards}
    assert ids == {"good1", "good2", "good3"}


def test_read_metric_skips_corrupted_lines(tmp_path):
    """metrics jsonl에 손상 줄이 있어도 valid 관측은 정상 반환 (I2 resilience)."""
    from sector.contracts import MetricObservation
    s = SectorStore(tmp_path)
    o1 = MetricObservation(metric="test_m", ts="2026-07-01", value=1.0)
    o2 = MetricObservation(metric="test_m", ts="2026-07-02", value=2.0)
    s.append_observations([o1])
    p = s._metric_path("test_m")
    with open(p, "a", encoding="utf-8") as f:
        f.write("not json\n")
        f.write(o2.model_dump_json() + "\n")
    rows = s.read_metric("test_m", last_n=10)
    assert len(rows) == 2
    assert rows[0].value == 1.0 and rows[1].value == 2.0


def test_observation_key_distinguishes_ecosystem_country_item():
    """Task 5 발견 결함 회귀 — 동명 패키지(pypi/npm)·국가별 앱·지표 item은 같은 ts에 공존."""
    base = dict(metric="sdk_downloads", ts="2026-07-06", value=1.0)
    a = MetricObservation(**base, meta={"pkg": "openai", "ecosystem": "pypi"})
    b = MetricObservation(**base, meta={"pkg": "openai", "ecosystem": "npm"})
    assert a.key() != b.key()
    c = MetricObservation(metric="app_rank", ts="2026-07-06", value=1.0,
                          meta={"app": "ChatGPT", "country": "us"})
    d = MetricObservation(metric="app_rank", ts="2026-07-06", value=2.0,
                          meta={"app": "ChatGPT", "country": "kr"})
    assert c.key() != d.key()
    e = MetricObservation(metric="kr_semi_production_index", ts="2026-06", value=1.0,
                          meta={"item": "재고"})
    f = MetricObservation(metric="kr_semi_production_index", ts="2026-06", value=2.0,
                          meta={"item": "출하"})
    assert e.key() != f.key()
