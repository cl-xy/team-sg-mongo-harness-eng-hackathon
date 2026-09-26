"""Schema-first extraction of a source-backed short-term graph."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from .types import ExtractionFailure, GraphBatch, MemoryEdge, MemoryNode, SourceRecord

ExtractionClient = Callable[[dict[str, Any]], dict[str, Any] | str]
FailureSink = Callable[[ExtractionFailure], None]
ErrorEmitter = Callable[[dict[str, Any]], None]
ALLOWED_KINDS = {"entity", "fact", "pattern", "summary"}
ASSERTIONS = {"observation", "hypothesis"}
HYPOTHESIS_CUES = re.compile(r"\b(cause[ds]?|causal|root cause|unlicensed|because|permit status)\b", re.IGNORECASE)


class ExtractionError(ValueError):
    """Raised when a model response cannot safely become a graph."""


def normalized_record(record: SourceRecord) -> dict[str, Any]:
    """Pass trusted 311 fields through instead of asking the model to infer them."""
    return {
        "id": record.id,
        "text": record.text,
        "occurred_at": record.occurred_at.isoformat(),
        "available_at": record.available_at.isoformat(),
        "metadata": record.metadata,
    }


def source_block_key(record: SourceRecord) -> str:
    """Keep factual claims scoped to an immutable 311 complaint block."""
    return f"source:{record.id}"


def source_location_key(record: SourceRecord) -> str:
    """Stable source-derived location scope; no model-created place identity."""
    location = record.metadata.get("location")
    if isinstance(location, dict) and isinstance(location.get("coordinates"), list):
        return "point:" + ",".join(str(value) for value in location["coordinates"])
    latitude, longitude = record.metadata.get("latitude"), record.metadata.get("longitude")
    if latitude is not None and longitude is not None:
        return f"point:{longitude},{latitude}"
    borough, postal_code = record.metadata.get("borough"), record.metadata.get("incident_zip")
    return f"area:{borough or 'unknown'}:{postal_code or 'unknown'}"


def extraction_request(records: list[SourceRecord]) -> dict[str, Any]:
    """The schema/prompt boundary supplied to the LLM adapter.

    Structured 311 fields are trusted source metadata; the model only chunks
    descriptive text and links those chunks. A complaint can support an
    observation, but causal explanations must be labelled hypotheses.
    """
    return {
        "instructions": (
            "Chunk only the supplied descriptive text into concepts. Preserve every "
            "source ID. A fact is one observation from exactly one source block and "
            "must use that source's scope_key. Do not combine paraphrases from distinct "
            "blocks into one fact. Mark reported conditions as 'observation'. Mark any "
            "cause, business identity, permit status, or recommended intervention as "
            "'hypothesis'; complaints alone never prove these. Return JSON only."
        ),
        "records": [normalized_record(record) | {"source_block_key": source_block_key(record)} for record in records],
        "json_schema": {
            "type": "object",
            "required": ["nodes", "edges"],
            "properties": {
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "kind", "text", "scope_key", "source_ids"],
                        "properties": {
                            "id": {"type": "string"},
                            "kind": {"enum": sorted(ALLOWED_KINDS)},
                            "text": {"type": "string"},
                            "scope_key": {"type": "string"},
                            "source_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                            "assertion": {"enum": sorted(ASSERTIONS)},
                        },
                    },
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "source_id", "target_id", "relation", "source_ids"],
                        "properties": {
                            "id": {"type": "string"},
                            "source_id": {"type": "string"},
                            "target_id": {"type": "string"},
                            "relation": {"type": "string"},
                            "weight": {"type": "number", "exclusiveMinimum": 0},
                            "source_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        },
                    },
                },
            },
        },
    }


def _deterministic_id(prefix: str, *parts: str) -> str:
    digest = sha256("|".join(parts).encode()).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _parse(raw: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ExtractionError("extractor returned invalid JSON") from error
    if not isinstance(raw, dict):
        raise ExtractionError("extractor response must be an object")
    return raw


def _source_ids(value: Any, valid_ids: set[str], owner: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ExtractionError(f"{owner} must have a non-empty source_ids list")
    source_ids = list(dict.fromkeys(value))
    unknown = set(source_ids) - valid_ids
    if unknown:
        raise ExtractionError(f"{owner} references unknown sources: {sorted(unknown)}")
    return source_ids


def _validate(raw: dict[str, Any], records: list[SourceRecord]) -> tuple[list[MemoryNode], list[MemoryEdge]]:
    raw_nodes, raw_edges = raw.get("nodes"), raw.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ExtractionError("response must contain nodes and edges arrays")
    known_sources = {record.id for record in records}
    record_times = {record.id: record.occurred_at for record in records}
    record_blocks = {record.id: source_block_key(record) for record in records}
    record_locations = {record.id: source_location_key(record) for record in records}
    nodes: list[MemoryNode] = []
    ids: set[str] = set()
    for item in raw_nodes:
        if not isinstance(item, dict):
            raise ExtractionError("each node must be an object")
        node_id, kind, text, scope_key = (item.get(key) for key in ("id", "kind", "text", "scope_key"))
        if not all(isinstance(value, str) and value.strip() for value in (node_id, kind, text, scope_key)):
            raise ExtractionError("nodes require non-empty id, kind, text, and scope_key")
        if kind not in ALLOWED_KINDS or node_id in ids:
            raise ExtractionError("node kind is invalid or node id is duplicated")
        source_ids = _source_ids(item.get("source_ids"), known_sources, f"node {node_id}")
        assertion = item.get("assertion")
        if kind in {"fact", "pattern", "summary"} and assertion not in ASSERTIONS:
            raise ExtractionError(f"node {node_id} must label its assertion as observation or hypothesis")
        if kind == "entity" and assertion is not None:
            raise ExtractionError(f"entity node {node_id} cannot make an assertion")
        if assertion == "observation" and HYPOTHESIS_CUES.search(text):
            raise ExtractionError(f"node {node_id} contains causal/root-cause language and must be a hypothesis")
        if kind == "fact":
            if len(source_ids) != 1:
                raise ExtractionError(f"fact node {node_id} must cite exactly one source block")
            expected_scope = record_blocks[source_ids[0]]
            if scope_key != expected_scope:
                raise ExtractionError(f"fact node {node_id} must use its source block scope_key")
        if kind == "pattern":
            locations = {record_locations[source_id] for source_id in source_ids}
            if len(locations) != 1 or scope_key != f"location:{locations.pop()}":
                raise ExtractionError(f"pattern node {node_id} must be scoped to one source-derived location")
        times = [record_times[source_id] for source_id in source_ids]
        nodes.append(MemoryNode(node_id, kind, text, scope_key, source_ids, min(times), max(times), assertion))
        ids.add(node_id)

    edges: list[MemoryEdge] = []
    edge_ids: set[str] = set()
    for item in raw_edges:
        if not isinstance(item, dict):
            raise ExtractionError("each edge must be an object")
        edge_id, source_id, target_id, relation = (item.get(key) for key in ("id", "source_id", "target_id", "relation"))
        if not all(isinstance(value, str) and value.strip() for value in (edge_id, source_id, target_id, relation)):
            raise ExtractionError("edges require non-empty id, endpoints, and relation")
        if edge_id in edge_ids or source_id not in ids or target_id not in ids or source_id == target_id:
            raise ExtractionError("edge IDs/endpoints are invalid")
        weight = item.get("weight", 1.0)
        if not isinstance(weight, (int, float)) or weight <= 0:
            raise ExtractionError("edge weight must be positive")
        source_ids = _source_ids(item.get("source_ids"), known_sources, f"edge {edge_id}")
        edges.append(MemoryEdge(edge_id, source_id, target_id, relation, float(weight), source_ids))
        edge_ids.add(edge_id)
    return nodes, edges


def extract_concepts(
    records: list[SourceRecord], session_id: str, *, extractor: ExtractionClient,
    failure_sink: FailureSink | None = None, emit_error: ErrorEmitter | None = None,
) -> GraphBatch:
    """Extract a pending, source-backed graph, retrying malformed output once."""
    if not records:
        raise ValueError("cannot extract concepts from an empty record batch")
    unique = {record.id: record for record in records}
    ordered = sorted(unique.values(), key=lambda record: (record.occurred_at, record.id))
    last_error: ExtractionError | None = None
    for _ in range(2):
        try:
            nodes, edges = _validate(_parse(extractor(extraction_request(ordered))), ordered)
            as_of = max(record.occurred_at for record in ordered)
            batch_id = _deterministic_id("batch", session_id, *(record.id for record in ordered))
            return GraphBatch(batch_id, session_id, as_of, nodes, edges, [record.id for record in ordered])
        except Exception as error:
            if not isinstance(error, ExtractionError):
                error = ExtractionError(f"extractor call failed: {error}")
            last_error = error
    failure = ExtractionFailure(
        session_id=session_id,
        source_ids=[record.id for record in ordered],
        records=[normalized_record(record) for record in ordered],
        attempts=2,
        error=str(last_error or "extraction failed"),
        failed_at=datetime.now(timezone.utc),
    )
    if failure_sink:
        failure_sink(failure)
    if emit_error:
        emit_error({"type": "error", "payload": {"stage": "extraction", "session_id": session_id, "source_ids": failure.source_ids, "error": failure.error}})
    raise last_error or ExtractionError("extraction failed")
