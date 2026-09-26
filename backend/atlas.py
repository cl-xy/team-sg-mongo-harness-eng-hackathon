from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient, UpdateOne
from pymongo.database import Database

from backend.contracts import GraphBatch, MemoryEdge, MemoryNode, MergeResult, SourceRecord
from backend.runtime import InMemoryHarnessServices


def _load_env(path: Path = Path('.env')) -> dict[str, str]:
    values = dict(os.environ)
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            key, separator, value = line.partition('=')
            if separator and key.strip() and not key.startswith('#'):
                values.setdefault(key.strip(), value.strip())
    return values


def connect() -> Database:
    env = _load_env()
    client = MongoClient(env['MONGODB_URI'], serverSelectionTimeoutMS=10_000)
    return client[env.get('MONGODB_DATABASE', '311_memory')]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def load_source_records(database: Database) -> list[SourceRecord]:
    records = []
    for document in database.source_records.find({}, {'_id': False}).sort('available_at', 1):
        document['occurred_at'] = _aware(document['occurred_at'])
        document['available_at'] = _aware(document['available_at'])
        records.append(SourceRecord(**document))
    return records


class AtlasHarnessServices(InMemoryHarnessServices):
    """Persists the memory graph to Atlas while reusing the deterministic pipeline."""

    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        database.memory_nodes.create_index('id', unique=True)
        database.memory_nodes.create_index('source_ids')
        database.memory_edges.create_index('id', unique=True)
        database.memory_edges.create_index([('source_id', 1), ('target_id', 1)])
        self._load_graph()

    def _load_graph(self) -> None:
        for document in self.database.memory_nodes.find({}, {'_id': False}):
            for key in ('first_seen_at', 'last_seen_at'):
                document[key] = _aware(document[key])
            if document.get('last_retrieved_at'):
                document['last_retrieved_at'] = _aware(document['last_retrieved_at'])
            self.nodes[document['id']] = MemoryNode(**document)
        for document in self.database.memory_edges.find({}, {'_id': False}):
            self.edges[document['id']] = MemoryEdge(**document)
        for document in self.database.short_term_batches.find({'status': 'committed'}, {'batch_id': True}):
            self._batches.add(document['batch_id'])

    def _upsert_nodes(self, node_ids: Sequence[str]) -> None:
        operations = [
            UpdateOne({'id': node_id}, {'$set': asdict(self.nodes[node_id])}, upsert=True)
            for node_id in node_ids
        ]
        if operations:
            self.database.memory_nodes.bulk_write(operations, ordered=False)

    def _upsert_edges(self, edges: Sequence[MemoryEdge]) -> None:
        operations = [UpdateOne({'id': edge.id}, {'$set': asdict(edge)}, upsert=True) for edge in edges]
        if operations:
            self.database.memory_edges.bulk_write(operations, ordered=False)

    def merge(self, batch: GraphBatch) -> MergeResult:
        result = super().merge(batch)
        self._upsert_nodes(result.created_ids + result.updated_ids)
        self._upsert_edges(batch.edges)
        self.database.short_term_batches.update_one(
            {'batch_id': batch.batch_id},
            {'$set': {
                'batch_id': batch.batch_id,
                'session_id': batch.session_id,
                'as_of': batch.as_of,
                'source_ids': batch.source_ids,
                'status': 'committed',
            }},
            upsert=True,
        )
        return result

    def insert_summary(self, summary: MemoryNode) -> None:
        super().insert_summary(summary)
        self._upsert_nodes([summary.id])

    def insert_member_edge(self, edge: MemoryEdge) -> None:
        super().insert_member_edge(edge)
        self._upsert_edges([edge])

    def assign_group(self, member_ids: Sequence[str], summary_id: str) -> None:
        super().assign_group(member_ids, summary_id)
        self._upsert_nodes(member_ids)


def create_services() -> AtlasHarnessServices:
    return AtlasHarnessServices(connect())
