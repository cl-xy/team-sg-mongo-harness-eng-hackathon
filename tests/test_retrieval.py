"""Unit tests for bounded long-term memory retrieval."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
from typing import Any, Mapping, Sequence

from backend.memory.retrieval import RetrievalLimits, retrieve_context


NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def source(source_id: str, available_at: datetime = NOW) -> dict[str, Any]:
    return {"id": source_id, "available_at": available_at}


def node(
    node_id: str,
    *,
    kind: str = "pattern",
    text: str | None = None,
    source_ids: Sequence[str] = ("source-1",),
    status: str = "active",
    group_id: str | None = None,
    first_seen_at: datetime = NOW,
    last_seen_at: datetime = NOW,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "text": text or f"Details for {node_id}",
        "scope_key": "noise|Manhattan|10001",
        "source_ids": list(source_ids),
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "status": status,
        "group_id": group_id,
    }


def edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    *,
    relation: str = "related_to",
    source_ids: Sequence[str] = ("source-1",),
    weight: float = 1.0,
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source_id": source_id,
        "target_id": target_id,
        "relation": relation,
        "weight": weight,
        "source_ids": list(source_ids),
    }


class FakeRetrievalStore:
    def __init__(
        self,
        nodes: Sequence[Mapping[str, Any]],
        edges: Sequence[Mapping[str, Any]] = (),
        sources: Sequence[Mapping[str, Any]] = (),
        scores: Mapping[str, float] | None = None,
    ) -> None:
        self.nodes = {str(item["id"]): dict(item) for item in nodes}
        self.edges = [dict(item) for item in edges]
        self.sources = {str(item["id"]): dict(item) for item in sources}
        self.scores = dict(scores or {})
        self.retrieved: list[tuple[list[str], datetime]] = []
        self.search_calls: list[tuple[str, int, Mapping[str, Any]]] = []

    def search_memories(
        self, text: str, limit: int, filters: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        self.search_calls.append((text, limit, dict(filters)))
        matching = []
        for item in self.nodes.values():
            if item.get("status", "active") != filters.get("status", "active"):
                continue
            group_id = filters.get("group_id")
            if group_id is not None and item.get("group_id") != group_id:
                continue
            matching.append(item)
        matching.sort(key=lambda item: (-self.scores.get(item["id"], 0.0), item["id"]))
        return [
            {"node": item, "score": self.scores.get(item["id"], 0.0)}
            for item in matching[:limit]
        ]

    def get_memory_nodes(self, node_ids: Sequence[str]) -> list[dict[str, Any]]:
        return [self.nodes[node_id] for node_id in node_ids if node_id in self.nodes]

    def get_memory_edges(
        self, node_ids: Sequence[str], limit: int
    ) -> list[dict[str, Any]]:
        node_id_set = set(node_ids)
        matching = [
            item
            for item in self.edges
            if item["source_id"] in node_id_set or item["target_id"] in node_id_set
        ]
        matching.sort(key=lambda item: item["id"])
        return matching[:limit]

    def get_source_records(self, source_ids: Sequence[str]) -> list[dict[str, Any]]:
        return [self.sources[source_id] for source_id in source_ids if source_id in self.sources]

    def mark_nodes_retrieved(
        self, node_ids: Sequence[str], retrieved_at: datetime
    ) -> None:
        self.retrieved.append((list(node_ids), retrieved_at))


def store_for(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]] = (),
    sources: Sequence[Mapping[str, Any]] | None = None,
    scores: Mapping[str, float] | None = None,
) -> FakeRetrievalStore:
    if sources is None:
        source_ids = {source_id for item in nodes for source_id in item.get("source_ids", [])}
        source_ids.update(source_id for item in edges for source_id in item.get("source_ids", []))
        sources = [source(source_id) for source_id in sorted(source_ids)]
    return FakeRetrievalStore(nodes, edges, sources, scores)


class RetrievalTests(unittest.TestCase):
    def test_limits_reject_invalid_caps(self) -> None:
        with self.assertRaises(ValueError):
            RetrievalLimits(seed_limit=0)
        with self.assertRaises(ValueError):
            RetrievalLimits(max_context_tokens=0)

    def test_returns_top_vector_seeds_and_stable_order(self) -> None:
        nodes = [node("c"), node("b"), node("a")]
        store = store_for(nodes, scores={"a": 0.8, "b": 0.8, "c": 0.2})

        result = retrieve_context(
            "noise pattern", "session-1", NOW,
            RetrievalLimits(seed_limit=2, max_hops=0), store=store,
        )

        self.assertEqual(result.seed_ids, ["a", "b"])
        self.assertEqual([item.id for item in result.nodes], ["a", "b"])
        self.assertTrue(result.truncated)
        self.assertEqual(store.retrieved[0][0], ["a", "b"])
        self.assertIn("Sources: source-1", result.context_text)

    def test_expands_relevant_edges_but_not_location_only_edges_or_entities(self) -> None:
        nodes = [
            node("seed", source_ids=("source-1",)),
            node("related", source_ids=("source-2",)),
            node("location", kind="entity", source_ids=("source-3",)),
            node("other", source_ids=("source-4",)),
        ]
        edges = [
            edge("e1", "seed", "related", source_ids=("source-1",)),
            edge("e2", "seed", "location", relation="located_at", source_ids=("source-1",)),
            edge("e3", "location", "other", source_ids=("source-1",)),
        ]
        store = store_for(nodes, edges, scores={"seed": 0.95})

        result = retrieve_context(
            "noise pattern", "session-1", NOW,
            RetrievalLimits(seed_limit=1, max_hops=2), store=store,
        )

        self.assertEqual({item.id for item in result.nodes}, {"seed", "related"})
        self.assertEqual([item.id for item in result.edges], ["e1"])
        self.assertIn("source-2", result.source_ids)

    def test_summary_members_expand_only_for_detail_queries(self) -> None:
        nodes = [
            node("summary", kind="summary", text="Repeated noise pattern across one block."),
            node("member-1", text="Complaint from September 1", group_id="summary", source_ids=("source-2",)),
            node("member-2", text="Complaint from September 2", group_id="summary", source_ids=("source-3",)),
        ]
        edges = [
            edge("m1", "member-1", "summary", relation="member_of", source_ids=("source-2",)),
            edge("m2", "member-2", "summary", relation="member_of", source_ids=("source-3",)),
        ]
        store = store_for(nodes, edges, scores={"summary": 0.95, "member-1": 0.91, "member-2": 0.76})

        broad = retrieve_context(
            "summarize the recurring noise pattern", "session-1", NOW,
            RetrievalLimits(seed_limit=1, max_hops=2), store=store,
        )
        detail = retrieve_context(
            "which incidents support this pattern?", "session-1", NOW,
            RetrievalLimits(seed_limit=1, max_hops=2, max_members_per_summary=1), store=store,
        )

        self.assertEqual([item.id for item in broad.nodes], ["summary"])
        self.assertEqual({item.id for item in detail.nodes}, {"summary", "member-1"})
        self.assertIn("member-1", detail.context_text)
        self.assertNotIn("member-2", detail.context_text)

    def test_future_and_archived_evidence_are_excluded(self) -> None:
        future_time = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
        nodes = [
            node("future-source", source_ids=("future",)),
            node("future-node", first_seen_at=future_time, last_seen_at=future_time),
            node("archived", status="archived"),
            node("current", source_ids=("source-1",)),
        ]
        sources = [source("future", future_time), source("source-1", NOW)]
        store = store_for(nodes, sources=sources, scores={"future-source": 1.0, "future-node": 0.9, "archived": 0.8, "current": 0.7})

        result = retrieve_context(
            "noise pattern", "session-1", NOW,
            RetrievalLimits(seed_limit=2, max_hops=0), store=store,
        )

        self.assertEqual([item.id for item in result.nodes], ["current"])
        self.assertNotIn("future", result.source_ids)

    def test_token_cap_returns_empty_context_without_touching_nodes(self) -> None:
        store = store_for([node("seed", text="A long explanation that will exceed the budget.")])

        result = retrieve_context(
            "noise pattern", "session-1", NOW,
            RetrievalLimits(seed_limit=1, max_hops=0, max_context_tokens=1),
            store=store,
            token_counter=lambda text: len(text.split()),
        )

        self.assertEqual(result.nodes, [])
        self.assertEqual(result.context_text, "")
        self.assertEqual(result.token_count, 0)
        self.assertTrue(result.truncated)
        self.assertEqual(store.retrieved, [])

    def test_cycles_terminate_and_context_stays_within_caps(self) -> None:
        nodes = [node("a"), node("b"), node("c")]
        edges = [edge("ab", "a", "b"), edge("bc", "b", "c"), edge("ca", "c", "a")]
        store = store_for(nodes, edges, scores={"a": 0.9})
        limits = RetrievalLimits(seed_limit=1, max_hops=5, max_nodes=3, max_edges=2, max_context_tokens=300)

        result = retrieve_context(
            "noise pattern", "session-1", NOW, limits, store=store,
            token_counter=lambda text: len(text.split()),
        )

        self.assertLessEqual(len(result.nodes), limits.max_nodes)
        self.assertLessEqual(len(result.edges), limits.max_edges)
        self.assertLessEqual(result.token_count, limits.max_context_tokens)
        self.assertEqual(len({item.id for item in result.nodes}), len(result.nodes))

    def test_edge_without_available_provenance_is_not_returned(self) -> None:
        nodes = [node("a", source_ids=("source-1",)), node("b", source_ids=("source-2",))]
        edges = [edge("unverifiable", "a", "b", source_ids=())]
        store = store_for(nodes, edges, scores={"a": 0.9})

        result = retrieve_context(
            "noise pattern", "session-1", NOW,
            RetrievalLimits(seed_limit=1, max_hops=1), store=store,
        )

        self.assertEqual([item.id for item in result.nodes], ["a"])
        self.assertEqual(result.edges, [])


if __name__ == "__main__":
    unittest.main()
