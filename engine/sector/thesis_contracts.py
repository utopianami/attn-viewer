"""테제(Thesis) 계약 — 섹터 카드·지표를 근거로 한 구조적 주장의 typed 표현.

`sector.contracts`의 Axis·EventType·memory_segment 값 공간을 재사용한다
(가짜 세계 금지 — 2부 T1 계획, r2-B6/B8).
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sector.contracts import Axis

_URL_RE = re.compile(r"^https?://")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

# SectorCard.memory_segment 값 공간 재사용 (contracts.py에 별도 export된 alias가
# 없어 값 목록만 미러링 — 원본이 바뀌면 이 Literal도 같이 바꿔야 함, r2-B6).
MemorySegment = Literal["hbm", "dram", "nand", "mixed"]


def observation_id(metric: str, ts: str, meta: dict) -> str:
    """metric·ts·meta로부터 결정적 관측 ID를 만든다 (16자 hex)."""
    payload = f"{metric}|{ts}|{json.dumps(meta, sort_keys=True, ensure_ascii=False)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class Evidence(BaseModel):
    card_id: str
    canonical_url: str = Field(min_length=1)
    publisher_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)

    @field_validator("quote", "publisher_id", "canonical_url")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("must not be blank")
        return s

    @field_validator("canonical_url")
    @classmethod
    def _url_scheme(cls, v: str) -> str:
        if not _URL_RE.match(v):
            raise ValueError("canonical_url must start with http:// or https://")
        return v


class Statement(BaseModel):
    statement_id: str
    text: str
    supporting: list[Evidence] = Field(default_factory=list)
    contradicting: list[Evidence] = Field(default_factory=list)


class KeyMetric(BaseModel):
    metric: str
    observation_id: str
    value: float
    unit: str
    ts: str
    meta: dict = Field(default_factory=dict)
    source: str


class RequiredInput(BaseModel):
    metric: str
    max_age_days: int
    min_count: int = 1
    meta_filter: dict = Field(default_factory=dict)


class Selectors(BaseModel):
    entities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    segments: list[MemorySegment] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)


class InputSnapshot(BaseModel):
    """LLM prompt에 실제 제공된 전체 ID 스냅샷 — 채택(citation)분이 아니라 노출분 전체."""
    card_ids: list[str] = Field(default_factory=list)
    metric_observation_ids: list[str] = Field(default_factory=list)


class ThesisRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    revision_id: str
    claim: str
    axis: Axis
    selectors: Selectors
    priority: int
    assessment: Literal["strengthening", "weakening", "mixed"]
    statements: list[Statement] = Field(default_factory=list)
    key_metrics: list[KeyMetric] = Field(default_factory=list)
    required_inputs: list[RequiredInput] = Field(default_factory=list)
    valid_from: str
    input_snapshot: InputSnapshot
    updated_at: str

    @field_validator("valid_from")
    @classmethod
    def _valid_from_format(cls, v: str) -> str:
        if not _TS_RE.match(v):
            raise ValueError("valid_from must be YYYY-MM-DDTHH:MM:SS UTC")
        return v

    @model_validator(mode="after")
    def _revision_id_matches(self) -> "ThesisRevision":
        expected = f"{self.id}@{self.valid_from}"
        if self.revision_id != expected:
            raise ValueError(f"revision_id must equal {expected!r}, got {self.revision_id!r}")
        return self
