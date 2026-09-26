from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

from backend.contracts import (
    GraphBatch,
    GroupingLimits,
    GroupingResult,
    MergeResult,
    RetrievedContext,
    SourceRecord,
    TraceEvent,
    TraceType,
)
from backend.memory.grouping import GroupingStore, SummaryBuilder, group_oversized_clusters


Mode = Literal['baseline', 'memory']


class HarnessServices(Protocol):
    grouping_store: GroupingStore
    grouping_limits: GroupingLimits
    build_summary: SummaryBuilder

    def ingest(self, records: Sequence[SourceRecord]) -> None: ...
    def extract(self, records: Sequence[SourceRecord], session_id: str) -> GraphBatch: ...
    def merge(self, batch: GraphBatch) -> MergeResult: ...
    def retrieve(self, query: str, session_id: str, as_of: datetime) -> RetrievedContext: ...
    def recommend(
        self, records: Sequence[SourceRecord], context: RetrievedContext | None,
    ) -> dict[str, Any]: ...


def run_step(
    records: Sequence[SourceRecord],
    mode: Mode,
    services: HarnessServices,
    *,
    session_id: str = '311-demo',
) -> list[TraceEvent]:
    if mode not in ('baseline', 'memory'):
        raise ValueError(f'Unsupported mode: {mode}')
    if not records:
        return []
    ordered = sorted(records, key=lambda record: (record.available_at, record.id))
    run_id = str(uuid4())
    simulated_at = max(record.available_at for record in ordered)
    events: list[TraceEvent] = []

    def emit(event_type: TraceType, payload: dict[str, Any]) -> None:
        events.append(TraceEvent(run_id, len(events), simulated_at, event_type, payload))

    try:
        services.ingest(ordered)
        emit('ingested', {'record_ids': [record.id for record in ordered]})
        context = None
        if mode == 'memory':
            query = '\n'.join(record.text for record in ordered)
            context = services.retrieve(query, session_id, simulated_at)
            emit('retrieved', {
                'seed_ids': context.seed_ids,
                'source_ids': context.source_ids,
                'token_count': context.token_count,
                'truncated': context.truncated,
            })

        if mode == 'memory':
            batch = services.extract(ordered, session_id)
            emit('extracted', {
                'batch_id': batch.batch_id,
                'node_count': len(batch.nodes),
                'edge_count': len(batch.edges),
                'source_ids': batch.source_ids,
            })
            merge = services.merge(batch)
            emit('merged', {
                'batch_id': merge.batch_id,
                'created_ids': merge.created_ids,
                'updated_ids': merge.updated_ids,
                'committed': merge.committed,
            })
            if not merge.committed:
                raise RuntimeError(f'Batch {batch.batch_id} was not committed')
            grouping: GroupingResult = group_oversized_clusters(
                services.grouping_store,
                simulated_at,
                services.grouping_limits,
                services.build_summary,
            )
            emit('clustered', {
                'snapshot_id': grouping.snapshot_id,
                'communities': grouping.communities,
                'eligible_sizes': grouping.eligible_sizes,
                'truncated': grouping.truncated,
            })
            if grouping.summary_id:
                emit('grouped', {
                    'summary_id': grouping.summary_id,
                    'member_ids': grouping.selected_member_ids,
                    'context_tokens_before': grouping.context_tokens_before,
                    'context_tokens_after': grouping.context_tokens_after,
                })
        emit('recommended', services.recommend(ordered, context))
    except Exception as error:
        emit('error', {'error': type(error).__name__, 'error_description': str(error)})
    return events
