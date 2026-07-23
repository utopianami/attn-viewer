# engine/tests/test_p23_integration.py — B3/r2-2 게이트 + on-arm 통합 (하네스 재사용)
from tests.p23_harness import run_pipeline


def test_non_memory_full_profile_no_thesis_no_chain(tmp_path):
    # full 프로필(sector_rag_enabled=True)이지만 is_sector_question=False —
    # 게이트가 프로필이 아니라 memory_sector_active임을 증명 (r1-B3)
    out = run_pipeline("코스피 은행 배당주 지금 어때?", tmp_path=tmp_path,
                       overrides_extra={"disable_p23": False})
    names = [l["name"] for l in out["layers"]]
    assert "thesis" not in names and "chain" not in names
    assert not any("chain" in d for d in out["final"]["meta"]["degraded"])


def test_entity_only_question_blocked_by_memory_gate(tmp_path):
    # r2-2 — NVIDIA 엔티티로 is_sector_question=True(검색 게이트 통과)여도
    # is_memory_question=False → thesis·chain 미가동
    out = run_pipeline("엔비디아 CUDA 소프트웨어 매출 전망 어때?", tmp_path=tmp_path,
                       overrides_extra={"disable_p23": False})
    names = [l["name"] for l in out["layers"]]
    assert "sector_rag" in names                  # 검색 경로는 기존대로
    assert "thesis" not in names and "chain" not in names


def test_on_arm_sector_question_emits_thesis_and_chain(tmp_path):
    # r2-1e — 전체 스위트 `DISABLE_P23=true` 게이트에서도 green: run override가
    # env 설정에 우선(B2 seam 실증) — 명시적 disable_p23=False 전달
    out = run_pipeline("SK하이닉스 HBM 현물가 흐름 어때?", tmp_path=tmp_path,
                       overrides_extra={"disable_p23": False})
    names = [l["name"] for l in out["layers"]]
    assert "chain" in names
    chain_l = [l for l in out["layers"] if l["name"] == "chain"][-1]
    assert chain_l["round"] == chain_l["data"]["meta"]["round"]   # r2 권고 1
    assert "typed_fact_snapshot" in chain_l["data"]               # r2-7 방출면
    verify = [l for l in out["layers"] if l["name"] == "verify"][-1]
    assert "chain_verdicts" in verify["data"]


def test_off_arm_override_suppresses_everything(tmp_path):
    out = run_pipeline("SK하이닉스 HBM 현물가 흐름 어때?", tmp_path=tmp_path,
                       overrides_extra={"disable_p23": True})
    names = [l["name"] for l in out["layers"]]
    assert "thesis" not in names and "chain" not in names   # B2 — run override arm
