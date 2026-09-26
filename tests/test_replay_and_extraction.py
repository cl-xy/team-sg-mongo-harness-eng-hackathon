import json
from datetime import datetime
from pathlib import Path

import pytest

from backend.extraction import JsonlFailureStore, SourceRecord, extract_concepts, source_block_key
from backend.extraction.service import ExtractionError
from backend.ingestion import bounded_311_query, recurring_311_slice, replay_records, source_record_from_311


def record(record_id: str, occurred: str, available: str | None = None) -> SourceRecord:
    return SourceRecord(record_id, "noise report", datetime.fromisoformat(occurred), datetime.fromisoformat(available or occurred), {"location": "A"})


def test_replay_deduplicates_orders_and_honours_availability() -> None:
    early = record("early", "2026-09-01T01:00:00+00:00")
    later = record("later", "2026-09-02T01:00:00+00:00", "2026-09-04T01:00:00+00:00")
    replayed = replay_records([later, early, early], as_of=datetime.fromisoformat("2026-09-03T01:00:00+00:00"))
    assert [item.id for item in replayed] == ["early"]


def test_extraction_validates_provenance_and_retries_once() -> None:
    records = [record("a", "2026-09-01T01:00:00+00:00"), record("b", "2026-09-02T01:00:00+00:00")]
    calls = 0

    def extractor(_: list[dict]) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"nodes": [], "edges": [{"id": "bad"}]}
        return {
            "nodes": [
                {"id": "fact-a", "kind": "fact", "text": "noise at A", "scope_key": "source:a", "source_ids": ["a"], "assertion": "observation"},
                {"id": "place-a", "kind": "entity", "text": "A", "scope_key": "A", "source_ids": ["a", "b"]},
            ],
            "edges": [{"id": "at-a", "source_id": "fact-a", "target_id": "place-a", "relation": "located_at", "weight": 1, "source_ids": ["a"]}],
        }

    batch = extract_concepts(records, "session-1", extractor=extractor)
    assert calls == 2
    assert batch.status == "pending"
    assert batch.source_ids == ["a", "b"]


def test_extraction_rejects_unknown_provenance() -> None:
    with pytest.raises(ExtractionError, match="unknown sources"):
        extract_concepts([record("a", "2026-09-01T01:00:00+00:00")], "session", extractor=lambda _: {"nodes": [{"id": "f", "kind": "fact", "text": "x", "scope_key": "source:a", "source_ids": ["missing"], "assertion": "observation"}], "edges": []})


def test_facts_cannot_merge_source_blocks_and_must_declare_assertion() -> None:
    records = [record("a", "2026-09-01T01:00:00+00:00"), record("b", "2026-09-02T01:00:00+00:00")]
    with pytest.raises(ExtractionError, match="exactly one source block"):
        extract_concepts(records, "session", extractor=lambda _: {"nodes": [{"id": "merged", "kind": "fact", "text": "same wording", "scope_key": "source:a", "source_ids": ["a", "b"], "assertion": "observation"}], "edges": []})
    with pytest.raises(ExtractionError, match="label its assertion"):
        extract_concepts([records[0]], "session", extractor=lambda _: {"nodes": [{"id": "f", "kind": "fact", "text": "unlicensed bar", "scope_key": source_block_key(records[0]), "source_ids": ["a"]}], "edges": []})
    with pytest.raises(ExtractionError, match="must be a hypothesis"):
        extract_concepts([records[0]], "session", extractor=lambda _: {"nodes": [{"id": "f", "kind": "fact", "text": "an unlicensed bar caused the noise", "scope_key": source_block_key(records[0]), "source_ids": ["a"], "assertion": "observation"}], "edges": []})


def test_pattern_cannot_cross_location_boundaries() -> None:
    first = SourceRecord("a", "noise", datetime.fromisoformat("2026-09-01T01:00:00+00:00"), datetime.fromisoformat("2026-09-01T01:00:00+00:00"), {"location": {"coordinates": [-73.9, 40.7]}})
    second = SourceRecord("b", "noise", datetime.fromisoformat("2026-09-02T01:00:00+00:00"), datetime.fromisoformat("2026-09-02T01:00:00+00:00"), {"location": {"coordinates": [-73.8, 40.7]}})
    with pytest.raises(ExtractionError, match="one source-derived location"):
        extract_concepts([first, second], "session", extractor=lambda _: {"nodes": [{"id": "p", "kind": "pattern", "text": "repeated noise", "scope_key": "location:point:-73.9,40.7", "source_ids": ["a", "b"], "assertion": "observation"}], "edges": []})


def test_failure_is_retained_and_error_event_is_emitted(tmp_path) -> None:
    events: list[dict] = []
    failures = JsonlFailureStore(tmp_path / "failed-extractions.jsonl")
    with pytest.raises(ExtractionError):
        extract_concepts([record("a", "2026-09-01T01:00:00+00:00")], "session", extractor=lambda _: "not json", failure_sink=failures, emit_error=events.append)
    assert failures.pending()[0]["source_ids"] == ["a"]
    assert events[0]["type"] == "error"


def test_bounded_slice_uses_one_recurring_type_location_across_dates() -> None:
    recurring = [
        SourceRecord(str(day), "noise", datetime.fromisoformat(f"2026-09-0{day}T01:00:00+00:00"), datetime.fromisoformat(f"2026-09-0{day}T01:01:00+00:00"), {"complaint_type": "Noise", "location": {"coordinates": [-73.9, 40.7]}})
        for day in range(1, 4)
    ]
    other = record("other", "2026-09-01T01:00:00+00:00")
    selected = recurring_311_slice([other, *recurring], maximum_records=2)
    assert [item.id for item in selected] == ["1", "2"]
    query = bounded_311_query(start="2026-09-01T00:00:00", end="2026-09-04T00:00:00", limit=250)
    assert query["$limit"] == 250


def test_socrata_row_becomes_source_metadata_without_model_inference() -> None:
    source = source_record_from_311({
        "unique_key": "311-1", "complaint_type": "Noise", "descriptor": "Loud music",
        "created_date": "2026-09-01T01:00:00+00:00", "location": {"coordinates": [-73.9, 40.7]},
        "agency": "NYPD",
    })
    assert source.id == "311-1"
    assert source.text == "Noise — Loud music"
    assert source.metadata["location"] == {"coordinates": [-73.9, 40.7]}


def test_small_fixture_contains_a_bounded_month_long_recurring_slice() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "nyc_311_small.json"
    rows = json.loads(fixture.read_text())
    assert len(rows) == 150
    assert all(row["id"].isdigit() for row in rows)
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(set(row["metadata"]) == set(rows[0]["metadata"]) for row in rows)
    records = [source_record_from_311(row) for row in rows]
    selected = recurring_311_slice(records)
    dates = {record.occurred_at.date() for record in selected}
    assert len(selected) <= 50
    assert len(dates) >= 2
    assert (max(dates) - min(dates)).days >= 29
