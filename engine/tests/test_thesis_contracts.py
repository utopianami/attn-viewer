import pytest
from pydantic import ValidationError

from sector.contracts import EventType
from sector.entities import ENTITY_PATTERNS
from sector.metrics_registry import METRIC_REGISTRY
from sector.thesis_contracts import (Evidence, InputSnapshot, KeyMetric, RequiredInput,
                                     Selectors, Statement, ThesisRevision, observation_id)
from sector.thesis_seeds import SEED_THESES

_CANON = {c for c, _ in ENTITY_PATTERNS}


def make_rev(**kw):
    base = dict(
        id="hbm-tightness", revision_id="hbm-tightness@2026-07-21T00:00:00",
        claim="HBM 공급은 구조적으로 타이트하다", axis="A",
        selectors=Selectors(entities=["SK_HYNIX"], metrics=["memory_price_usd_per_gb"],
                            segments=["hbm"], event_types=["supply_signal"]),
        priority=1, assessment="strengthening",
        statements=[Statement(statement_id="s1", text="HBM 수요가 공급을 앞선다",
                              supporting=[
                                  Evidence(card_id="c-1", canonical_url="https://a.com/1",
                                           publisher_id="a.com", quote="q1"),
                                  Evidence(card_id="c-2", canonical_url="https://b.com/2",
                                           publisher_id="b.com", quote="q2")])],
        key_metrics=[KeyMetric(metric="memory_price_usd_per_gb", observation_id="x" * 16,
                               value=0.1, unit="USD/GB", ts="2026-07",
                               source="DRAM/NAND 소비자가 proxy")],
        required_inputs=[RequiredInput(metric="memory_price_usd_per_gb", max_age_days=45,
                                       meta_filter={"category": "DRAM"})],
        valid_from="2026-07-21T00:00:00",
        input_snapshot=InputSnapshot(card_ids=["c-1", "c-2"],
                                     metric_observation_ids=["x" * 16]),
        updated_at="2026-07-21T00:00:00")
    base.update(kw)
    return ThesisRevision(**base)


def test_revision_id_equality_enforced():
    with pytest.raises(ValidationError):
        make_rev(revision_id="hbm-tightness@2099-01-01T00:00:00")   # id@valid_from 불일치
    with pytest.raises(ValidationError):
        make_rev(valid_from="2026-07-21")                            # timestamp 형식 위반
    with pytest.raises(ValidationError):
        make_rev(axis="Z")                                           # Axis Literal 위반


def test_evidence_rejects_empty_and_bad_url():
    with pytest.raises(ValidationError):
        Evidence(card_id="c", canonical_url="https://a.com/1", publisher_id="a.com", quote="  ")
    with pytest.raises(ValidationError):
        Evidence(card_id="c", canonical_url="ftp://a.com/1", publisher_id="a.com", quote="q")
    with pytest.raises(ValidationError):
        Evidence(card_id="c", canonical_url="https://a.com/1", publisher_id="", quote="q")


def test_observation_id_deterministic():
    assert observation_id("m", "2026-07", {"a": 1}) == observation_id("m", "2026-07", {"a": 1})
    assert observation_id("m", "2026-07", {"a": 1}) != observation_id("m", "2026-07", {"a": 2})


def test_seeds_use_real_vocabulary():                # B6 — 가짜 세계 금지
    assert len(SEED_THESES) == 8
    import typing
    event_vals = set(typing.get_args(EventType))
    for s in SEED_THESES:
        sel = s["selectors"]
        assert set(sel["entities"]) <= _CANON, (s["id"], sel["entities"])
        assert set(sel["metrics"]) <= set(METRIC_REGISTRY), (s["id"], sel["metrics"])
        assert set(sel["event_types"]) <= event_vals, s["id"]
        assert set(sel["segments"]) <= {"hbm", "dram", "nand", "mixed"}, s["id"]  # r2-B6
        for ri in s["required_inputs"]:
            assert ri["metric"] in METRIC_REGISTRY, (s["id"], ri["metric"])
        make_rev(id=s["id"], revision_id=f"{s['id']}@2026-07-21T00:00:00",
                 claim=s["claim"], axis=s["axis"],
                 selectors=Selectors(**sel), priority=s["priority"],
                 required_inputs=[RequiredInput(**ri) for ri in s["required_inputs"]])


def test_list_fields_are_required():
    with pytest.raises(ValidationError):
        Statement(statement_id="s", text="t")                      # supporting 필수
    with pytest.raises(ValidationError):
        Selectors(entities=["SK_HYNIX"])                            # 나머지 3필드 필수
    with pytest.raises(ValidationError):
        InputSnapshot(card_ids=["c"])                               # metric_observation_ids 필수
    for missing in ("statements", "key_metrics", "required_inputs"):
        base = dict(
            id="hbm-tightness", revision_id="hbm-tightness@2026-07-21T00:00:00",
            claim="HBM 공급은 구조적으로 타이트하다", axis="A",
            selectors=Selectors(entities=["SK_HYNIX"], metrics=["memory_price_usd_per_gb"],
                                segments=["hbm"], event_types=["supply_signal"]),
            priority=1, assessment="strengthening",
            statements=[Statement(statement_id="s1", text="HBM 수요가 공급을 앞선다",
                                  supporting=[
                                      Evidence(card_id="c-1", canonical_url="https://a.com/1",
                                               publisher_id="a.com", quote="q1")])],
            key_metrics=[KeyMetric(metric="memory_price_usd_per_gb", observation_id="x" * 16,
                                   value=0.1, unit="USD/GB", ts="2026-07",
                                   source="DRAM/NAND 소비자가 proxy")],
            required_inputs=[RequiredInput(metric="memory_price_usd_per_gb", max_age_days=45,
                                           meta_filter={"category": "DRAM"})],
            valid_from="2026-07-21T00:00:00",
            input_snapshot=InputSnapshot(card_ids=["c-1"],
                                         metric_observation_ids=["x" * 16]),
            updated_at="2026-07-21T00:00:00")
        del base[missing]
        with pytest.raises(ValidationError):
            ThesisRevision(**base)
