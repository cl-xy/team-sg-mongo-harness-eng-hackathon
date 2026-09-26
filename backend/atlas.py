from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient, UpdateOne
from pymongo.errors import OperationFailure
from pymongo.database import Database

from backend.contracts import (
    GraphBatch,
    GroupingLimits,
    MemoryEdge,
    MemoryNode,
    MergeResult,
    RetrievedContext,
    SourceRecord,
)
from backend.recommendation import DEFAULT_MODEL, model_recommendation
from backend.runtime import InMemoryHarnessServices
from backend.memory.retrieval_adapter import MongoMemoryRetrievalStore as MongoRetrievalStore


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


def _contract_fields(contract, document: dict) -> dict:
    names = {item.name for item in fields(contract)}
    return {key: value for key, value in document.items() if key in names}


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

    def __init__(self, database: Database, *, openrouter_key: str | None = None, model: str = DEFAULT_MODEL) -> None:
        super().__init__()
        self.database = database
        self.openrouter_key = openrouter_key
        self.model = model
        self.latest_summary: str | None = None
        threshold = os.environ.get('GROUPING_THRESHOLD') or _load_env().get('GROUPING_THRESHOLD')
        if threshold:
            self.grouping_limits = GroupingLimits(grouping_threshold=int(threshold))
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
            self.nodes[document['id']] = MemoryNode(**_contract_fields(MemoryNode, document))
        for document in self.database.memory_edges.find({}, {'_id': False}):
            self.edges[document['id']] = MemoryEdge(**_contract_fields(MemoryEdge, document))
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
        self.latest_summary = summary.text

    def recommend(self, records: Sequence[SourceRecord], context: RetrievedContext | None) -> dict[str, Any]:
        fallback = super().recommend(records, context)
        if not self.openrouter_key:
            return {**fallback, 'recommender': 'template'}
        return model_recommendation(
            self.openrouter_key, self.model, records, context, self.latest_summary, fallback,
        )

    def insert_member_edge(self, edge: MemoryEdge) -> None:
        super().insert_member_edge(edge)
        self._upsert_edges([edge])

    def assign_group(self, member_ids: Sequence[str], summary_id: str) -> None:
        super().assign_group(member_ids, summary_id)
        self._upsert_nodes(member_ids)


def create_legacy_services() -> AtlasHarnessServices:
    env = _load_env()
    return AtlasHarnessServices(
        connect(),
        openrouter_key=env.get('OPENROUTER_API_KEY'),
        model=env.get('OPENROUTER_MODEL', DEFAULT_MODEL),
    )


class ExactOnlySearch:
    """Explicit no-vector search: the merge engine falls back to exact identity keys."""

    mode = 'none'

    def search_memories(self, text: str, limit: int = 5, filters: dict | None = None) -> list[dict]:
        return []


def create_merge_services():
    """Jiacheng's merge engine and Mongo store behind the shared harness boundary.

    Uses Atlas Vector Search when the automated-embedding index is queryable,
    otherwise an explicit exact-identity search so the run never silently
    depends on an index that is still building.
    """
    from backend.memory.embeddings import AtlasMemorySearch, OpenRouterJudge, configure_search
    from backend.memory.retrieval import RetrievalLimits, retrieve_context
    from backend.memory.services import MemoryHarnessServices
    from backend.memory.store import MongoMemoryStore

    env = _load_env()
    os.environ.update({key: value for key, value in env.items() if key not in os.environ})
    os.environ.setdefault('OPENROUTER_MODEL', DEFAULT_MODEL)
    store = MongoMemoryStore.from_env()
    try:
        store.ensure_indexes()
    except OperationFailure as error:
        if error.code != 85:  # IndexOptionsConflict: an equivalent index exists under another name
            raise

    search = ExactOnlySearch()
    try:
        atlas_search = AtlasMemorySearch.from_env(store.nodes)
        try:
            atlas_search.ensure_index()
        except ValueError:
            pass  # an index with this name already exists; use it if it is ready
        indexes = list(store.nodes.list_search_indexes(name=atlas_search.index_name))
        if indexes and indexes[0].get('status') == 'READY' and indexes[0].get('queryable'):
            search = atlas_search
    except Exception:
        pass
    configure_search(search)

    judge = OpenRouterJudge.from_env() if env.get('OPENROUTER_API_KEY') else None
    fixture = InMemoryHarnessServices()
    recommender = AtlasHarnessServices.__new__(AtlasHarnessServices)
    InMemoryHarnessServices.__init__(recommender)
    recommender.openrouter_key = env.get('OPENROUTER_API_KEY')
    recommender.model = os.environ['OPENROUTER_MODEL']
    recommender.latest_summary = None

    def build_summary(members):
        text = fixture.build_summary(members)
        recommender.latest_summary = text
        return text

    def recommend(records, context):
        fallback = InMemoryHarnessServices.recommend(recommender, records, context)
        fallback['search'] = search.mode
        if not recommender.openrouter_key:
            return {**fallback, 'recommender': 'template'}
        return model_recommendation(
            recommender.openrouter_key, recommender.model, records, context,
            recommender.latest_summary, fallback,
        )

    retrieval_store = MongoRetrievalStore(store.database, search)

    def retrieve(query, session_id, as_of):
        if search.mode == 'none':
            return RetrievedContext([], [], [], [], '', 0, False)
        result = retrieve_context(
            query[:2000],
            session_id,
            as_of,
            RetrievalLimits(),
            store=retrieval_store,
        )
        return result

    return MemoryHarnessServices(
        store, search, judge=judge,
        extract=fixture.extract, retrieve=retrieve, recommend=recommend, build_summary=build_summary,
    )


def create_services():
    """Create the Atlas-backed merge, bounded-retrieval, and harness services."""
    return create_merge_services()


def create_fast_services() -> AtlasHarnessServices:
    """Deterministic merge with Atlas persistence and the model recommender; proven demo path."""
    env = _load_env()
    return AtlasHarnessServices(
        connect(),
        openrouter_key=env.get('OPENROUTER_API_KEY'),
        model=env.get('OPENROUTER_MODEL', DEFAULT_MODEL),
    )
