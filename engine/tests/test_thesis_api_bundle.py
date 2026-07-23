import json

from evals.bundle import EvalBundle, capture_bundle
from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.thesis_store import ThesisStore
from tests.test_thesis_contracts import make_rev


def test_capture_snapshot_date_boundary_and_backcompat(tmp_path):
    store = SectorStore(tmp_path / "s")
    store.append_observations([MetricObservation(
        metric="kr_semi_export", ts="2026-07-01", value=1.0, unit="k_usd")])
    tstore = ThesisStore(tmp_path / "s")                     # store root 동일 위치 (B9)
    tstore.append(make_rev(valid_from="2026-07-20T09:00:00",
                           revision_id="hbm-tightness@2026-07-20T09:00:00"))
    tstore.append(make_rev(valid_from="2026-07-21T09:00:00", assessment="mixed",
                           revision_id="hbm-tightness@2026-07-21T09:00:00"))
    out = capture_bundle(store, tmp_path / "b", as_of="2026-07-20",
                         availability="unproven", ra_docs=[], prices={}, macro={},
                         thesis_store=tstore)
    b = EvalBundle(out)
    assert [t["revision_id"] for t in b.theses()] == \
        ["hbm-tightness@2026-07-20T09:00:00"]                # 당일 09시 revision 포함 (날짜 비교)
    m = json.loads((out / "manifest.json").read_text())
    assert m["thesis_revisions"] == ["hbm-tightness@2026-07-20T09:00:00"]
    assert b.verify_hash()
    # 하위호환: thesis 없는 기존 bundle
    out2 = capture_bundle(store, tmp_path / "b2", as_of="2026-07-20",
                          availability="unproven", ra_docs=[], prices={}, macro={})
    assert EvalBundle(out2).theses() == []


def test_cmd_capture_auto_wires_thesis(tmp_path, monkeypatch):   # B9 — 운영 경로
    import evals.build_chain_cases as bcc
    store = SectorStore(tmp_path / "s")
    store.append_observations([MetricObservation(
        metric="kr_semi_export", ts="2026-07-01", value=1.0, unit="k_usd")])
    ThesisStore(tmp_path / "s").append(make_rev(
        valid_from="2026-07-19T00:00:00",
        revision_id="hbm-tightness@2026-07-19T00:00:00"))
    monkeypatch.setattr(bcc, "_get_store", lambda: store)
    monkeypatch.setattr(bcc, "_HERE", tmp_path)              # bundles 출력 위치
    import argparse, json as _json
    ra = tmp_path / "ra.json"; ra.write_text("[]")
    pj = tmp_path / "p.json"; pj.write_text('{"quotes": []}')
    mj = tmp_path / "m.json"; mj.write_text("{}")
    args = argparse.Namespace(case="cj-t", as_of="2026-07-20", availability="unproven",
                              ra_docs=str(ra), prices=str(pj), macro=str(mj),
                              auto_live=False, allow_empty_ra="", no_thesis=False)
    bcc.cmd_capture(args)
    b = EvalBundle(tmp_path / "bundles" / "cj-t")
    assert len(b.theses()) == 1


def test_theses_api_empty_and_one_revision(tmp_path, monkeypatch):
    """GET /v1/sector/theses — T1 계약: 빈 store→{"theses": []}, revision 있으면 freshness 포함."""
    import asyncio

    import httpx
    from app.settings import settings

    monkeypatch.setattr(settings, "sector_storage_dir", str(tmp_path))
    monkeypatch.setattr(settings, "sector_scheduler_enabled", False)
    from app.main import app
    import sector.api as api
    api._STORE = None

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as c:
            r = await c.get("/v1/sector/theses")
            assert r.status_code == 200
            assert r.json() == {"theses": []}

            ThesisStore(tmp_path).append(make_rev(
                valid_from="2026-07-19T00:00:00",
                revision_id="hbm-tightness@2026-07-19T00:00:00"))
            r2 = await c.get("/v1/sector/theses")
            assert r2.status_code == 200
            body = r2.json()
            assert len(body["theses"]) == 1
            t = body["theses"][0]
            assert t["revision_id"] == "hbm-tightness@2026-07-19T00:00:00"
            assert t["freshness"] in {"fresh", "degraded", "stale"}

    asyncio.run(go())
