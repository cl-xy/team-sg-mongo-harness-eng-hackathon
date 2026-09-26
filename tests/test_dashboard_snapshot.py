import unittest
from pathlib import Path

from scripts.dashboard_snapshot import build_snapshot
from scripts.run_harness import _load_records


class DashboardSnapshotTests(unittest.TestCase):
    def test_replay_is_chronological_and_comparison_is_isolated(self):
        records = _load_records(Path('fixtures/311-small.json'))
        result = build_snapshot(records, batch_size=20)
        self.assertEqual(result['record_count'], len(records))
        self.assertEqual(result['baseline']['historical_source_ids'], [])
        self.assertGreater(len(result['memory']['historical_source_ids']), 0)
        self.assertEqual(result['baseline']['text'], result['memory']['text'])
        source_by_id = {record.id: record for record in records}
        for batch in result['batches']:
            current_ids = set(batch['record_ids'])
            retrieval = next(event for event in batch['events'] if event['type'] == 'retrieved')
            self.assertFalse(current_ids.intersection(retrieval['payload']['source_ids']))
            for source_id in retrieval['payload']['source_ids']:
                self.assertLessEqual(source_by_id[source_id].available_at.isoformat(), batch['as_of'])
        self.assertTrue(any(node['kind'] == 'summary' for node in result['nodes']))
        self.assertEqual(len({node['id'] for node in result['nodes']}), len(result['nodes']))

    def test_empty_input_is_explicit(self):
        with self.assertRaisesRegex(ValueError, 'at least one'):
            build_snapshot([], batch_size=20)

    def test_invalid_batch_size_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'positive'):
            build_snapshot([], batch_size=0)
