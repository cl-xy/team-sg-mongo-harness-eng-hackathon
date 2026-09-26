"""Bounded, recurrence-oriented intake for NYC 311 records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from backend.extraction.types import SourceRecord


def source_record_from_311(row: dict[str, Any]) -> SourceRecord:
    """Copy source fields directly; no LLM derives location or complaint metadata."""
    metadata = dict(row.get("metadata", {}))
    structural_fields = {"id", "unique_key", "text", "occurred_at", "available_at", "created_date"}
    for field, value in row.items():
        if field not in structural_fields and field != "metadata":
            metadata[field] = value
    identifier = row.get("id", row.get("unique_key"))
    occurred_at = row.get("occurred_at", row.get("created_date"))
    if identifier is None or occurred_at is None:
        raise ValueError("311 rows require id/unique_key and occurred_at/created_date")
    text = row.get("text")
    if text is None:
        text = " — ".join(str(value) for value in (metadata.get("complaint_type"), metadata.get("descriptor")) if value)
    if not text:
        raise ValueError("311 rows require text or complaint_type/descriptor")
    for field in ("complaint_type", "descriptor", "agency", "borough", "incident_zip", "location", "latitude", "longitude"):
        if field in row:
            metadata[field] = row[field]
    return SourceRecord(
        id=str(identifier), text=str(text),
        occurred_at=datetime.fromisoformat(str(occurred_at)),
        available_at=datetime.fromisoformat(str(row.get("available_at", occurred_at))),
        metadata=metadata,
    )


def location_key(record: SourceRecord) -> str | None:
    location = record.metadata.get("location")
    if isinstance(location, dict) and isinstance(location.get("coordinates"), list):
        return "point:" + ",".join(str(value) for value in location["coordinates"])
    latitude, longitude = record.metadata.get("latitude"), record.metadata.get("longitude")
    if latitude is not None and longitude is not None:
        return f"point:{longitude},{latitude}"
    return None


def recurring_311_slice(
    records: Iterable[SourceRecord], *, maximum_records: int = 50, minimum_dates: int = 2,
    minimum_recurrences: int = 2,
) -> list[SourceRecord]:
    """Select one small complaint-type/location slice spanning multiple dates.

    Call this with a page already bounded by the Socrata query below; it never
    requests or assumes the full 311 corpus.
    """
    if maximum_records < minimum_dates or minimum_dates < 2 or minimum_recurrences < 2:
        raise ValueError("slice bounds require positive records and at least two dates/recurrences")
    grouped: dict[tuple[str, str], list[SourceRecord]] = defaultdict(list)
    for record in records:
        complaint_type = record.metadata.get("complaint_type")
        place = location_key(record)
        if isinstance(complaint_type, str) and place:
            grouped[(complaint_type, place)].append(record)
    eligible = [
        (key, items) for key, items in grouped.items()
        if len(items) >= minimum_recurrences and len({item.occurred_at.date() for item in items}) >= minimum_dates
    ]
    if not eligible:
        return []
    _, selected = max(eligible, key=lambda pair: (len(pair[1]), len({item.occurred_at.date() for item in pair[1]}), pair[0]))
    return sorted(selected, key=lambda item: (item.occurred_at, item.id))[:maximum_records]


def bounded_311_query(*, start: str, end: str, limit: int = 250) -> dict[str, str | int]:
    """Socrata parameters for a bounded chronological page, never a full export."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    return {
        "$select": "unique_key,complaint_type,descriptor,agency,borough,incident_zip,created_date,latitude,longitude,location",
        "$where": f"created_date between '{start}' and '{end}'",
        "$order": "created_date ASC, unique_key ASC",
        "$limit": limit,
    }
