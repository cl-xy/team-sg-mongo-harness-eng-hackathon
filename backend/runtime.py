from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime
from collections.abc import Sequence

from backend.contracts import (
    GraphBatch,
    GroupingLimits,
    MemoryEdge,
    MemoryNode,
    MergeResult,
    RetrievedContext,
    SourceRecord,
)


class InMemoryHarnessServices:
    """Deterministic fixture adapter for exercising the integration harness."""

    def __init__(self) -> None:
        self.nodes: dict[str, MemoryNode] = {}
        self.edges: dict[str, MemoryEdge] = {}
        self.records: dict[str, SourceRecord] = {}
        self.grouping_store = self
        self.grouping_limits = GroupingLimits()
        self._batches: set[str] = set()

    def ingest(self, records: Sequence[SourceRecord]) -> None:
        for record in records:
            self.records[record.id] = record

    def extract(self, records: Sequence[SourceRecord], session_id: str) -> GraphBatch:
        nodes: list[MemoryNode] = []
        for record in records:
            complaint_type = str(record.metadata.get('complaint_type', 'Unknown'))
            descriptor = str(record.metadata.get('descriptor', 'Unspecified'))
            location = str(record.metadata.get('location', 'Unknown'))
            node_id = f'fact-{record.id}'
            nodes.append(MemoryNode(
                id=node_id,
                kind='fact',
                text=f'{complaint_type} ({descriptor}) reported at {location}: {record.text}',
                scope_key=(
                    f'{complaint_type.casefold()}:{descriptor.casefold()}:{location.casefold()}'
                ),
                source_ids=[record.id],
                first_seen_at=record.occurred_at,
                last_seen_at=record.occurred_at,
            ))

        edge_groups: dict[str, list[MemoryNode]] = defaultdict(list)
        for node in nodes:
            edge_groups[node.scope_key].append(node)
        edges: list[MemoryEdge] = []
        for related in edge_groups.values():
            for index, source in enumerate(related):
                for target in related[index + 1:]:
                    pair = sorted((source.id, target.id))
                    edge_id = 'related-' + hashlib.sha256('|'.join(pair).encode()).hexdigest()[:20]
                    edges.append(MemoryEdge(
                        id=edge_id,
                        source_id=pair[0],
                        target_id=pair[1],
                        relation='related_to',
                        weight=1.0,
                        source_ids=sorted(set(source.source_ids + target.source_ids)),
                    ))
        batch_material = '|'.join(sorted(record.id for record in records))
        batch_id = 'batch-' + hashlib.sha256(batch_material.encode()).hexdigest()[:20]
        return GraphBatch(
            batch_id=batch_id,
            session_id=session_id,
            as_of=max(record.available_at for record in records),
            nodes=nodes,
            edges=edges,
            source_ids=sorted(record.id for record in records),
        )

    def merge(self, batch: GraphBatch) -> MergeResult:
        if batch.batch_id in self._batches:
            return MergeResult(batch.batch_id, {}, [], [], [], True)
        created_ids: list[str] = []
        updated_ids: list[str] = []
        for node in batch.nodes:
            existing = self.nodes.get(node.id)
            if existing is None:
                self.nodes[node.id] = node
                created_ids.append(node.id)
            else:
                existing.source_ids = sorted(set(existing.source_ids + node.source_ids))
                existing.last_seen_at = max(existing.last_seen_at, node.last_seen_at)
                updated_ids.append(node.id)
        for edge in batch.edges:
            self.edges[edge.id] = edge
        self._batches.add(batch.batch_id)
        return MergeResult(
            batch.batch_id,
            {node.id: node.id for node in batch.nodes},
            created_ids,
            updated_ids,
            [edge.id for edge in batch.edges],
            True,
        )

    def retrieve(self, query: str, session_id: str, as_of: datetime) -> RetrievedContext:
        query_terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
        candidates = []
        for node in self.nodes.values():
            if node.status != 'active' or node.first_seen_at > as_of:
                continue
            overlap = len(query_terms & set(re.findall(r"[a-z0-9]+", node.text.casefold())))
            if overlap:
                candidates.append((overlap, node.id, node))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected = [item[2] for item in candidates[:5]]
        source_ids = sorted({source_id for node in selected for source_id in node.source_ids})
        text = '\n'.join(node.text for node in selected)
        token_count = len(text.split())
        selected_ids = {node.id for node in selected}
        context_edges = [
            edge for edge in self.edges.values()
            if edge.source_id in selected_ids and edge.target_id in selected_ids
        ]
        return RetrievedContext(
            seed_ids=[node.id for node in selected],
            nodes=selected,
            edges=context_edges,
            source_ids=source_ids,
            context_text=text,
            token_count=token_count,
            truncated=len(candidates) > len(selected),
        )

    def recommend(self, records: Sequence[SourceRecord], context: RetrievedContext | None) -> dict:
        group_counts: dict[tuple[str, str], list[str]] = defaultdict(list)
        for record in records:
            key = (
                str(record.metadata.get('complaint_type', 'Unknown')),
                str(record.metadata.get('location', 'Unknown')),
            )
            group_counts[key].append(record.id)
        (complaint_type, location), source_ids = max(
            group_counts.items(), key=lambda item: (len(item[1]), item[0]),
        )
        return {
            'recommendation': f'Investigate the recurring {complaint_type} reports at {location}.',
            'evidence_source_ids': sorted(source_ids),
            'historical_context_source_ids': context.source_ids if context else [],
            'is_hypothesis': True,
        }

    def graph_snapshot(self):
        material = '|'.join(sorted(self.nodes))
        snapshot_id = 'snapshot-' + hashlib.sha256(material.encode()).hexdigest()[:20]
        return snapshot_id, list(self.nodes.values()), list(self.edges.values())

    def insert_summary(self, summary: MemoryNode) -> None:
        self.nodes.setdefault(summary.id, summary)

    def insert_member_edge(self, edge: MemoryEdge) -> None:
        self.edges.setdefault(edge.id, edge)

    def assign_group(self, member_ids: Sequence[str], summary_id: str) -> None:
        for member_id in member_ids:
            self.nodes[member_id].group_id = summary_id

    def context_token_count(self, node_ids: Sequence[str]) -> int:
        return sum(len(self.nodes[node_id].text.split()) for node_id in node_ids)

    @staticmethod
    def build_summary(members: Sequence[MemoryNode]) -> str:
        source_ids = sorted({source_id for node in members for source_id in node.source_ids})
        return (
            f'{len(members)} related observations across {len(source_ids)} source records: '
            + '; '.join(sorted({node.text.split(':', 1)[0] for node in members}))
        )


def create_services() -> InMemoryHarnessServices:
    return InMemoryHarnessServices()
