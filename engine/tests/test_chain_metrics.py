from evals.metrics import axis_mean, bootstrap_ci, chain_axes_valid, paired_valid

_FULL = {"mechanism": 1.0, "state_link": 1.0, "verdict": 1.0,
         "evidence": 1.0, "countercase": 1.0}


def _rec(cid, axes):
    return {"id": cid, "chain_axes": axes}


def test_chain_axes_valid_requires_exact_keyset():
    assert chain_axes_valid(_rec("a", dict(_FULL)))
    assert not chain_axes_valid(_rec("a", {"mechanism": 1.0}))          # 부분 dict 거부 (B8)
    assert not chain_axes_valid(_rec("a", {**_FULL, "extra": 1.0}))
    assert not chain_axes_valid(_rec("a", {**_FULL, "verdict": None}))


def test_paired_valid_union_denominator():
    base = [_rec("a", dict(_FULL)), _rec("b", dict(_FULL))]
    cand = [_rec("a", dict(_FULL)), _rec("c", dict(_FULL))]   # b 누락, c는 base에 없음
    pairs, ratio = paired_valid(base, cand)
    assert [p[0]["id"] for p in pairs] == ["a"]
    assert round(ratio, 3) == round(1 / 3, 3)                  # 분모 = {a,b,c}


def test_bootstrap_ci():
    lo, hi = bootstrap_ci([1.0] * 10, seed=42)
    assert lo > 0
    lo2, hi2 = bootstrap_ci([1.0, -1.0] * 5, seed=42)
    assert lo2 <= 0 <= hi2


def test_axis_mean_ignores_invalid():
    rows = [_rec("a", dict(_FULL)), _rec("b", {**_FULL, "mechanism": None})]
    assert axis_mean(rows, "mechanism") == 1.0
