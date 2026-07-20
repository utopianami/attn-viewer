# engine/tests/test_eval_bundle.py
import json
import time

import pytest

from evals.bundle import capture_bundle
from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore


def _card(cid: str, ts: str) -> SectorCard:
    # direction 허용값은 sector/contracts.py:22 — pos|neg|neutral|mixed
    return SectorCard(id=cid, ts=ts, axis="A", direction="pos", magnitude=2,
                      source_grade="A", title=f"t-{cid}", interpreted_signal="",
                      raw_quote=f"q-{cid}", url=f"https://a.example/{cid}",
                      entities=["SK하이닉스"])


def _seed(tmp_path, n_cards: int = 3) -> SectorStore:
    store = SectorStore(tmp_path / "sector")
    store.append_cards([_card(f"c-{i}", f"2026-07-{i+1:02d}T00:00:00") for i in range(n_cards)])
    store.append_observations([
        MetricObservation(metric="kr_semi_export", ts="2026-07-01", value=1.0, unit="k_usd"),
        MetricObservation(metric="kr_semi_export", ts="2026-07-15", value=2.0, unit="k_usd")])
    return store


def test_store_stamps_ingested_at(tmp_path):
    store = _seed(tmp_path)
    cards = store.read_cards(days=None, limit=100_000)
    assert all(c.ingested_at for c in cards)          # append가 스탬프
    obs = store.read_metric("kr_semi_export")
    assert all(o.ingested_at for o in obs)


def test_capture_refuses_overwrite_and_bad_proven(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b1", as_of="2026-07-02",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    with pytest.raises(FileExistsError):
        capture_bundle(store, tmp_path / "b1", as_of="2026-07-02",
                       availability="unproven", ra_docs=[], prices={}, macro={})
    with pytest.raises(ValueError):                    # 과거 as_of에 proven 금지
        capture_bundle(store, tmp_path / "b2", as_of="2026-07-02",
                       availability="proven", ra_docs=[], prices={}, macro={})
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with pytest.raises(ValueError):                    # r3-B4: 빈 채널 proven은 사유 없인 거부
        capture_bundle(store, tmp_path / "b3", as_of=today,
                       availability="proven", ra_docs=[], prices={}, macro={})
    capture_bundle(store, tmp_path / "b4", as_of=today, availability="proven",
                   ra_docs=[], prices={"quotes": [{"token": "005930.KS", "last": 1.0}]},
                   macro={"kospi": 1.0},
                   empty_reasons={"ra": "회고성 사건 — RA 미수집"})       # 사유 있으면 OK


def test_capture_filters_full_store_not_limit500(tmp_path):
    store = SectorStore(tmp_path / "sector")
    # 600건 적재 — 기본 limit=500 함정 검증 (store.py:53)
    store.append_cards([_card(f"c-{i}", "2026-07-01T00:00:00") for i in range(600)])
    out = capture_bundle(store, tmp_path / "b", as_of="2026-07-02",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["card_ids"]) == 600


def test_capture_fail_closed_and_manifest(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(
        store, tmp_path / "b", as_of="2026-07-10", availability="unproven",
        ra_docs=[{"id": "n1", "title": "t", "url": "https://n.example/x",
                  "published_at": "2026-07-09", "snippet": "s"},
                 {"id": "n2", "title": "t", "url": "https://n.example/undated",
                  "snippet": "s"}],
        prices={"quotes": [], "macro": {}}, macro={})
    m = json.loads((out / "manifest.json").read_text())
    assert m["dropped_undated_docs"] == 1
    assert "https://n.example/x" in m["urls"]
    assert "https://n.example/undated" not in m["urls"]
    assert m["content_hash"]                           # hash 존재
