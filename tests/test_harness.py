from datetime import datetime, timezone
import unittest

from backend.contracts import (
    GroupingLimits,
    MemoryEdge,
    MemoryNode,
    MergeResult,
    RetrievedContext,
    SourceRecord,
)
from backend.harness import run_step
from backend.memory.grouping import group_oversized_clusters


NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, nodes, edges):
        self.nodes = list(nodes)
        self.edges = list(edges)

    def graph_snapshot(self):
        return 'snapshot-1', self.nodes, self.edges

    def insert_summary(self, summary):
        self.nodes.append(summary)

    def insert_member_edge(self, edge):
        self.edges.append(edge)

    def assign_group(self, member_ids, summary_id):
        for node in self.nodes:
            if node.id in member_ids:
                node.group_id = summary_id

    def context_token_count(self, node_ids):
        return len(node_ids)


def make_node(node_id):
    return MemoryNode(
        id=node_id,
        kind='fact',
        text=node_id,
        scope_key='311',
        source_ids=[f'source-{node_id}'],
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


class GroupingTests(unittest.TestCase):
    def test_groups_largest_eligible_community_and_retains_evidence(self):
        nodes = [make_node(f'a-{index}') for index in range(10)]
        nodes.extend(make_node(f'b-{index}') for index in range(9))
        edges = []
        for prefix, size in (('a', 10), ('b', 9)):
            for index in range(size):
                for other_index in range(index + 1, size):
                    edges.append(MemoryEdge(
                        id=f'{prefix}-edge-{index}-{other_index}',
                        source_id=f'{prefix}-{index}',
                        target_id=f'{prefix}-{other_index}',
                        relation='related_to',
                        weight=1,
                    ))
        store = FakeStore(nodes, edges)

        result = group_oversized_clusters(
            store, NOW, GroupingLimits(), lambda members: 'summary text',
        )

        self.assertEqual(result.eligible_sizes, [10, 9])
        self.assertEqual(result.selected_member_ids, [f'a-{index}' for index in range(10)])
        summary = next(node for node in store.nodes if node.id == result.summary_id)
        self.assertEqual(len(summary.source_ids), 10)
        self.assertEqual(result.context_tokens_before, 19)
        self.assertEqual(result.context_tokens_after, 10)

    def test_edgeless_nodes_are_not_grouped(self):
        store = FakeStore([make_node(f'node-{index}') for index in range(9)], [])

        result = group_oversized_clusters(
            store, NOW, GroupingLimits(), lambda members: 'unreachable',
        )

        self.assertIsNone(result.summary_id)
        self.assertEqual(len(result.communities), 9)


class HarnessTests(unittest.TestCase):
    def test_baseline_skips_memory_services(self):
        class Services:
            def __init__(self):
                self.calls = []

            def ingest(self, records):
                self.calls.append('ingest')

            def extract(self, records, session_id):
                self.calls.append('extract')

            def merge(self, batch):
                self.calls.append('merge')

            def retrieve(self, query, session_id, as_of):
                self.calls.append('retrieve')

            def recommend(self, records, context):
                self.calls.append('recommend')
                return {'ok': True}

        services = Services()
        record = SourceRecord('record-1', 'complaint', NOW, NOW)

        events = run_step([record], 'baseline', services)

        self.assertEqual(services.calls, ['ingest', 'recommend'])
        self.assertEqual([event.type for event in events], ['ingested', 'recommended'])


if __name__ == '__main__':
    unittest.main()
