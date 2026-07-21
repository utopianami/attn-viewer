"""Case-Memory 저장소 — storage/rag/case_memory/ 아래 append-only JSONL.
SectorStore 패턴 복제(engine/sector/store.py)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from casemem.contracts import CaseEpisode

_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


class CaseStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        (self.root / "cases").mkdir(parents=True, exist_ok=True)
        self._index = self.root / "index.jsonl"

    def _known_ids(self) -> set[str]:
        if not self._index.exists():
            return set()
        out: set[str] = set()
        for line in self._index.read_text(encoding="utf-8").splitlines():
            try:
                out.add(json.loads(line)["id"])
            except Exception:  # noqa: BLE001 — 손상 줄 스킵
                continue
        return out

    def append_episodes(self, eps: list[CaseEpisode]) -> int:
        known = self._known_ids()
        added = 0
        with self._index.open("a", encoding="utf-8") as f:
            for ep in eps:
                if ep.id in known:
                    continue
                known.add(ep.id)
                f.write(ep.model_dump_json() + "\n")
                sdir = self.root / "cases" / _SAFE.sub("_", ep.sector)
                sdir.mkdir(parents=True, exist_ok=True)
                (sdir / f"{_SAFE.sub('_', ep.id)}.json").write_text(
                    ep.model_dump_json(indent=1), encoding="utf-8")
                added += 1
        return added

    def read_episodes(self, *, sector: str | None = None) -> list[CaseEpisode]:
        if not self._index.exists():
            return []
        out: list[CaseEpisode] = []
        for line in self._index.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ep = CaseEpisode.model_validate_json(line)
            except Exception:  # noqa: BLE001 — never-raise
                continue
            if sector is not None and ep.sector != sector:
                continue
            out.append(ep)
        return out
