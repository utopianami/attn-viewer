import asyncio
import copy
import datetime as dt
import json

from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore
from sector.thesis_seeds import SEED_THESES
from sector.thesis_store import ThesisStore
from sector.thesis_update import main, update_all, update_thesis

NOW = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)

# 실제 프로덕션 hbm-tightness 시드를 그대로 쓴다(2부 T9 블로커 1/2 — codex 재검토
# 후 fixture를 게이트에 맞춰 보정하라는 판정. thesis_seeds.py가 바뀌면 이 테스트도
# 같이 정확해진다 — 손으로 복제한 축약판이 real seed와 drift하는 일이 없도록).
_HBM_SEED = next(s for s in SEED_THESES if s["id"] == "hbm-tightness")


def _seed():
    return copy.deepcopy(_HBM_SEED)


def _env(tmp_path):
    store = SectorStore(tmp_path / "s")
    # hbm-tightness의 required_inputs 5개(HBM item·DRAM item·memory_capex 3사)를
    # 전부 충족시키는 관측 — Blocker 1(게이트는 fresh만 통과) 하에서 LLM까지
    # 도달하려면 전부 있어야 한다.
    store.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=16.0,
                          unit="USD/GB", meta={"item": "HBM|HBM $/GB", "category": "HBM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB",
                          meta={"item": "DRAM|DRAM cheapest (Keepa)", "category": "DRAM"}),
        MetricObservation(metric="memory_capex", ts="2026-07", value=18000.0,
                          unit="b_local", meta={"item": "005930.KS", "token": "005930.KS"}),
        MetricObservation(metric="memory_capex", ts="2026-07", value=7800.0,
                          unit="b_local", meta={"item": "000660.KS", "token": "000660.KS"}),
        MetricObservation(metric="memory_capex", ts="2026-07", value=8.0,
                          unit="b_local", meta={"item": "MU", "token": "MU"}),
    ])
    store.append_cards([
        SectorCard(id="c1", ts="2026-07-20T00:00:00", axis="A", direction="pos",
                   magnitude=2, source_grade="A", title="t1", interpreted_signal="",
                   raw_quote="HBM 수요가 공급을 앞선다는 분석 기사", url="https://a.com/1",
                   entities=["SK_HYNIX"]),
        SectorCard(id="c2", ts="2026-07-20T00:00:00", axis="A", direction="pos",
                   magnitude=2, source_grade="A", title="t2", interpreted_signal="",
                   raw_quote="고객 인증 확대 보도라는 별개 근거", url="https://b.com/2",
                   entities=["SK_HYNIX"])])
    return store, ThesisStore(tmp_path)


class _Updater:
    model = "fake-sonnet"
    def __init__(self, proposal): self.proposal, self.calls = proposal, 0
    async def run(self, prompt, instructions="", response_format=None, **kw):
        self.calls += 1
        return response_format.model_validate(self.proposal)


class _Verifier:
    model = "fake-gpt"
    def __init__(self): self.calls = 0
    async def run(self, prompt, instructions="", response_format=None, **kw):
        self.calls += 1
        import re
        pairs = re.findall(r'"statement_id":\s*"(s\d+)".*?"card_id":\s*"(c\d+)"', prompt, re.S) or []
        # 프롬프트에서 (sid, card) 전부에 supported=True — 구현이 넣는 형식에 맞춰 조정 가능
        sids = set(re.findall(r'"statement_id":\s*"(s\d+)"', prompt))
        cids = re.findall(r'"card_id":\s*"(c\d+)"', prompt)
        rows = [{"statement_id": s, "card_id": c, "supported": True, "why": ""}
                for s in sids for c in set(cids)]
        rels = [{"statement_id": s, "relevant": True, "direction": "supports"} for s in sids]
        return response_format.model_validate({"rows": rows, "relations": rels})


