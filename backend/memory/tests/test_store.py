import unittest
from datetime import datetime, timezone

try:
    import mongomock
except ImportError:
    mongomock = None

from backend.memory.merge import MergeEngine
from backend.memory.store import MongoMemoryStore
from test_merge import TIME, batch, node


class EmptySearch:
    def search_memories(self, *args, **kwargs): return []


@unittest.skipUnless(mongomock, 'Install backend/memory/requirements-dev.txt for Mongo adapter tests')
class MongoStoreTests(unittest.TestCase):
    def setUp(self):
        self.database = mongomock.MongoClient(tz_aware=True)['memory_test']
        self.store = MongoMemoryStore(self.database)
        self.store.ensure_indexes()
        for id in ('s1','s2'):
            self.store.put_source(dict(id=id, text='Evidence '+id,
                                       occurred_at=TIME, available_at=TIME, metadata={}))

    def test_real_update_operators_preserve_counters_and_union_sources(self):
        engine=MergeEngine(self.store,EmptySearch(),judge=lambda a,b:'same')
        first=engine.merge_graph(batch())
        id=first.id_map['n1']
        self.store.nodes.update_one({'id':id},{'$set':{'retrieval_count':7}})
        second=batch([node('n2','Paraphrase','s2')],id='b2')
        engine.merge_graph(second)
        engine.merge_graph(second)
        saved=self.store.get_node(id)
        self.assertEqual(saved['source_ids'],['s1','s2'])
        self.assertEqual(saved['retrieval_count'],7)
        self.assertIsNone(saved['group_id'])
        self.assertEqual(len(saved['variants']),2)

    def test_pending_plan_survives_store_and_engine_reconstruction(self):
        engine=MergeEngine(self.store,EmptySearch(),judge=lambda a,b:'related')
        b=batch([node(),node('n2','Garbage','s2')])
        original=self.store.upsert_edge
        def failed(edge):
            original(edge)
            raise RuntimeError('Crash after edge write')
        self.store.upsert_edge=failed
        with self.assertRaises(RuntimeError): engine.merge_graph(b)
        fresh=MongoMemoryStore(self.database)
        result=MergeEngine(fresh,EmptySearch()).merge_graph(b)
        self.assertTrue(result.committed)
        self.assertEqual(fresh.nodes.count_documents({}),2)
        self.assertEqual(fresh.edges.count_documents({}),1)
        edge=fresh.edges.find_one()
        self.assertEqual(edge['weight'],1)
        self.assertEqual(edge['source_ids'],['s1','s2'])

    def test_ingestion_pending_batch_can_be_planned(self):
        self.store.batches.insert_one(batch())
        self.assertTrue(MergeEngine(self.store,EmptySearch()).merge_graph(batch()).committed)

    def test_source_replay_is_stable_at_bson_millisecond_precision(self):
        time=datetime(2026,9,1,12,0,0,123456,tzinfo=timezone.utc)
        source=dict(id='microsecond-source',text='original',occurred_at=time,available_at=time,metadata={})
        self.store.put_source(source)
        self.store.put_source(source)
        self.assertEqual(self.store.sources.count_documents({'id':source['id']}),1)

    def test_entity_and_source_indexes_exist_and_ids_are_unique(self):
        indexes=self.store.nodes.index_information()
        self.assertTrue(indexes['id_1']['unique'])
        self.assertIn('source_ids_1',indexes)
        self.assertIn('identity_keys_1',indexes)
        for field in ['source_id','target_id']:
            self.assertIn(field+'_1',self.store.edges.index_information())

    def test_resume_by_id_needs_no_original_in_process_batch(self):
        engine=MergeEngine(self.store,EmptySearch())
        self.store.upsert_node=lambda n: (_ for _ in ()).throw(RuntimeError('crash'))
        b=batch()
        b['as_of']='2026-09-01T12:00:00.123456Z'
        with self.assertRaises(RuntimeError): engine.merge_graph(b)
        fresh=MongoMemoryStore(self.database)
        engine=MergeEngine(fresh,EmptySearch())
        result=engine.resume_batch('b1')
        self.assertTrue(result.committed)
        self.assertEqual(engine.resume_batch('b1'),result)


if __name__=='__main__': unittest.main()
