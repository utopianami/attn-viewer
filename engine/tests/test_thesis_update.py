import asyncio
import datetime as dt
import json

from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore
from sector.thesis_store import ThesisStore
from sector.thesis_update import main, update_all, update_thesis

NOW = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)


def _seed():
    return {"id": "hbm-tightness", "claim": "HBM 타이트", "axis": "A", "priority": 1,
            "selectors": {"entities": ["SK_HYNIX"], "metrics": ["memory_price_usd_per_gb"],
                          "segments": ["hbm"], "event_types": ["supply_signal"]},
            "required_inputs": [{"metric": "memory_price_usd_per_gb", "max_age_days": 3650,
                                 "min_count": 1, "meta_filter": {"category": "DRAM"}}]}


def _env(tmp_path):
    store = SectorStore(tmp_path / "s")
    store.append_observations([MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1, unit="USD/GB",
        meta={"category": "DRAM"})])
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
    assert rev.key_metrics[0].value == 0.1
    assert set(rev.input_snapshot.card_ids) == {"c1", "c2"}  # 제공 전체 (정확 집합)
    from sector.thesis_contracts import observation_id as _oid
    assert set(rev.input_snapshot.metric_observation_ids) == {
        _oid("memory_price_usd_per_gb", "2026-07", {"category": "DRAM"})}  # r2-B8


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
