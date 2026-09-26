"""Durable graph operations. One merge writer; evidence is always a set of IDs."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Protocol

from backend.contracts import MemoryEdge, MemoryNode


def document(value) -> dict:
    """Accept the shared dataclasses, extraction dataclasses and driver documents."""
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, 'model_dump'):
        return value.model_dump()
    return deepcopy(dict(value))


def source_document(source) -> dict:
    value = document(source)
    for field in ('occurred_at', 'available_at'):
        timestamp = utc(value[field])
        # BSON precision also defines the fixture adapter's replay semantics.
        value[field] = timestamp.replace(microsecond=timestamp.microsecond // 1000 * 1000)
    return value

def utc(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError('Timestamps must include a UTC offset')
    return parsed.astimezone(timezone.utc)


def union_node(existing: dict | None, incoming: dict) -> dict:
    if existing is None:
        return deepcopy(incoming)
    result = deepcopy(existing)
    result['source_ids'] = sorted(set(existing['source_ids']) | set(incoming['source_ids']))
    result['first_seen_at'] = min(utc(existing['first_seen_at']), utc(incoming['first_seen_at']))
    result['last_seen_at'] = max(utc(existing['last_seen_at']), utc(incoming['last_seen_at']))
    for field in ('variants', 'identity_keys'):
        result.setdefault(field, [])
        for value in incoming.get(field, []):
            if value not in result[field]:
                result[field].append(deepcopy(value))
    return result


class MemoryStore(Protocol):
    def put_source(self, source) -> None: ...
    def get_source(self, id: str) -> dict | None: ...
    def get_node(self, id: str) -> dict | None: ...
    def exact_candidates(self, candidate: dict) -> list[dict]: ...
    def recent_candidates(self, candidate: dict, limit: int) -> list[dict]: ...
    def get_batch(self, batch_id: str) -> dict | None: ...
    def pending_batch_ids(self) -> list[str]: ...
    def save_plan(self, plan: dict) -> None: ...
    def upsert_node(self, node: dict) -> None: ...
    def upsert_edge(self, edge: dict) -> None: ...
    def commit_batch(self, batch_id: str) -> None: ...
    def grouping_candidates(self): ...
    def edges_between(self, node_ids: list[str]) -> list[dict]: ...
    def assign_group(self, member_ids: list[str], summary_id: str) -> None: ...


class InMemoryStore:
    """Fixture implementation, explicitly selected by tests/offline callers only."""
    def __init__(self):
        self.sources: dict[str, dict] = {}
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.batches: dict[str, dict] = {}

    def put_source(self, source: dict) -> None:
        source = source_document(source)
        if source['id'] in self.sources and self.sources[source['id']] != source:
            raise ValueError('Source IDs are immutable')
        self.sources[source['id']] = deepcopy(source)

    def get_source(self, id): return deepcopy(self.sources.get(id))
    def get_node(self, id): return deepcopy(self.nodes.get(id))
    def get_batch(self, batch_id): return deepcopy(self.batches.get(batch_id))

    def exact_candidates(self, candidate):
        return [deepcopy(n) for n in self.nodes.values()
                if n['kind'] == candidate['kind'] and n['scope_key'] == candidate['scope_key']
                and (set(n['source_ids']) & set(candidate['source_ids'])
                     or set(n.get('identity_keys', [])) & set(candidate['identity_keys']))]

    def recent_candidates(self, candidate, limit):
        nodes = [n for n in self.nodes.values() if n['kind'] == candidate['kind']
                 and n['scope_key'] == candidate['scope_key'] and n['status'] == 'active']
        return deepcopy(sorted(nodes, key=lambda n: (utc(n['last_seen_at']), n['id']), reverse=True)[:limit])

    def pending_batch_ids(self):
        return [id for id, b in self.batches.items() if b['status'] == 'pending' and 'write_plan' in b]

    def save_plan(self, plan):
        existing = self.batches.get(plan['batch_id'])
        if existing and 'write_plan' in existing:
            if existing['fingerprint'] != plan['fingerprint']:
                raise ValueError('Batch ID has a different write plan')
            return
        self.batches[plan['batch_id']] = deepcopy(plan)

    def upsert_node(self, node):
        self.nodes[node['id']] = union_node(self.nodes.get(node['id']), node)

    def upsert_edge(self, edge):
        if not all(id in self.nodes for id in (edge['source_id'], edge['target_id'])):
            raise ValueError('An edge endpoint does not exist')
        previous = self.edges.get(edge['id'])
        result = deepcopy(edge)
        if previous:
            result['source_ids'] = sorted(set(previous['source_ids']) | set(edge['source_ids']))
            result['weight'] = max(previous['weight'], edge['weight'])
        self.edges[edge['id']] = result

    def commit_batch(self, batch_id):
        self.batches[batch_id]['status'] = 'committed'

    def grouping_candidates(self):
        for node in sorted(self.nodes.values(), key=lambda n:n['id']):
            if node['kind'] in ('fact', 'pattern') and node['status'] == 'active' and node.get('group_id') is None:
                yield deepcopy(node)

    def edges_between(self, node_ids):
        ids = set(node_ids)
        return [deepcopy(edge) for edge in self.edges.values()
                if edge['source_id'] in ids and edge['target_id'] in ids]

    def assign_group(self, member_ids, summary_id):
        for id in member_ids:
            self.nodes[id]['group_id'] = summary_id


REGULAR_INDEXES = {
    'source_records': [('id', True), ('available_at', False)],
    'memory_nodes': [('id', True), ('source_ids', False), ('identity_keys', False), ('group_id', False),
                     ([('kind', 1), ('scope_key', 1), ('status', 1), ('last_seen_at', -1)], False)],
    'memory_edges': [('id', True), ('source_id', False), ('target_id', False), ('source_ids', False)],
    'short_term_batches': [('batch_id', True), ('status', False)],
}


class MongoMemoryStore:
    """Official PyMongo driver; no network requests occur until explicitly used."""
    def __init__(self, database: Any, search=None):
        self.database = database
        self.search = search
        self.nodes = database['memory_nodes']
        self.edges = database['memory_edges']
        self.sources = database['source_records']
        self.batches = database['short_term_batches']

    @classmethod
    def from_env(cls):
        from pymongo import MongoClient
        uri, name = os.getenv('MONGODB_URI'), os.getenv('MONGODB_DATABASE')
        if not uri or not name:
            raise RuntimeError('Set MONGODB_URI and MONGODB_DATABASE')
        client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=10000,
                             connectTimeoutMS=10000, socketTimeoutMS=30000)
        return cls(client[name])

    def ensure_indexes(self):
        for name, indexes in REGULAR_INDEXES.items():
            for fields, unique in indexes:
                self.database[name].create_index(fields, unique=unique)

    def put_source(self, source):
        value = source_document(source)
        existing = self.get_source(value['id'])
        if existing is not None and existing != value:
            raise ValueError('Source IDs are immutable')
        self.sources.update_one({'id': value['id']}, {'$setOnInsert': value}, upsert=True)

    def get_source(self, id): return self.sources.find_one({'id': id}, {'_id': 0})
    def get_node(self, id): return self.nodes.find_one({'id': id}, {'_id': 0})
    def get_batch(self, batch_id): return self.batches.find_one({'batch_id': batch_id}, {'_id': 0})

    def get_memory_nodes(self, node_ids):
        return list(self.nodes.find({'id': {'$in': list(node_ids)}}, {'_id': 0, 'embedding': 0}))

    def get_memory_edges(self, node_ids, limit):
        if not node_ids or limit <= 0:
            return []
        return list(self.edges.find({
            '$or': [
                {'source_id': {'$in': list(node_ids)}},
                {'target_id': {'$in': list(node_ids)}},
            ],
        }, {'_id': 0}).sort('id', 1).limit(limit))

    def get_source_records(self, source_ids):
        if not source_ids:
            return []
        return list(self.sources.find({'id': {'$in': list(source_ids)}}, {'_id': 0}))

    def mark_nodes_retrieved(self, node_ids, retrieved_at):
        if not node_ids:
            return
        self.nodes.update_many(
            {'id': {'$in': list(node_ids)}},
            {'$inc': {'retrieval_count': 1}, '$set': {'last_retrieved_at': utc(retrieved_at)}},
        )

    def exact_candidates(self, candidate):
        return list(self.nodes.find({
            'kind': candidate['kind'], 'scope_key': candidate['scope_key'],
            '$or': [{'source_ids': {'$in': candidate['source_ids']}},
                    {'identity_keys': {'$in': candidate['identity_keys']}}],
        }, {'_id': 0}).limit(100))

    def recent_candidates(self, candidate, limit):
        return list(self.nodes.find({'kind': candidate['kind'], 'scope_key': candidate['scope_key'],
                                     'status': 'active'}, {'_id': 0})
                    .sort([('last_seen_at', -1), ('id', 1)]).limit(limit))

    def pending_batch_ids(self):
        # Ingestion may persist an unplanned pending batch; only plans lock the writer.
        return [b['batch_id'] for b in self.batches.find(
            {'status': 'pending', 'write_plan': {'$exists': True}}, {'batch_id': 1})]

    def save_plan(self, plan):
        existing = self.get_batch(plan['batch_id'])
        if existing and 'write_plan' in existing:
            if existing['fingerprint'] != plan['fingerprint']:
                raise ValueError('Batch ID has a different write plan')
            return
        # Single writer: freeze all decisions before mutating the graph.
        self.batches.update_one({'batch_id': plan['batch_id']}, {'$set': deepcopy(plan)}, upsert=True)

    def upsert_node(self, node):
        value = deepcopy(node)
        for field in ('first_seen_at', 'last_seen_at'):
            value[field] = utc(value[field])
        variable = {'source_ids', 'variants', 'identity_keys', 'first_seen_at', 'last_seen_at'}
        insert = {k: v for k, v in value.items() if k not in variable}
        if self.search is not None and self.search.mode == 'explicit':
            existing = self.get_node(value['id'])
            if existing is None or 'embedding' not in existing:
                insert['embedding'] = self.search.embed_document(value['text'])
        update = {
            '$setOnInsert': insert,
            '$addToSet': {k: {'$each': value.get(k, [])} for k in ('source_ids', 'variants', 'identity_keys')},
            '$min': {'first_seen_at': value['first_seen_at']},
            '$max': {'last_seen_at': value['last_seen_at']},
        }
        self.nodes.update_one({'id': value['id']}, update, upsert=True)
        if 'embedding' in insert:
            # Also fills embeddings on existing nodes when explicit mode is enabled.
            self.nodes.update_one({'id': value['id'], 'embedding': {'$exists': False}},
                                  {'$set': {'embedding': insert['embedding']}})

    def upsert_edge(self, edge):
        for id in (edge['source_id'], edge['target_id']):
            if self.get_node(id) is None:
                raise ValueError('An edge endpoint does not exist')
        self.edges.update_one({'id': edge['id']}, {
            '$setOnInsert': {k: v for k, v in edge.items() if k not in ('source_ids', 'weight')},
            '$addToSet': {'source_ids': {'$each': edge['source_ids']}},
            '$max': {'weight': edge['weight']},
        }, upsert=True)

    def commit_batch(self, batch_id):
        self.batches.update_one({'batch_id': batch_id, 'write_plan': {'$exists': True}},
                                {'$set': {'status': 'committed'}})

    def grouping_candidates(self):
        return self.nodes.find({'kind': {'$in': ['fact', 'pattern']}, 'status': 'active',
                                'group_id': None}, {'_id': 0, 'embedding': 0}).sort('id', 1)

    def edges_between(self, node_ids):
        return list(self.edges.find({'source_id': {'$in': node_ids}, 'target_id': {'$in': node_ids}}, {'_id': 0}))

    def assign_group(self, member_ids, summary_id):
        self.nodes.update_many({'id': {'$in': member_ids}}, {'$set': {'group_id': summary_id}})


class GroupingStoreAdapter:
    """Project persisted nodes into the integrator's GroupingStore protocol.

    Fetch max_snapshot_nodes + 1 eligible nodes so grouping itself reports
    truncation. Set as_of to the harness replay clock before taking a snapshot.
    """
    def __init__(self, store: MemoryStore, *, as_of: datetime, max_snapshot_nodes=500):
        self.store, self.as_of, self.max_snapshot_nodes = store, utc(as_of), max_snapshot_nodes

    def _available(self, node):
        if utc(node['last_seen_at']) > self.as_of:
            return False
        return self._sources_available(node['source_ids'])

    def _sources_available(self, source_ids):
        for id in source_ids:
            source = self.store.get_source(id)
            if source is None or utc(source['available_at']) > self.as_of or utc(source['occurred_at']) > self.as_of:
                return False
        return bool(source_ids)

    @staticmethod
    def _node(value):
        data = {field.name: deepcopy(value[field.name]) for field in fields(MemoryNode) if field.name in value}
        for key in ('first_seen_at', 'last_seen_at', 'last_retrieved_at'):
            if data.get(key) is not None: data[key] = utc(data[key])
        # The shared MemoryNode has no assertion field yet. Preserve the label in
        # the grouping view's text; storage retains the original text and label.
        if value.get('assertion') == 'hypothesis':
            data['text'] = '[hypothesis] '+data['text']
        return MemoryNode(**data)

    def graph_snapshot(self):
        if self.store.pending_batch_ids():
            raise RuntimeError('Recover the pending merge before grouping')
        selected = []
        for node in self.store.grouping_candidates():
            if self._available(node):
                selected.append(self._node(node))
                if len(selected) > self.max_snapshot_nodes: break
        edges = [MemoryEdge(**{f.name: edge[f.name] for f in fields(MemoryEdge) if f.name in edge})
                 for edge in self.store.edges_between([n.id for n in selected])
                 if self._sources_available(edge['source_ids'])]
        payload = {'nodes': [asdict(n) for n in selected], 'edges': sorted([asdict(e) for e in edges], key=lambda e:e['id'])}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]
        return 'snapshot-'+digest, selected, edges

    def insert_summary(self, summary):
        value = document(summary)
        if value['kind'] != 'summary' or not self._available(value):
            raise ValueError('Summary must retain available source evidence')
        value['variants'] = [{k: deepcopy(value[k]) for k in ('text', 'source_ids', 'first_seen_at', 'last_seen_at')}]
        self.store.upsert_node(value)

    def insert_member_edge(self, edge):
        value = document(edge)
        if value['relation'] != 'member_of':
            raise ValueError('Grouping may insert only member_of edges')
        self.store.upsert_edge(value)

    def assign_group(self, member_ids, summary_id):
        summary = self.store.get_node(summary_id)
        if summary is None or summary['kind'] != 'summary':
            raise ValueError('Group summary must exist before assigning members')
        for id in member_ids:
            node = self.store.get_node(id)
            if node is None or node.get('group_id') not in (None, summary_id):
                raise ValueError('Missing member or member belongs to another group')
        self.store.assign_group(member_ids, summary_id)

    def context_token_count(self, node_ids):
        # Match the fixture runtime's whitespace-token estimate.
        return sum(len(self._node(self.store.get_node(id)).text.split()) for id in node_ids)
