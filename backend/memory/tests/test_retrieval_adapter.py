import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from backend.contracts import RetrievedContext as SharedRetrievedContext
from backend.memory.embeddings import AtlasMemorySearch
from backend.memory.retrieval import RetrievalLimits
from backend.memory.services import MemoryHarnessServices


NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


class Cursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def limit(self, count):
        return Cursor(self.documents[:count])

    def __iter__(self):
        return iter(self.documents)


class Collection:
    def __init__(self, documents):
        self.documents = list(documents)
        self.updates = []

    def find(self, query, projection=None):
        return Cursor([document for document in self.documents if _matches(document, query)])

    def update_many(self, query, update):
        self.updates.append((query, update))


def _matches(document, query):
    for key, value in query.items():
        if key == "$or":
            if not any(_matches(document, branch) for branch in value):
                return False
        elif isinstance(value, dict) and "$in" in value:
            if document.get(key) not in value["$in"]:
                return False
        elif document.get(key) != value:
            return False
    return True


class RetrievalAdapterTests(unittest.TestCase):
    def test_detail_retrieval_uses_indexed_group_id_filter_and_mongo_graph_reads(self):
        summary = {
            "id": "summary-1", "kind": "summary", "text": "Repeated noise reports",
            "scope_key": "noise|10001", "source_ids": ["source-summary"],
            "first_seen_at": NOW, "last_seen_at": NOW, "status": "active", "group_id": None,
        }
        member = {
            "id": "member-1", "kind": "pattern", "text": "Loud music on September 1",
            "scope_key": "noise|10001", "source_ids": ["source-member"],
            "first_seen_at": NOW, "last_seen_at": NOW, "status": "active", "group_id": "summary-1",
        }
        edge = {
            "id": "membership-1", "source_id": "member-1", "target_id": "summary-1",
            "relation": "member_of", "weight": 1.0, "source_ids": ["source-member"],
        }
        memory_store = SimpleNamespace(
            nodes=Collection([summary, member]),
            edges=Collection([edge]),
            sources=Collection([
                {"id": "source-summary", "available_at": NOW},
                {"id": "source-member", "available_at": NOW},
            ]),
        )
        vector_collection = Mock()
        vector_collection.aggregate.side_effect = [
            [{**summary, "score": 0.99}],
            [{**member, "score": 0.91}],
        ]
        vector_search = AtlasMemorySearch(vector_collection)
        services = MemoryHarnessServices(
            memory_store,
            vector_search,
            extract=lambda records, session_id: None,
            recommend=lambda records, context: {},
            build_summary=lambda members: "unused",
            retrieval_limits=RetrievalLimits(
                seed_limit=1, max_hops=2, max_members_per_summary=2
            ),
        )
        result = services.retrieve("which incidents support this pattern?", "session-1", NOW)

        self.assertIsInstance(result, SharedRetrievedContext)
        self.assertEqual({node.id for node in result.nodes}, {"summary-1", "member-1"})
        self.assertEqual([item.id for item in result.edges], ["membership-1"])
        member_search_stage = vector_collection.aggregate.call_args_list[1].args[0][0]["$vectorSearch"]
        self.assertEqual(member_search_stage["filter"]["group_id"], "summary-1")
        self.assertIn(
            {"type": "filter", "path": "group_id"},
            vector_search.index_definition()["fields"],
        )
        self.assertTrue(vector_search.index_name.endswith("_v2"))
        self.assertEqual(memory_store.nodes.updates[0][1]["$inc"], {"retrieval_count": 1})
        self.assertEqual(result.as_dict()["nodes"][0]["first_seen_at"], "2026-09-26T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
