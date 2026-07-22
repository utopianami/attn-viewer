import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import CaseEpisode, _parse_ts
from casemem.store import CaseStore
from casemem.seeds import load_seeds


def test_seed_files_validate_as_episodes():
    seed_dir = Path(__file__).resolve().parents[1] / "casemem" / "seeds"
    files = sorted(seed_dir.glob("*.json"))
    assert len(files) >= 6
    for f in files:
        ep = CaseEpisode.model_validate_json(f.read_text(encoding="utf-8"))
        assert ep.sector in ("memory", "finance", "tech")
        assert len(ep.phases) >= 3
        # 국면 order는 0..n-1 오름차순
        assert [p.order for p in ep.phases] == sorted(p.order for p in ep.phases)
        # 룩어헤드 불변식: 각 국면 evidence knowable_at 파싱 가능
        for p in ep.phases:
            for e in p.evidence:
                assert _parse_ts(e.knowable_at) is not None


def test_load_seeds_populates_store(tmp_path):
    s = CaseStore(tmp_path)
    n = load_seeds(s)
    assert n >= 6
    ids = {e.id for e in s.read_episodes(sector="memory")}
    assert "mem-2016-2019-supercycle-crash" in ids and "mem-2023-2025-hbm-upcycle" in ids
    assert load_seeds(s) == 0        # 재적재 idempotent(dedup)
