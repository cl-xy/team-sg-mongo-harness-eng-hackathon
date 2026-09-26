import json
import unittest
from unittest.mock import Mock

from backend.memory.embeddings import AtlasMemorySearch, OpenRouterJudge, VoyageEmbeddings


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.collection=Mock()
        self.collection.aggregate.return_value=[{'id':'n','score':.7}]

    def test_automated_index_and_first_stage_text_query(self):
        search=AtlasMemorySearch(self.collection)
        self.assertEqual(search.index_definition()['fields'][0],
                         dict(type='autoEmbed',modality='text',path='text',model='voyage-4'))
        result=search.search_memories('noise',5,{'scope_key':'block1','kind':'fact'})
        stage=self.collection.aggregate.call_args.args[0][0]['$vectorSearch']
        self.assertEqual(stage['query'],{'text':'noise'})
        self.assertEqual(stage['filter']['status'],'active')
        self.assertEqual(stage['filter']['scope_key'],'block1')
        self.assertEqual(stage['limit'],5)
        self.assertNotIn('queryVector',stage)
        self.assertEqual(result,[{'id':'n','score':.7}])

    def test_group_id_is_an_indexed_vector_prefilter_for_summary_members(self):
        search=AtlasMemorySearch(self.collection)
        search.search_memories('which incidents support this?',5,{'group_id':'summary-1'})
        vector_stage=self.collection.aggregate.call_args.args[0][0]['$vectorSearch']
        self.assertEqual(vector_stage['filter']['group_id'],'summary-1')
        self.assertIn({'type':'filter','path':'group_id'},search.index_definition()['fields'])
        self.assertEqual(search.index_name,'memory_automated_v2')

    def test_explicit_mode_uses_voyage_query_and_document_types(self):
        voyage=Mock(); voyage.embed.return_value=[.1,.2,.3]
        search=AtlasMemorySearch(self.collection,mode='explicit',voyage=voyage,dimensions=3)
        search.search_memories('noise',5,{})
        voyage.embed.assert_called_with('noise','query')
        stage=self.collection.aggregate.call_args.args[0][0]['$vectorSearch']
        self.assertEqual(stage['queryVector'],[.1,.2,.3])
        self.assertNotIn('query',stage)
        self.assertEqual(search.index_definition()['fields'][0]['numDimensions'],3)
        search.embed_document('evidence')
        voyage.embed.assert_called_with('evidence','document')

    def test_invalid_limits_and_filters_rejected_before_network(self):
        search=AtlasMemorySearch(self.collection)
        for limit in [0,-1,True,101]:
            with self.assertRaises(ValueError): search.search_memories('q',limit,{})
        with self.assertRaises(ValueError): search.search_memories('q',5,{'$where':'bad'})
        self.collection.aggregate.assert_not_called()

    def test_index_readiness_and_visibility_are_separate(self):
        self.collection.list_search_indexes.return_value=[{'queryable':True,'status':'BUILDING'}]
        search=AtlasMemorySearch(self.collection)
        with self.assertRaises(TimeoutError): search.wait_until_ready(timeout=0)
        self.collection.list_search_indexes.return_value=[{'queryable':True,'status':'READY'}]
        search.wait_until_ready(timeout=0)
        with self.assertRaises(TimeoutError): search.wait_until_visible('different-id','noise',timeout=0)
        search.wait_until_visible('n','noise',timeout=0)

    def test_existing_index_definition_mismatch_is_not_silently_replaced(self):
        search=AtlasMemorySearch(self.collection)
        self.collection.list_search_indexes.return_value=[{'latestDefinition':{'fields':[]}}]
        with self.assertRaises(ValueError): search.ensure_index()
        self.collection.create_search_index.assert_not_called()


class ModelTests(unittest.TestCase):
    def test_batch_judge_covers_all_candidate_ids_in_one_bounded_call(self):
        candidates=[{'id':f'n{i}','text':f'Assertion {i}'} for i in range(12)]
        content=json.dumps({'decisions':[{'id':n['id'],'decision':'same' if i==11 else 'new'}
                                         for i,n in enumerate(candidates)]})
        transport=Mock(return_value={'choices':[{'message':{'content':content}}]})
        judge=OpenRouterJudge('secret','model',transport=transport)
        result=judge.classify_many({'text':'Reworded assertion 11'},candidates)
        self.assertEqual(result['n11'],'same')
        self.assertEqual(len(result),12)
        self.assertEqual(transport.call_count,1)

    def test_batch_judge_does_not_accept_unrequested_or_duplicate_ids(self):
        for ids in [['not-requested'],['n1','n1']]:
            content=json.dumps({'decisions':[{'id':id,'decision':'same'} for id in ids]})
            transport=Mock(return_value={'choices':[{'message':{'content':content}}]})
            judge=OpenRouterJudge('secret','model',transport=transport)
            self.assertEqual(judge.classify_many({},[{'id':'n1'}]),{'n1':'new'})

    def test_batch_judge_malformed_decision_array_defaults_to_new(self):
        for decisions in [None, 3, [{'id':[], 'decision':'same'}]]:
            transport=Mock(return_value={'choices':[{'message':{'content':json.dumps({'decisions':decisions})}}]})
            judge=OpenRouterJudge('secret','model',transport=transport)
            self.assertEqual(judge.classify_many({},[{'id':'n1'}]),{'n1':'new'})

    def test_judge_passes_citations_dates_and_location_and_accepts_valid_decision(self):
        transport=Mock(return_value={'choices':[{'message':{'content':json.dumps({'decision':'same'})}}]})
        judge=OpenRouterJudge('secret','test/model',transport=transport)
        a={'text':'music','scope_key':'block1','source_ids':['s1'],'first_seen_at':'2026-09-01T00:00:00Z'}
        self.assertEqual(judge(a,dict(a,text='amplified sound')),'same')
        body=transport.call_args.args[2]
        self.assertEqual(body['temperature'],0)
        self.assertEqual(body['response_format']['type'],'json_schema')
        self.assertIn('block1',body['messages'][1]['content'])
        self.assertIn('s1',body['messages'][1]['content'])

    def test_judge_bad_json_refusal_and_network_failure_default_to_new(self):
        for response in ['not json','{"decision":"maybe"}',None]:
            transport=Mock(return_value={'choices':[{'message':{'content':response}}]})
            self.assertEqual(OpenRouterJudge('secret','model',transport=transport)({},{}),'new')
        judge=OpenRouterJudge('secret','model',transport=Mock(side_effect=TimeoutError()))
        self.assertEqual(judge({},{}),'new')

    def test_oversized_decision_does_not_silently_truncate_evidence(self):
        transport=Mock()
        judge=OpenRouterJudge('secret','model',transport=transport)
        self.assertEqual(judge({'text':'x'*25000},{}),'new')
        transport.assert_not_called()

    def test_explicit_embedding_dimensions_and_finiteness_are_validated(self):
        for values in [[1,2],[float('nan')]*3]:
            embed=VoyageEmbeddings('secret',dimensions=3,
                                   transport=Mock(return_value={'data':[{'embedding':values}]}))
            with self.assertRaises(ValueError): embed.embed('text','query')


if __name__=='__main__': unittest.main()
