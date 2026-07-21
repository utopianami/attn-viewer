import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import CaseEpisode, Phase
from casemem.store import CaseStore


def _ep(eid, sector="memory"):
    return CaseEpisode(id=eid, sector=sector, title=eid,
                       event_time="2018-01-01", knowable_at="2018-01-15",
                       phases=[Phase(order=0, label="p0",
                                     period_start="2018-01-01", knowable_at="2018-02-01")])


def test_append_writes_original_and_index(tmp_path):
    s = CaseStore(tmp_path)
    added = s.append_episodes([_ep("mem-a"), _ep("mem-b")])
    assert added == 2
    assert (tmp_path / "cases" / "memory" / "mem-a.json").exists()
    assert (tmp_path / "index.jsonl").exists()
    got = s.read_episodes()
    assert {e.id for e in got} == {"mem-a", "mem-b"}


def test_append_dedups_by_id(tmp_path):
    s = CaseStore(tmp_path)
    s.append_episodes([_ep("mem-a")])
    added = s.append_episodes([_ep("mem-a")])      # 같은 id 재적재
    assert added == 0
    assert len(s.read_episodes()) == 1


def test_read_filters_by_sector_and_survives_corrupt_line(tmp_path):
    s = CaseStore(tmp_path)
    s.append_episodes([_ep("mem-a", "memory"), _ep("fx-a", "fx")])
    with (tmp_path / "index.jsonl").open("a", encoding="utf-8") as f:
        f.write("{corrupt json\n")
    got = s.read_episodes(sector="memory")
    assert [e.id for e in got] == ["mem-a"]        # fx 제외, 손상 라인 무시
