"""Wire Jiacheng's persistence into the existing harness without replacing it."""
from dataclasses import replace
from datetime import datetime, timezone

from backend.contracts import GroupingLimits
from .merge import MergeEngine
from .store import GroupingStoreAdapter


class MemoryHarnessServices:
    """Inject the team's extraction, retrieval, recommendation and summary callbacks.

    No model, retrieval stub or database fallback is selected implicitly. Callers
    can supply Atlas adapters or explicitly chosen fixture implementations.
    """
    def __init__(self, store, search, *, extract, retrieve, recommend, build_summary,
                 judge=None, grouping_limits=None):
        self.store = store
        self.engine = MergeEngine(store, search, judge)
        self._extract, self._retrieve, self._recommend = extract, retrieve, recommend
        self.build_summary = build_summary
        self.grouping_limits = grouping_limits or GroupingLimits()
        self.grouping_store = GroupingStoreAdapter(
            store, as_of=datetime.min.replace(tzinfo=timezone.utc),
            max_snapshot_nodes=self.grouping_limits.max_snapshot_nodes)
        # MongoMemoryStore uses the same adapter for explicit document embeddings.
        if hasattr(store, 'search'):
            store.search = search if getattr(search, 'mode', None) == 'explicit' else None

    def ingest(self, records):
        if self.store.pending_batch_ids():
            raise RuntimeError('Resume pending merges before starting another harness step')
        for record in records:
            self.store.put_source(record)
        self.grouping_store.as_of = max(record.available_at for record in records)

    def extract(self, records, session_id):
        batch = self._extract(records, session_id)
        # Xinyi's extractor currently stamps occurrence time. The harness uses
        # availability time; preserve observed node dates and align only the batch clock.
        return replace(batch, as_of=max(record.available_at for record in records))

    def merge(self, batch):
        return self.engine.merge_graph(batch)

    def retrieve(self, query, session_id, as_of):
        return self._retrieve(query, session_id, as_of)

    def recommend(self, records, context):
        return self._recommend(records, context)
