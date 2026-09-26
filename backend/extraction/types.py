"""Temporary extraction-side contract types.

These fields mirror the shared application contract. Once the integrator's
``backend.contracts`` module lands, this module can become a direct re-export.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class SourceRecord:
    id: str
    text: str
    occurred_at: datetime
    available_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("source record IDs must be non-empty")
        if not self.text.strip():
            raise ValueError("source record text must be non-empty")
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))
        object.__setattr__(self, "available_at", utc(self.available_at))


@dataclass(frozen=True)
class MemoryNode:
    id: str
    kind: Literal["entity", "fact", "pattern", "summary"]
    text: str
    scope_key: str
    source_ids: list[str]
    first_seen_at: datetime
    last_seen_at: datetime
    assertion: Literal["observation", "hypothesis"] | None = None


@dataclass(frozen=True)
class MemoryEdge:
    id: str
    source_id: str
    target_id: str
    relation: str
    weight: float
    source_ids: list[str]


@dataclass(frozen=True)
class GraphBatch:
    batch_id: str
    session_id: str
    as_of: datetime
    nodes: list[MemoryNode]
    edges: list[MemoryEdge]
    source_ids: list[str]
    status: Literal["pending", "committed"] = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtractionFailure:
    """Replayable failed extraction; raw records remain the source of truth."""

    session_id: str
    source_ids: list[str]
    records: list[dict[str, Any]]
    attempts: int
    error: str
    failed_at: datetime
