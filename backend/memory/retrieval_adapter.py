"""Bridge the graph store and Atlas vector adapter to graph retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence


class MongoMemoryRetrievalStore:
    """Implement ``RetrievalStore`` over ``MongoMemoryStore`` collections.

    ``memory_store`` may be Jiacheng's ``MongoMemoryStore`` or a PyMongo
    ``Database``. ``vector_search`` is the shared ``AtlasMemorySearch`` instance
    used by the merge path. This adapter does not own clients or indexes.
    """

    def __init__(self, memory_store: Any, vector_search: Any) -> None:
        self.memory_store = memory_store
        self.vector_search = vector_search
        if all(hasattr(memory_store, name) for name in ("nodes", "edges", "sources")):
            self.nodes = memory_store.nodes
            self.edges = memory_store.edges
            self.sources = memory_store.sources
        else:
            self.nodes = memory_store["memory_nodes"]
            self.edges = memory_store["memory_edges"]
            self.sources = memory_store["source_records"]

    def search_memories(
        self, text: str, limit: int, filters: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]:
        return self.vector_search.search_memories(text, limit, dict(filters))

    def get_memory_nodes(self, node_ids: Sequence[str]) -> Sequence[Mapping[str, Any]]:
        if not node_ids:
            return []
        return list(
            self.nodes.find(
                {"id": {"$in": list(node_ids)}}, {"_id": 0}
            )
        )

    def get_memory_edges(
        self, node_ids: Sequence[str], limit: int
    ) -> Sequence[Mapping[str, Any]]:
        if not node_ids or limit <= 0:
            return []
        cursor = self.edges.find(
            {
                "$or": [
                    {"source_id": {"$in": list(node_ids)}},
                    {"target_id": {"$in": list(node_ids)}},
                ]
            },
            {"_id": 0},
        )
        return list(cursor.limit(limit))

    def get_source_records(
        self, source_ids: Sequence[str]
    ) -> Sequence[Mapping[str, Any]]:
        if not source_ids:
            return []
        return list(
            self.sources.find(
                {"id": {"$in": list(source_ids)}}, {"_id": 0}
            )
        )

    def mark_nodes_retrieved(
        self, node_ids: Sequence[str], retrieved_at: datetime
    ) -> None:
        if not node_ids:
            return
        self.nodes.update_many(
            {"id": {"$in": list(node_ids)}},
            {
                "$inc": {"retrieval_count": 1},
                "$set": {"last_retrieved_at": retrieved_at},
            },
        )
