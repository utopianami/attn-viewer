"""raw 코퍼스 store + 원자 상태 (2026-07-21 firehose)."""
import json
import multiprocessing
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import CollectorResult, RawNewsDoc  # noqa: E402
from sector.store import SectorStore  # noqa: E402


def test_rawnewsdoc_defaults():
    d = RawNewsDoc(id="172279", title="t", created_at="2026-07-20T10:00:00+09:00")
    assert d.content == "" and d.tag_names == [] and d.ingested_at == ""


def test_collectorresult_has_stats():
    r = CollectorResult(name="saveticker", kind="news")
    assert r.stats == {}
    r2 = CollectorResult(name="x", kind="news", stats={"scan_hwm": 10})
    assert r2.stats["scan_hwm"] == 10


# ── Task 2: set_states ────────────────────────────────────────────────────────
def test_set_states_atomic_multi(tmp_path):
    s = SectorStore(tmp_path)
    s.set_states({"a": 1, "b": {"x": 2}})
    s.set_states({"a": 3})                      # 부분 갱신은 병합
    data = json.loads((tmp_path / "state.json").read_text())
    assert data == {"a": 3, "b": {"x": 2}}
    assert s.get_state("b") == {"x": 2}


def test_set_state_still_works(tmp_path):
    s = SectorStore(tmp_path)
    s.set_state("k", 5)
    assert s.get_state("k") == 5


# ── Task 3: append_raw_news ───────────────────────────────────────────────────
def _doc(i, ts="2026-07-20T10:00:00+09:00", title="t"):
    return RawNewsDoc(id=str(i), title=title, created_at=ts, content="c")


def _append_same_raw(root: str, start, output) -> None:
    original_read_text = Path.read_text

    def delayed_read_text(path, *args, **kwargs):
        value = original_read_text(path, *args, **kwargs)
        if path.name == "2026-07.jsonl":
            time.sleep(0.1)
        return value

    Path.read_text = delayed_read_text
    start.wait()
    output.put(SectorStore(root).append_raw_news([_doc("shared")]))


def test_append_raw_dedup_and_partition(tmp_path):
    s = SectorStore(tmp_path)
    n1 = s.append_raw_news([_doc(1), _doc(2), _doc(1)])   # in-batch 중복 1건
    n2 = s.append_raw_news([_doc(2), _doc(3)])            # 파티션 재실행 중복
    assert (n1, n2) == (2, 1)
    p = tmp_path / "news_raw" / "2026-07.jsonl"
    ids = [json.loads(l)["id"] for l in p.read_text().splitlines()]
    assert ids == ["1", "2", "3"]


def test_duplicate_raw_append_is_serialized_across_processes(tmp_path):
    store = SectorStore(tmp_path)
    store.append_raw_news([_doc("seed")])
    context = multiprocessing.get_context("fork")
    start = context.Event()
    output = context.Queue()
    processes = [
        context.Process(target=_append_same_raw, args=(str(tmp_path), start, output))
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0

    assert sorted(output.get(timeout=1) for _ in processes) == [0, 0, 0, 1]
    ids = [json.loads(line)["id"] for line in store._raw_path("2026-07").read_text().splitlines()]
    assert ids.count("shared") == 1


def test_append_raw_stamps_ingested_at(tmp_path):
    s = SectorStore(tmp_path)
    s.append_raw_news([_doc(9)])
    p = tmp_path / "news_raw" / "2026-07.jsonl"
    row = json.loads(p.read_text().splitlines()[0])
    assert row["ingested_at"] != ""


def test_append_raw_unknown_partition(tmp_path):
    s = SectorStore(tmp_path)
    s.append_raw_news([RawNewsDoc(id="5", title="t", created_at="")])
    assert (tmp_path / "news_raw" / "unknown.jsonl").exists()


# ── Task 4: write_status stats ────────────────────────────────────────────────
def test_write_status_includes_stats(tmp_path):
    s = SectorStore(tmp_path)
    r = CollectorResult(name="saveticker", kind="news",
                        status="degraded", stats={"scan_hwm": 172300, "raw_added": 40})
    s.write_status([r])
    st = s.read_status()["saveticker"]
    assert st["stats"]["scan_hwm"] == 172300 and st["stats"]["raw_added"] == 40
