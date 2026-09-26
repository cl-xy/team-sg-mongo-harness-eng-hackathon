"""Conservative equivalence decisions, canonical IDs and resumable graph writes."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime
import hashlib
import json
import math
from typing import Callable, Mapping

from backend.contracts import MergeResult
from .store import MemoryStore, utc, union_node


def plain(value):
    if hasattr(value, 'model_dump'):
        return plain(value.model_dump())
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, datetime):
        return utc(value).isoformat()
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def normalized(text):
    return ' '.join(text.casefold().split())


def identity_keys(node):
    # A timestamp distinguishes observations; recurring abstractions should be patterns.
    times = [node['first_seen_at'], node['last_seen_at']] if node['kind'] == 'fact' else []
    key = fingerprint([node['kind'], node['scope_key'], node.get('assertion'), normalized(node['text']), times])
    keys = ['text:' + key]
    if node['kind'] == 'entity' and nonblank(node.get('entity_key')):
        keys.append('entity:' + fingerprint([node['scope_key'], node['entity_key']]))
    return keys


class MergeEngine:
    def __init__(self, store: MemoryStore, search, judge: Callable | None = None):
        self.store, self.search, self.judge = store, search, judge

    def merge_graph(self, batch) -> MergeResult:
        batch = plain(batch)
        payload = {k: v for k, v in batch.items() if k != 'status'}
        digest = fingerprint(payload)
        existing = self.store.get_batch(batch['batch_id'])
        if existing and 'write_plan' in existing:
            if existing['fingerprint'] != digest:
                raise ValueError('Batch ID was reused with different content')
            if existing['status'] == 'committed':
                return MergeResult(**deepcopy(existing['result']))
            return self._apply(existing)
        pending = self.store.pending_batch_ids()
        if pending:
            raise RuntimeError('Recover pending merge before starting another batch: '+', '.join(pending))
        self._validate(batch)
        plan = self._plan(batch)
        plan.update(batch_id=batch['batch_id'], session_id=batch['session_id'],
                    as_of=utc(batch['as_of']), source_ids=batch['source_ids'],
                    status='pending', fingerprint=digest, nodes=batch['nodes'], edges=batch['edges'])
        self.store.save_plan(plan)
        return self._apply(plan)

    def _validate(self, batch):
        for field in ('batch_id', 'session_id'):
            if not nonblank(batch.get(field)):
                raise ValueError(f'{field} must be a nonempty string')
        as_of = utc(batch['as_of'])
        if len(batch['nodes']) > 100 or len(batch['edges']) > 500:
            raise ValueError('Demo merge limit: 100 nodes and 500 edges per batch')
        all_sources = set(batch['source_ids'])
        for id in all_sources:
            source = self.store.get_source(id)
            if source is None:
                raise ValueError(f'Missing source record: {id}')
            if utc(source['available_at']) > as_of or utc(source['occurred_at']) > as_of:
                raise ValueError('Source evidence is in the replay future')
        local_ids = set()
        for node in batch['nodes']:
            if not all(nonblank(node.get(k)) for k in ('id', 'text', 'scope_key')):
                raise ValueError('Nodes require nonempty IDs, text and scope keys')
            if node['id'] in local_ids:
                raise ValueError('Duplicate local node ID')
            local_ids.add(node['id'])
            if node['kind'] not in ('entity', 'fact', 'pattern', 'summary'):
                raise ValueError('Invalid memory kind')
            if node.get('status', 'active') != 'active':
                raise ValueError('Incoming memories must be active')
            if node.get('assertion') not in (None, 'observation', 'hypothesis'):
                raise ValueError('Invalid assertion label')
            if node['kind'] == 'entity' and node.get('assertion') is not None:
                raise ValueError('Entity nodes cannot make assertions')
            if not node['source_ids'] or not set(node['source_ids']) <= all_sources:
                raise ValueError('Node evidence must be nonempty and belong to the batch')
            if not utc(node['first_seen_at']) <= utc(node['last_seen_at']) <= as_of:
                raise ValueError('Invalid or future node time range')
        for edge in batch['edges']:
            if edge['source_id'] not in local_ids or edge['target_id'] not in local_ids:
                raise ValueError('Edges must reference local batch nodes')
            if not nonblank(edge['relation']) or not edge['source_ids'] or not set(edge['source_ids']) <= all_sources:
                raise ValueError('Edges require a relation and batch evidence')
            if not math.isfinite(edge['weight']) or edge['weight'] <= 0:
                raise ValueError('Edge weight must be finite and positive')

    def resume_batch(self, batch_id):
        """Resume durable decisions without needing the caller's original payload."""
        plan = self.store.get_batch(batch_id)
        if plan is None or 'write_plan' not in plan:
            raise ValueError('No durable write plan exists for this batch')
        return MergeResult(**deepcopy(plan['result'])) if plan['status'] == 'committed' else self._apply(plan)

    def _prepare(self, node):
        result = deepcopy(node)
        for field in ('first_seen_at', 'last_seen_at'):
            result[field] = utc(result[field])
        result.update(source_ids=sorted(set(node['source_ids'])), status='active',
                      retrieval_count=0, last_retrieved_at=None, group_id=None)
        result['identity_keys'] = identity_keys(result)
        result['variants'] = [{k: deepcopy(result[k]) for k in
                               ('text', 'source_ids', 'first_seen_at', 'last_seen_at', 'assertion') if k in result}]
        return result

    @staticmethod
    def _compatible(a, b):
        distinct_entities = (a['kind'] == b['kind'] == 'entity'
                             and nonblank(a.get('entity_key')) and nonblank(b.get('entity_key'))
                             and a['entity_key'] != b['entity_key'])
        return (not distinct_entities and a['kind'] == b['kind'] and a['scope_key'] == b['scope_key']
                and a.get('assertion') == b.get('assertion')
                and b['status'] == 'active')

    @staticmethod
    def _extends_group(candidate, other):
        # Summary refresh is deferred: retain new evidence outside its old group.
        return bool(other.get('group_id') and
                    set(candidate['source_ids']) - set(other['source_ids']))

    @staticmethod
    def _same_time(a, b):
        if a['kind'] != 'fact':
            return True
        return (utc(a['first_seen_at']) <= utc(b['last_seen_at'])
                and utc(b['first_seen_at']) <= utc(a['last_seen_at']))

    def _with_evidence(self, node):
        fields = ('id', 'kind', 'text', 'scope_key', 'entity_key', 'assertion', 'source_ids', 'first_seen_at', 'last_seen_at')
        result = {k: deepcopy(node[k]) for k in fields if k in node}
        result['evidence'] = [self.store.get_source(id) for id in node['source_ids']]
        return result

    def _decide(self, candidate, other, blocked, as_of, judgments=None):
        if other['id'] in blocked or not self._compatible(candidate, other):
            return 'new'
        if not self._available(other, as_of):
            return 'new'
        if set(candidate['identity_keys']) & set(other.get('identity_keys', identity_keys(other))):
            return 'related' if self._extends_group(candidate, other) else 'same'
        if self.judge is None:
            return 'new'
        relation = (judgments.get(other['id'], 'new') if judgments is not None else
                    self.judge(self._with_evidence(candidate), self._with_evidence(other)))
        if relation == 'same' and (not self._same_time(candidate, other)
                                   or self._extends_group(candidate, other)):
            return 'related'
        return relation if relation in ('same', 'related', 'contradictory', 'new') else 'new'

    def _available(self, node, as_of):
        if utc(node['last_seen_at']) > as_of or not node['source_ids']:
            return False
        for id in node['source_ids']:
            source = self.store.get_source(id)
            if source is None or utc(source['available_at']) > as_of or utc(source['occurred_at']) > as_of:
                return False
        return True

    def _plan(self, batch):
        id_map, writes, edges = {}, {}, {}
        created, updated = set(), set()
        as_of = utc(batch['as_of'])
        for raw in batch['nodes']:
            candidate = self._prepare(raw)
            blocked = set()
            for edge in batch['edges']:
                if edge['relation'] == 'contradicts' and raw['id'] in (edge['source_id'], edge['target_id']):
                    other_local = edge['target_id'] if raw['id'] == edge['source_id'] else edge['source_id']
                    if other_local in id_map:
                        blocked.add(id_map[other_local])
            candidates = {n['id']: n for n in self.store.exact_candidates(candidate)}
            for n in writes.values():
                if self._compatible(candidate, n):
                    candidates[n['id']] = n
            exact = [n for n in candidates.values() if self._compatible(candidate,n)
                     and n['id'] not in blocked and self._available(n, as_of)
                     and not self._extends_group(candidate, n)
                     and set(candidate['identity_keys']) & set(n.get('identity_keys',identity_keys(n)))]
            relations = []
            if exact:
                canonical = sorted(exact, key=lambda n:n['id'])[0]
            else:
                ranked = self.search.search_memories(candidate['text'], limit=5, filters={
                    'kind': candidate['kind'], 'scope_key': candidate['scope_key'],
                    'status': 'active', 'last_seen_at': {'$lte': as_of}})
                # Fetch canonical documents again: search indexes can be stale.
                for hit in ranked[:5]:
                    n = writes.get(hit['id']) or self.store.get_node(hit['id'])
                    if n: candidates[n['id']] = n
                for n in self.store.recent_candidates(candidate, 5):
                    candidates.setdefault(n['id'], n)
                local = [n for n in candidates.values() if self._compatible(candidate, n)
                         and n['id'] not in blocked and self._available(n, as_of)]
                # Keep every current-batch candidate and all five vector hits. The
                # production judge handles this set in one input/output-bounded call.
                local.sort(key=lambda n:(n['id'] not in writes, n['id']))
                judgments = None
                if self.judge is not None and hasattr(self.judge, 'classify_many'):
                    judgments = self.judge.classify_many(self._with_evidence(candidate),
                                                        [self._with_evidence(n) for n in local])
                canonical = None
                for other in local:
                    relation = self._decide(candidate, other, blocked, as_of, judgments)
                    if relation == 'same':
                        canonical = other
                        break
                    if relation in ('related', 'contradictory'):
                        relations.append((other, relation))
            if canonical is None:
                canonical_id = 'mem_' + fingerprint([batch['batch_id'], raw['id']])[:32]
                candidate['id'] = canonical_id
                writes[canonical_id] = candidate
                created.add(canonical_id)
            else:
                canonical_id = canonical['id']
                writes[canonical_id] = union_node(writes.get(canonical_id, canonical), candidate)
                if canonical_id not in created: updated.add(canonical_id)
            id_map[raw['id']] = canonical_id
            for other, relation in relations:
                self._edge(edges, canonical_id, other['id'],
                           'contradicts' if relation == 'contradictory' else 'related_to', 1.0,
                           candidate['source_ids'] + other['source_ids'])
        for edge in batch['edges']:
            self._edge(edges, id_map[edge['source_id']], id_map[edge['target_id']],
                       edge['relation'], edge['weight'], edge['source_ids'])
        result = dict(batch_id=batch['batch_id'], id_map=id_map, created_ids=sorted(created),
                      updated_ids=sorted(updated), edge_ids=sorted(edges), committed=True)
        return {'write_plan': {'nodes': list(writes.values()), 'edges': list(edges.values())}, 'result': result}

    @staticmethod
    def _edge(edges, source, target, relation, weight, sources):
        if source == target:
            return
        if relation in ('related_to', 'contradicts'):
            source, target = sorted([source, target])
        id = 'edge_' + fingerprint([source, target, relation])[:32]
        previous = edges.get(id, {})
        edges[id] = dict(id=id, source_id=source, target_id=target, relation=relation,
                         weight=max(weight, previous.get('weight', 0)),
                         source_ids=sorted(set(sources) | set(previous.get('source_ids', []))))

    def _apply(self, plan):
        for node in plan['write_plan']['nodes']:
            self.store.upsert_node(node)
        for edge in plan['write_plan']['edges']:
            self.store.upsert_edge(edge)
        self.store.commit_batch(plan['batch_id'])
        return MergeResult(**deepcopy(plan['result']))


_engine: MergeEngine | None = None


def configure_merge(store, search, judge=None):
    """Call once at harness startup; dependency injection keeps agent tools simple."""
    global _engine
    _engine = MergeEngine(store, search, judge)


def merge_graph(batch) -> MergeResult:
    if _engine is None:
        raise RuntimeError('Call configure_merge(store, search, judge) at startup')
    return _engine.merge_graph(batch)
