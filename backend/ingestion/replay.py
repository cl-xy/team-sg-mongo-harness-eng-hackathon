"""Deterministic, availability-aware replay of source records."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("record timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _field(record: Any, name: str) -> Any:
    return getattr(record, name) if hasattr(record, name) else record[name]


def replay_records(
    records: Iterable[Any], *, as_of: datetime, limit: int | None = None
) -> list[Any]:
    """Return unique records visible at ``as_of``, in occurrence order.

    A source ID is the replay idempotency key. If duplicate records disagree,
    keeping the first supplied copy makes fixture replay deterministic.
    """
    replay_time = _as_utc(as_of)
    unique: dict[str, Any] = {}
    for record in records:
        record_id = str(_field(record, "id"))
        if record_id not in unique:
            unique[record_id] = record

    visible = [
        record
        for record in unique.values()
        if _as_utc(_field(record, "available_at")) <= replay_time
    ]
    visible.sort(key=lambda record: (_as_utc(_field(record, "occurred_at")), str(_field(record, "id"))))
    return visible if limit is None else visible[:limit]