_GOOD = {"statements": [{"text": "HBM 수요가 공급을 앞선다",
                         "evidence": [{"card_id": "c1", "quote": "HBM 수요가 공급을 앞선다"},
                                      {"card_id": "c2", "quote": "고객 인증 확대 보도"}]}],
         "key_metric_names": ["memory_price_usd_per_gb"]}


def test_full_pipe_creates_revision_with_verifier_called(tmp_path):
    store, tstore = _env(tmp_path)
    up, ver = _Updater(_GOOD), _Verifier()
    rev = asyncio.run(update_thesis(_seed(), store, tstore, up, ver, now=NOW))
    assert rev is not None and ver.calls >= 1               # B11 — verifier 실호출
    assert rev.assessment == "strengthening"                 # 방향 코드 집계
    # key_metric_names=["memory_price_usd_per_gb"] — HBM·DRAM 둘 다 이 이름을 쓰는
    # required_inputs라 둘 다 KeyMetric으로 나온다(2부 T9 블로커 2c — first-wins 아님).
    assert [round(km.value, 4) for km in rev.key_metrics] == [16.0, 0.1]
    assert [km.meta.get("item") for km in rev.key_metrics] == [
        "HBM|HBM $/GB", "DRAM|DRAM cheapest (Keepa)"]
    assert set(rev.input_snapshot.card_ids) == {"c1", "c2"}  # 제공 전체 (정확 집합)
    from sector.thesis_contracts import observation_id as _oid
    # InputSnapshot은 required_inputs 5개(HBM·DRAM·memory_capex 3사) 전체를 기록한다
    # (채택분이 아니라 조립 시점에 제공한 전체 — r2-B8, 2부 T9 블로커 2b).
    assert set(rev.input_snapshot.metric_observation_ids) == {
        _oid("memory_price_usd_per_gb", "2026-07", {"item": "HBM|HBM $/GB", "category": "HBM"}),
        _oid("memory_price_usd_per_gb", "2026-07",
             {"item": "DRAM|DRAM cheapest (Keepa)", "category": "DRAM"}),
        _oid("memory_capex", "2026-07", {"item": "005930.KS", "token": "005930.KS"}),
        _oid("memory_capex", "2026-07", {"item": "000660.KS", "token": "000660.KS"}),
        _oid("memory_capex", "2026-07", {"item": "MU", "token": "MU"}),
    }


def test_required_gate_blocks_before_llm(tmp_path):          # B11 — sentinel
    store, tstore = _env(tmp_path)
    seed = _seed(); seed["required_inputs"][0]["metric"] = "kr_semi_export"  # 관측 없음
    class _Boom:
        model = "boom"
        async def run(self, *a, **k): raise AssertionError("LLM called before gate")
    rev = asyncio.run(update_thesis(seed, store, tstore, _Boom(), _Boom(), now=NOW))
    assert rev is None


def test_update_all_wires_roles_and_isolates(tmp_path):      # B11 — 배선·격리
    store, _ = _env(tmp_path)
    created = []
    def factory(name):
        created.append(name)
        return _Updater(_GOOD) if name == "thesis_updater" else _Verifier()
    res = asyncio.run(update_all(store, tstore=ThesisStore(tmp_path),
                                 only=["hbm-tightness"], role_factory=factory))
    assert set(created) == {"thesis_updater", "thesis_verifier"}
    assert res["hbm-tightness"] == "updated"


def test_cli_main_only_flag_and_exit_code(tmp_path, monkeypatch, capsys):
    """subprocess가 아니라 main() 직접 호출로 검증 — 실 LLM 호출 없이 update_all을
    스텁해 argparse --only 배선·JSON 출력·exit code(에러 있으면 1)만 확인한다."""
    import sector.thesis_update as mod

    monkeypatch.setattr(mod, "_get_store", lambda: object())

    captured_only = {}

    async def _fake_update_all(store, tstore=None, only=None, role_factory=None):
        captured_only["only"] = only
        return {"hbm-tightness": "updated"}

    monkeypatch.setattr(mod, "update_all", _fake_update_all)
    rc = main(["--only", "hbm-tightness"])
    out = json.loads(capsys.readouterr().out)
    assert captured_only["only"] == ["hbm-tightness"]
    assert out == {"hbm-tightness": "updated"} and rc == 0

    async def _fake_update_all_error(store, tstore=None, only=None, role_factory=None):
        return {"hbm-tightness": "error: boom"}

    monkeypatch.setattr(mod, "update_all", _fake_update_all_error)
    rc2 = main([])
    assert rc2 == 1


