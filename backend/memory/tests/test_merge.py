import copy
import unittest

from backend.memory.merge import MergeEngine, fingerprint
from backend.memory.store import InMemoryStore


TIME = '2026-09-01T12:00:00+00:00'


def node(id='n1', text='Loud music at 10 Main Street', source='s1', **extra):
    return dict(id=id, kind='fact', text=text, scope_key='NYC:QUEENS:10 MAIN ST',
                source_ids=[source], first_seen_at=TIME, last_seen_at=TIME,
                last_retrieved_at=None, retrieval_count=0, status='active',
                group_id=None, **extra)


def batch(nodes=None, edges=None, id='b1'):
    nodes = nodes if nodes is not None else [node()]
    return dict(batch_id=id, session_id='session1', as_of=TIME, nodes=nodes,
                edges=edges or [], source_ids=sorted({s for n in nodes for s in n['source_ids']}),
                status='pending')


class Search:
    def __init__(self, store):
        self.store, self.calls = store, []

    def search_memories(self, text, limit, filters):
        self.calls.append((text, limit, filters))
        return [dict(n, score=.99) for n in self.store.nodes.values()][:limit]


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryStore()
        for s in ['s1', 's2', 's3', 's4']:
            self.store.put_source(dict(id=s, text='Original complaint '+s,
                                       occurred_at=TIME, available_at=TIME, metadata={}))
        self.search = Search(self.store)

    def engine(self, judge=None):
        return MergeEngine(self.store, self.search, judge=judge)

    def test_replay_is_idempotent_and_returns_original_result(self):
        b = batch()
        engine = self.engine()
        first = engine.merge_graph(b)
        snapshot = copy.deepcopy(self.store.nodes)
        self.assertEqual(engine.merge_graph(b), first)
        self.assertEqual(self.store.nodes, snapshot)
        self.assertTrue(first.committed)
        self.assertEqual(len(first.created_ids), 1)

    def test_paraphrase_merges_before_vector_index_sees_new_node(self):
        class LaggingSearch:
            def search_memories(self, *args, **kwargs): return []
        second = node('n2', 'Amplified music is disturbing residents', 's2')
        engine = MergeEngine(self.store, LaggingSearch(), judge=lambda a,b: 'same')
        result = engine.merge_graph(batch([node(), second]))
        self.assertEqual(result.id_map['n1'], result.id_map['n2'])
        saved = next(iter(self.store.nodes.values()))
        self.assertEqual(saved['source_ids'], ['s1', 's2'])
        self.assertEqual(len(saved['variants']), 2)

    def test_different_locations_cannot_merge_even_if_judge_says_same(self):
        other = node('n2', source='s2')
        other['scope_key'] = 'NYC:QUEENS:20 MAIN ST'
        result = self.engine(lambda a,b: 'same').merge_graph(batch([node(), other]))
        self.assertNotEqual(result.id_map['n1'], result.id_map['n2'])

    def test_conflict_keeps_both_nodes_and_cited_edge(self):
        other = node('n2', 'No music was audible at 10 Main Street', 's2')
        result = self.engine(lambda a,b:'contradictory').merge_graph(batch([node(), other]))
        self.assertEqual(len(self.store.nodes), 2)
        edge = self.store.edges[result.edge_ids[0]]
        self.assertEqual(edge['relation'], 'contradicts')
        self.assertEqual(edge['source_ids'], ['s1','s2'])

    def test_explicit_conflict_overrides_judge_and_exact_text(self):
        other = node('n2', source='s2')
        edge = dict(id='e', source_id='n1', target_id='n2', relation='contradicts',
                    weight=1, source_ids=['s1','s2'])
        self.engine(lambda a,b:'same').merge_graph(batch([node(),other],[edge]))
        self.assertEqual(len(self.store.nodes), 2)
        self.assertEqual(len(self.store.edges), 1)

    def test_shared_source_does_not_merge_different_assertions(self):
        other = node('n2', 'Garbage blocks the entrance')
        self.engine().merge_graph(batch([node(), other]))
        self.assertEqual(len(self.store.nodes), 2)

    def test_separate_dates_are_not_identical_observations(self):
        other = node('n2', source='s2')
        other['first_seen_at'] = other['last_seen_at'] = '2026-08-31T12:00:00Z'
        self.engine(lambda a,b:'same').merge_graph(batch([node(),other]))
        self.assertEqual(len(self.store.nodes), 2)

    def test_exact_entity_key_merges_paraphrase_without_model(self):
        a,b = node(entity_key='building:10'),node('n2','10 Main St building','s2',entity_key='building:10')
        a['kind'] = b['kind'] = 'entity'
        self.engine().merge_graph(batch([a,b]))
        self.assertEqual(len(self.store.nodes),1)

    def test_unknown_judgment_preserves_both_nodes(self):
        self.engine(lambda a,b:'maybe').merge_graph(batch([node(),node('n2','A paraphrase','s2')]))
        self.assertEqual(len(self.store.nodes), 2)

    def test_related_creates_edge_without_merging_and_remaps_input_edges(self):
        other = node('n2','Waste outside noisy building','s2')
        edge = dict(id='local',source_id='n1',target_id='n2',relation='located_at',weight=2,source_ids=['s1'])
        result = self.engine(lambda a,b:'related').merge_graph(batch([node(),other],[edge]))
        self.assertEqual(len(self.store.nodes),2)
        self.assertEqual({e['relation'] for e in self.store.edges.values()},{'related_to','located_at'})
        for e in self.store.edges.values():
            self.assertIn(e['source_id'],self.store.nodes)
            self.assertIn(e['target_id'],self.store.nodes)
        self.assertEqual(len(result.edge_ids),2)

    def test_dangling_edge_and_missing_source_fail_before_writes(self):
        b=batch(edges=[dict(id='e',source_id='n1',target_id='missing',relation='related_to',weight=1,source_ids=['s1'])])
        with self.assertRaises(ValueError): self.engine().merge_graph(b)
        with self.assertRaises(ValueError): self.engine().merge_graph(batch([node(source='missing')]))
        self.assertFalse(self.store.nodes)
        self.assertFalse(self.store.batches)

    def test_future_evidence_and_naive_timestamps_rejected(self):
        self.store.sources['s1']['available_at']='2026-09-02T00:00:00Z'
        with self.assertRaises(ValueError): self.engine().merge_graph(batch())
        self.store.sources['s1']['available_at']=TIME
        b=batch(); b['as_of']='2026-09-01T12:00:00'
        with self.assertRaises(ValueError): self.engine().merge_graph(b)

    def test_changed_payload_cannot_reuse_batch_id(self):
        self.engine().merge_graph(batch())
        with self.assertRaises(ValueError):
            self.engine().merge_graph(batch([node(text='Changed')]))

    def test_recovery_reuses_checkpoint_without_rerunning_model(self):
        b=batch([node(),node('n2','A paraphrase','s2')])
        original=self.store.upsert_node
        def fail_after_write(n):
            original(n)
            raise RuntimeError('simulated process failure after acknowledged write')
        self.store.upsert_node=fail_after_write
        with self.assertRaises(RuntimeError): self.engine(lambda a,b:'same').merge_graph(b)
        self.assertEqual(self.store.batches['b1']['status'],'pending')
        self.store.upsert_node=original
        def no_calls(*args): self.fail('Recovery must not replan')
        result=self.engine(no_calls).merge_graph(b)
        self.assertTrue(result.committed)
        self.assertEqual(len(self.store.nodes),1)
        self.assertEqual(next(iter(self.store.nodes.values()))['source_ids'],['s1','s2'])

    def test_index_lag_across_batches_uses_recent_durable_candidates(self):
        class LaggingSearch:
            def search_memories(self,*args,**kwargs): return []
        engine=MergeEngine(self.store,LaggingSearch(),judge=lambda a,b:'same')
        first=engine.merge_graph(batch())
        second=engine.merge_graph(batch([node('n2','Equivalent paraphrase','s2')],id='b2'))
        self.assertEqual(first.id_map['n1'],second.id_map['n2'])

    def test_overlapping_new_batch_is_blocked_until_pending_plan_recovers(self):
        original=self.store.upsert_node
        self.store.upsert_node=lambda n: (_ for _ in ()).throw(RuntimeError('failure'))
        with self.assertRaises(RuntimeError): self.engine().merge_graph(batch())
        self.store.upsert_node=original
        with self.assertRaises(RuntimeError): self.engine().merge_graph(batch(id='b2'))

    def test_old_occurrence_with_later_available_evidence_is_not_merged_or_shown_to_model(self):
        self.store.sources['s2']['available_at'] = '2026-09-02T12:00:00Z'
        future = batch([node('future', source='s2')], id='future-batch')
        future['as_of'] = '2026-09-03T00:00:00Z'
        self.engine().merge_graph(future)
        def no_calls(candidate, existing):
            self.assertNotIn('s2', existing['source_ids'], 'Future evidence must not reach the identity judge')
            return 'new'
        self.engine(no_calls).merge_graph(batch())
        self.assertEqual(len(self.store.nodes), 2)
        self.engine(no_calls).merge_graph(batch([node('earlier','A different assertion','s3')],id='earlier'))

    def test_missing_evidence_on_existing_node_is_not_used_as_identity(self):
        self.engine().merge_graph(batch([node(source='s2')],id='existing'))
        del self.store.sources['s2']
        self.engine().merge_graph(batch())
        self.assertEqual(len(self.store.nodes),2)

    def test_distinct_explicit_entity_keys_override_identical_labels(self):
        a = node(entity_key='building:10')
        b = node('n2',source='s2',entity_key='building:20')
        a['kind'] = b['kind'] = 'entity'
        self.engine(lambda a,b:'same').merge_graph(batch([a,b]))
        self.assertEqual(len(self.store.nodes),2)

    def test_all_current_batch_nodes_remain_semantic_candidates(self):
        nodes=[node(f'n{i}',f'Distinct assertion {i}') for i in range(11)]
        target=max(nodes,key=lambda n:fingerprint(['b1',n['id']])[:32])
        nodes.append(node('paraphrase','Reworded: '+target['text'],'s2'))
        def judge(a,b): return 'same' if a['text']=='Reworded: '+b['text'] else 'new'
        result=self.engine(judge).merge_graph(batch(nodes))
        self.assertEqual(result.id_map['paraphrase'],result.id_map[target['id']])
        self.assertEqual(len(self.store.nodes),11)

    def test_unplanned_ingestion_batch_is_not_a_writer_checkpoint(self):
        self.store.batches['b1']=batch()
        self.assertTrue(self.engine().merge_graph(batch()).committed)


if __name__=='__main__': unittest.main()
