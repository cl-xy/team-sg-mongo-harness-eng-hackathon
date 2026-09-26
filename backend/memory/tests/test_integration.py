"""Exercise the pulled extraction/contracts/harness against Jiacheng's modules."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from functools import partial
import unittest

import mongomock

from backend.contracts import GraphBatch, GroupingLimits, MemoryNode, MergeResult, RetrievedContext, SourceRecord
from backend.extraction import extract_concepts
from backend.harness import run_step
from backend.memory.merge import MergeEngine
from backend.memory.store import InMemoryStore, MongoMemoryStore
from backend.memory.grouping import group_oversized_clusters


NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


class EmptySearch:
    def search_memories(self, *args, **kwargs): return []


def source(id='s1', available_at=NOW):
    return SourceRecord(id, 'Reported loud music', NOW, available_at,
                        {'location': {'coordinates': [-73.9, 40.7]}})


def extracted_payload(request):
    nodes = []
    for record in request['records']:
        nodes.append(dict(id='fact-'+record['id'], kind='fact', text=record['text'],
                          scope_key=record['source_block_key'], source_ids=[record['id']],
                          assertion='observation'))
    edges = [dict(id=f'e-{i}', source_id=nodes[i]['id'], target_id=nodes[i+1]['id'],
                  relation='related_to', weight=1, source_ids=nodes[i]['source_ids']+nodes[i+1]['source_ids'])
             for i in range(len(nodes)-1)]
    return {'nodes': nodes, 'edges': edges}


class ContractIntegrationTests(unittest.TestCase):
    def test_new_evidence_for_grouped_pattern_stays_separate_and_related(self):
        for wording in ['Recurring loud music', 'Repeated amplified sound']:
            store = InMemoryStore()
            for record in [source('s1'), source('s2')]:
                store.put_source(record)
            engine = MergeEngine(store, EmptySearch(), judge=lambda a, b: 'same')
            first = MemoryNode('p', 'pattern', 'Recurring loud music', 'location:x', ['s1'], NOW, NOW)
            result = engine.merge_graph(GraphBatch('old', 'session', NOW, [first], [], ['s1']))
            old_id = result.id_map['p']
            store.assign_group([old_id], 'summary')
            second = MemoryNode('p', 'pattern', wording, 'location:x', ['s2'], NOW, NOW)
            result = engine.merge_graph(GraphBatch('new', 'session', NOW, [second], [], ['s2']))
            self.assertNotEqual(old_id, result.id_map['p'])
            self.assertEqual(store.get_node(old_id)['source_ids'], ['s1'])
            self.assertIsNone(store.get_node(result.id_map['p'])['group_id'])
            self.assertEqual(next(iter(store.edges.values()))['relation'], 'related_to')

    def test_public_engine_returns_shared_merge_result_for_shared_batch(self):
        store=InMemoryStore()
        store.put_source(asdict(source()))
        n=MemoryNode('local','fact','Reported loud music','source:s1',['s1'],NOW,NOW)
        b=GraphBatch('b','session',NOW,[n],[],['s1'])
        result=MergeEngine(store,EmptySearch()).merge_graph(b)
        self.assertIsInstance(result,MergeResult)
        self.assertTrue(result.committed)
        self.assertIn('local',result.id_map)

    def test_both_stores_accept_shared_and_extraction_source_dataclasses(self):
        from backend.extraction.types import SourceRecord as ExtractionSource
        for store in [InMemoryStore(),MongoMemoryStore(mongomock.MongoClient(tz_aware=True).db)]:
            with self.subTest(store=type(store).__name__):
                store.put_source(source())
                store.put_source(ExtractionSource(**asdict(source())))
                self.assertEqual(store.get_source('s1')['id'],'s1')

    def test_extraction_assertions_cannot_merge_through_exact_identity_or_judge(self):
        for text in ['Reported loud music','Possible loud music']:
            store=InMemoryStore(); store.put_source(asdict(source()))
            data=extracted_payload({'records':[dict(id='s1',text='Reported loud music',source_block_key='source:s1')]})
            other=dict(data['nodes'][0],id='hypothesis',text=text,assertion='hypothesis')
            data['nodes'].append(other)
            b=extract_concepts([source()],'session',extractor=lambda _:data)
            engine=MergeEngine(store,EmptySearch(),judge=lambda a,b:'same')
            engine.merge_graph(b)
            self.assertEqual(len(store.nodes),2)
            self.assertEqual({n['assertion'] for n in store.nodes.values()},{'observation','hypothesis'})

    def test_assertion_label_is_passed_to_identity_judge_and_retained_in_variants(self):
        store=InMemoryStore(); store.put_source(asdict(source()))
        data=extracted_payload({'records':[dict(id='s1',text='Reported loud music',source_block_key='source:s1')]})
        data['nodes'].append(dict(data['nodes'][0],id='paraphrase',text='Amplified sound'))
        def judge(a,b):
            self.assertEqual(a['assertion'],'observation')
            self.assertEqual(b['assertion'],'observation')
            return 'same'
        b=extract_concepts([source()],'session',extractor=lambda _:data)
        MergeEngine(store,EmptySearch(),judge=judge).merge_graph(b)
        variants=next(iter(store.nodes.values()))['variants']
        self.assertEqual({v['assertion'] for v in variants},{'observation'})

    def test_different_source_blocks_stay_separate_with_same_wording_and_time(self):
        store=InMemoryStore()
        records=[source('s1'),source('s2')]
        for r in records: store.put_source(asdict(r))
        b=extract_concepts(records,'session',extractor=extracted_payload)
        MergeEngine(store,EmptySearch(),judge=lambda a,b:'same').merge_graph(b)
        self.assertEqual(len(store.nodes),2)
        self.assertEqual({n['scope_key'] for n in store.nodes.values()},{'source:s1','source:s2'})

    def test_same_location_patterns_can_merge_across_source_blocks(self):
        store=InMemoryStore()
        records=[source('s1'),source('s2')]
        for r in records: store.put_source(asdict(r))
        payload={'nodes':[dict(id='p'+r.id,kind='pattern',text='Recurring loud music',
                               scope_key='location:point:-73.9,40.7',source_ids=[r.id],assertion='observation')
                          for r in records],'edges':[]}
        b=extract_concepts(records,'session',extractor=lambda _:payload)
        MergeEngine(store,EmptySearch()).merge_graph(b)
        self.assertEqual(len(store.nodes),1)
        self.assertEqual(next(iter(store.nodes.values()))['source_ids'],['s1','s2'])


class HarnessIntegrationTests(unittest.TestCase):
    def services(self,store):
        from backend.memory.services import MemoryHarnessServices
        return MemoryHarnessServices(
            store,EmptySearch(),extract=partial(extract_concepts,extractor=extracted_payload),
            retrieve=lambda *args:RetrievedContext([],[],[],[],'',0,False),
            recommend=lambda records,context:{'is_hypothesis':True,'sources':[r.id for r in records]},
            build_summary=lambda nodes:'Related reports',grouping_limits=GroupingLimits(grouping_threshold=2),
        )

    def test_real_extractor_merge_and_grouping_work_through_pulled_harness(self):
        for store in [InMemoryStore(),MongoMemoryStore(mongomock.MongoClient(tz_aware=True).db)]:
            with self.subTest(store=type(store).__name__):
                if isinstance(store,MongoMemoryStore): store.ensure_indexes()
                services=self.services(store)
                records=[source(str(i)) for i in range(3)]
                events=run_step(records,'memory',services)
                errors=[e.payload for e in events if e.type=='error']
                self.assertFalse(errors,errors)
                self.assertEqual([e.type for e in events],
                                 ['ingested','retrieved','extracted','merged','clustered','grouped','recommended'])
                group=next(e for e in events if e.type=='grouped').payload
                summary=store.get_node(group['summary_id'])
                self.assertEqual(summary['source_ids'],['0','1','2'])
                for id in group['member_ids']:
                    self.assertEqual(store.get_node(id)['group_id'],group['summary_id'])
                repeated=run_step(records,'memory',services)
                self.assertNotIn('error',[e.type for e in repeated])
                self.assertNotIn('grouped',[e.type for e in repeated])

    def test_delayed_source_uses_harness_availability_clock_without_weakening_merge(self):
        store=InMemoryStore()
        services=self.services(store)
        record=source(available_at=NOW+timedelta(days=1))
        events=run_step([record],'memory',services)
        errors=[e.payload for e in events if e.type=='error']
        self.assertFalse(errors,errors)
        checkpoint=next(iter(store.batches.values()))
        self.assertEqual(checkpoint['as_of'],record.available_at)

    def test_grouping_snapshot_excludes_future_evidence_and_labels_hypotheses(self):
        from backend.memory.store import GroupingStoreAdapter
        store=InMemoryStore()
        for id,available in [('past',NOW),('future',NOW+timedelta(days=1))]:
            store.put_source(asdict(source(id,available)))
            n=asdict(MemoryNode(id,'fact','Possible source of noise','location:x',[id],NOW,NOW))
            n['assertion']='hypothesis'
            store.upsert_node(n)
        snapshot=GroupingStoreAdapter(store,as_of=NOW)
        _,nodes,_=snapshot.graph_snapshot()
        self.assertEqual([n.id for n in nodes],['past'])
        self.assertIn('hypothesis',nodes[0].text.lower())

    def test_pending_merge_cannot_be_grouped(self):
        from backend.memory.store import GroupingStoreAdapter
        store=InMemoryStore()
        store.batches['b']={'status':'pending','write_plan':{}}
        with self.assertRaises(RuntimeError): GroupingStoreAdapter(store,as_of=NOW).graph_snapshot()

    def test_snapshot_limit_is_reported_by_existing_grouping_function(self):
        from backend.memory.store import GroupingStoreAdapter
        for store in [InMemoryStore(),MongoMemoryStore(mongomock.MongoClient(tz_aware=True).db)]:
            for i in range(5):
                record=source(str(i)); store.put_source(record)
                store.upsert_node(asdict(MemoryNode(str(i),'fact',record.text,'source:'+str(i),[str(i)],NOW,NOW)))
            adapter=GroupingStoreAdapter(store,as_of=NOW,max_snapshot_nodes=2)
            _,nodes,_=adapter.graph_snapshot()
            self.assertEqual(len(nodes),3)  # one sentinel makes truncation visible
            result=group_oversized_clusters(adapter,NOW,GroupingLimits(max_snapshot_nodes=2),lambda _: 'unused')
            self.assertTrue(result.truncated)
            self.assertEqual(sum(map(len,result.communities)),2)

    def test_future_edge_evidence_cannot_group_past_nodes(self):
        from backend.memory.store import GroupingStoreAdapter
        store=InMemoryStore()
        for i in range(3):
            record=source(str(i)); store.put_source(record)
            store.upsert_node(asdict(MemoryNode(str(i),'fact',record.text,'source:'+str(i),[str(i)],NOW,NOW)))
        store.put_source(source('future',available_at=NOW+timedelta(days=1)))
        for i in range(2):
            store.upsert_edge(dict(id=str(i),source_id=str(i),target_id=str(i+1),relation='related_to',
                                   weight=1,source_ids=['future']))
        adapter=GroupingStoreAdapter(store,as_of=NOW)
        _,_,edges=adapter.graph_snapshot()
        self.assertEqual(edges,[])
        result=group_oversized_clusters(adapter,NOW,GroupingLimits(grouping_threshold=2),lambda _: 'not yet known')
        self.assertIsNone(result.summary_id)

    def test_real_bounded_311_fixture_replays_through_integration(self):
        import json
        from pathlib import Path
        from backend.ingestion import source_record_from_311, recurring_311_slice
        rows=json.loads((Path(__file__).resolve().parents[3]/'fixtures/nyc_311_small.json').read_text())
        records=recurring_311_slice([source_record_from_311(row) for row in rows])
        self.assertGreaterEqual(len(records),2)
        store=InMemoryStore(); services=self.services(store)
        for offset in range(0,len(records),10):
            events=run_step(records[offset:offset+10],'memory',services)
            errors=[e.payload for e in events if e.type=='error']
            self.assertFalse(errors,errors)
        self.assertEqual(len(store.sources),len(records))


if __name__=='__main__': unittest.main()
