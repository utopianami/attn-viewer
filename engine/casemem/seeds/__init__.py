"""손으로 쓴 시드 CaseEpisode 로더 — 당대성 유지(설계 §4.2)."""
from __future__ import annotations

from pathlib import Path

from casemem.contracts import CaseEpisode
from casemem.store import CaseStore


def load_seeds(store: CaseStore, seed_dir: Path | None = None) -> int:
    seed_dir = seed_dir or Path(__file__).resolve().parent
    eps: list[CaseEpisode] = []
    for f in sorted(seed_dir.glob("*.json")):
        try:
            eps.append(CaseEpisode.model_validate_json(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 — 검증 실패 시드 스킵(never-raise)
            continue
    return store.append_episodes(eps)
