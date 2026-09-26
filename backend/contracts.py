from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


NodeKind = Literal['entity', 'fact', 'pattern', 'summary']
NodeStatus = Literal['active', 'archived']
EdgeRelation = Literal['related_to', 'located_at', 'contradicts', 'member_of']
TraceType = Literal[
    'ingested', 'extracted', 'merged', 'retrieved', 'clustered', 'grouped',
    'recommended', 'scored', 'error',
]


@dataclass(slots=True)
class SourceRecord:
    id: str
    text: str
    occurred_at: datetime
    available_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryNode:
    id: str
    kind: NodeKind
    text: str
    scope_key: str
    source_ids: list[str]
    first_seen_at: datetime
    last_seen_at: datetime
    last_retrieved_at: datetime | None = None
    retrieval_count: int = 0
    status: NodeStatus = 'active'
    group_id: str | None = None


@dataclass(slots=True)
class MemoryEdge:
    id: str
    source_id: str
    target_id: str
    relation: EdgeRelation
    weight: float
    source_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GraphBatch:
    batch_id: str
    session_id: str
    as_of: datetime
    nodes: list[MemoryNode]
    edges: list[MemoryEdge]
    source_ids: list[str]
    status: Literal['pending', 'committed'] = 'pending'


@dataclass(slots=True)
class MergeResult:
    batch_id: str
    id_map: dict[str, str]
    created_ids: list[str]
    updated_ids: list[str]
    edge_ids: list[str]
    committed: bool


@dataclass(slots=True)
class RetrievedContext:
    seed_ids: list[str]
    nodes: list[MemoryNode]
    edges: list[MemoryEdge]
    source_ids: list[str]
    context_text: str
    token_count: int
    truncated: bool


@dataclass(slots=True)
class GroupingLimits:
    grouping_threshold: int = 8
    max_snapshot_nodes: int = 500


@dataclass(slots=True)
class GroupingResult:
    snapshot_id: str
    communities: list[list[str]]
    eligible_sizes: list[int]
    selected_member_ids: list[str]
    summary_id: str | None
    context_tokens_before: int
    context_tokens_after: int
    truncated: bool = False
    summary_text: str | None = None


@dataclass(slots=True)
class TraceEvent:
    run_id: str
    sequence: int
    simulated_at: datetime
    type: TraceType
    payload: dict[str, Any]