def test_no_toctou_single_read_and_race_append_ignored(tmp_path):  # 2부 T9 블로커 4
    """metric당 store.read_metric 정확히 1회 + 조립 이후 append된 관측은 무시된다.

    조립(2단계) 후 LLM 호출(3단계) 도중 더 최신 관측이 store에 들어와도, 최종
    key_metrics는 조립 시점 스냅샷 그대로여야 한다(재조회 없음 — TOCTOU 방지).
    """
    store, tstore = _env(tmp_path)

    call_counts: dict[str, int] = {}
    orig_read_metric = store.read_metric

    def _counting_read_metric(metric, **kw):
        call_counts[metric] = call_counts.get(metric, 0) + 1
        return orig_read_metric(metric, **kw)

    store.read_metric = _counting_read_metric

    class _RaceUpdater(_Updater):
        async def run(self, prompt, instructions="", response_format=None, **kw):
            # LLM "호출 중" 레이스를 흉내낸다 — 조립 이후 더 최신(다른 ts) 관측 도착.
            store.append_observations([MetricObservation(
                metric="memory_price_usd_per_gb", ts="2026-07-22", value=999.0,
                unit="USD/GB", meta={"item": "HBM|HBM $/GB", "category": "HBM"})])
            return await super().run(prompt, instructions, response_format, **kw)

    up, ver = _RaceUpdater(_GOOD), _Verifier()
    rev = asyncio.run(update_thesis(_seed(), store, tstore, up, ver, now=NOW))

    assert rev is not None
    hbm_km = next(km for km in rev.key_metrics if km.meta.get("item") == "HBM|HBM $/GB")
    assert hbm_km.value == 16.0 and hbm_km.ts == "2026-07"      # 레이스로 들어온 999.0 아님
    for metric, n in call_counts.items():
        assert n == 1, (metric, n)                              # metric당 정확히 1회


_DUP_EVIDENCE_PROPOSAL = {
    "statements": [{"text": "HBM 수요가 공급을 앞선다",
                    "evidence": [{"card_id": "c1", "quote": "HBM 수요가 공급을 앞선다"},
                                 {"card_id": "c1", "quote": "HBM 수요가 공급을 앞선다"},
                                 {"card_id": "c2", "quote": "고객 인증 확대 보도"}]}],
    "key_metric_names": ["memory_price_usd_per_gb"]}


def test_duplicate_card_evidence_deduped_before_verify(tmp_path):  # 2부 T9 블로커 6a
    """LLM이 같은 statement 안에서 같은 card_id를 두 번 인용하면 첫 건만 남긴다.

    dedup이 없으면 verify_statements의 (statement_id, card_id) 중복 입력 가드
    (블로커 6b)가 즉시 VerificationFailed를 던져 revision 전체가 skip된다 — 이
    테스트는 dedup 덕분에 파이프가 정상 진행됨을 통해 6a를 간접 검증하고,
    최종 supporting에 card_id 중복이 없음을 직접 검증한다.
    """
    store, tstore = _env(tmp_path)
    up, ver = _Updater(_DUP_EVIDENCE_PROPOSAL), _Verifier()
    rev = asyncio.run(update_thesis(_seed(), store, tstore, up, ver, now=NOW))
    assert rev is not None                                       # dedup 없었으면 None(6b fail-closed)
    assert len(rev.statements) == 1
    supporting_card_ids = [ev.card_id for ev in rev.statements[0].supporting]
    assert sorted(supporting_card_ids) == ["c1", "c2"]            # c1 중복 인용 → 1건으로 축소
