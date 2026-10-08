"""Offline provider preparation tests. Fixtures are not a live Aster backend."""
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from aster_provider import (Capability, DeadlineExceeded, InProcessTestTransport, InvalidRequest,
    ProviderCancelled, ProviderResponse, ProviderUnavailable, StaleSelection,
    UnsupportedCapability, schema_identity)
from ai import provider as p
from ai.chat import IdeaForgeChat
from ai.vision import analyze_image
from core.project_memory import remember_from_text
from core.project_state import load as load_state, set_research
from inventory.extract_from_chat import maybe_remember
from inventory.enrich import enrich_equipment
from research_engine.background import BackgroundResearchManager
from research_engine.horizon import expand_topics
from research_engine.summarize import summarize
from research_engine.discoveries import assess
from research_engine import discovery_selection as ledger
from research_engine.variants import analyze_variants
from research_engine.virtual_builder import update_virtual_build
from fabrication.prototype_plan import plan as prototype
from simulation.planner import plan as simulation
from troubleshooting.engine import _build_queries, diagnose


OUTPUTS = {
    'chat': '  unmodified raw answer\n',
    'chat_json': '{"project_name":"New test","summary":"Unknown","subsystems":[]}',
    'project_memory': '{"facts":[{"key":"width","statement":"width 20 mm","value":20,"unit":"mm"}]}',
    'equipment_extract': '{"items":[{"name":"Test printer","category":"3d_printer"}]}',
    'equipment_enrich': '{"specs":{},"capabilities":[],"source_urls":[]}',
    'research_horizon': '{"watch_queries":[]}',
    'research_summary': 'Unknown; synthetic source claim only.',
    'discovery_assess': '{"discoveries":[]}',
    'reference_variants': '{"selection_needed":false,"variants":[]}',
    'virtual_build': '{"current_buildable_concept":{"summary":"Unknown"}}',
    'prototype_plan': '{"printable_parts":[],"unknowns":["TBD"]}',
    'simulation_plan': '{"simulations":[],"critical_unknowns":["TBD"]}',
    'troubleshooting_queries': '{"queries":[]}',
    'troubleshooting_diagnosis': 'Insufficient evidence; no fix claimed.',
}


class ProviderRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / '10000001'
        self.root.mkdir()
        for name in ('research', 'design', 'fabrication', 'simulation', 'troubleshooting'):
            (self.root / name).mkdir()
        self.write(self.root/'project.json', {'project_id':'10000001','name':'Test','plan':{}})
        self.bundle = {'web':[{'title':'Saved evidence','url':'https://example.org/source',
                                'snippet':'Source claim; unknown validity.'}]}
        self.write(self.root/'research/research.json', self.bundle)
        self.write(self.root/'research/gallery.json', {'images':[{'index':1},{'index':2}]})
        self.ai = self.base/'ai.json'
        self.write(self.ai, {'language_model':{'model':'standalone-test','base_url':'http://127.0.0.1:11434',
                                              'timeout_seconds':180,'temperature':.25},
                             'vision_model':{'model':'qwen3-vl:8b','base_url':'http://127.0.0.1:11434'}})
        self.selection = self.base/'ai_provider.json'
        self.choose('standalone')
        self.watch = self.base/'watch.json'; self.write(self.watch,{})
        self.trouble = self.base/'trouble.json'; self.write(self.trouble,{})
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(p,'SELECTION_PATH',self.selection))
        self.stack.enter_context(patch('inventory.enrich.DDGS',return_value=Mock(text=Mock(return_value=[]))))
        self.stack.enter_context(patch('troubleshooting.engine._search',return_value=[]))
        self.inventory = {'items':[{'equipment_id':'owned-1','name':'Test printer','specs':{}}]}
        self.stack.enter_context(patch('inventory.enrich.load_local',return_value=self.inventory))
        self.saved_inventory = self.stack.enter_context(patch('inventory.enrich.save_local'))
        self.remember = self.stack.enter_context(patch('inventory.extract_from_chat.remember',side_effect=lambda item:item))
        self.stack.enter_context(patch('fabrication.prototype_plan.load_all',return_value={'items':[]}))
        self.stack.enter_context(patch('simulation.planner.load_all',return_value={'items':[]}))
        self.chat = IdeaForgeChat.__new__(IdeaForgeChat)
        self.chat.config_path = self.ai
        self.chat.cfg = json.loads(self.ai.read_text())
        self.chat.current_project = self.root
        self.chat.history = []
        self.chat._pending_cancel = None
        self.chat._turn_lock = threading.RLock()
        self.chat._closed = False
        self.chat.research_manager = Mock(enqueue=Mock(return_value=False))
        self.chat.last_provider_provenance = []
        self.seen = []

    def write(self,path,data):
        path.write_text(json.dumps(data),encoding='utf-8')

    def choose(self,provider,revision=1):
        self.write(self.selection,{'protocol':'aster.provider.selection.v1','app_id':'ideaforge',
                                   'provider':provider,'revision':revision})

    def routes(self):
        return {
            'chat':lambda:self.chat._call([{'role':'user','content':'hello'}]),
            'project_memory':lambda:remember_from_text(self.root,'must use width 20 mm',str(self.ai)),
            'equipment_extract':lambda:maybe_remember('I have a test printer',str(self.ai)),
            'equipment_enrich':lambda:enrich_equipment('owned-1',str(self.ai)),
            'research_horizon':lambda:expand_topics(self.root,str(self.ai)),
            'research_summary':lambda:summarize(self.root,str(self.ai)),
            'discovery_assess':lambda:assess(self.root,{},self.bundle,str(self.ai),str(self.watch)),
            'reference_variants':lambda:analyze_variants(self.root,str(self.ai)),
            'virtual_build':lambda:update_virtual_build(self.root,[],str(self.ai)),
            'prototype_plan':lambda:prototype(self.root,str(self.ai)),
            'simulation_plan':lambda:simulation(self.root,str(self.ai)),
            'troubleshooting_queries':lambda:_build_queries('stuck',None,{'name':'Test'},self.chat.cfg['language_model']),
            'troubleshooting_diagnosis':lambda:diagnose(self.root,'stuck',ai_config=str(self.ai),trouble_config=str(self.trouble)),
        }

    def fixture(self,handler=None,capabilities=None):
        if capabilities is None:
            capabilities=[]
            candidates=ledger.normalized(self.bundle)
            for task in OUTPUTS:
                schema = (ledger.schema(candidates) if task=='discovery_assess' else
                          None if task in ('chat','research_summary','troubleshooting_diagnosis') else 'json')
                capabilities.append(Capability(task,schema_identity(schema)[0]))
        def respond(request):
            self.seen.append(request)
            return ProviderResponse.for_request(request,OUTPUTS[request.task])
        return InProcessTestTransport(handler or respond,capabilities=capabilities)

    def scope(self,**kwargs):
        return p.operation(self.root,self.ai,selection_path=self.selection,**kwargs)

    def post(self,task):
        def call(url,*,json,timeout):
            self.assertEqual(url,'http://127.0.0.1:11434/api/chat')
            self.assertEqual(json['model'],'standalone-test')
            self.assertFalse(json['stream'])
            self.assertGreater(timeout,0); self.assertLessEqual(timeout,180)
            actual='troubleshooting_queries' if json['messages'][0]['content'].startswith('Create up to 5') else task
            response=Mock();response.json.return_value={'message':{'content':OUTPUTS[actual]}}
            return response
        return call

    def test_all_thirteen_standalone_routes_keep_payload_and_raw_semantics(self):
        self.assertEqual(len(self.routes()),13)
        for task,run in self.routes().items():
            with self.subTest(task=task),self.scope() as op,patch.object(p.requests,'post',side_effect=self.post(task)) as post:
                result=run()
                self.assertTrue(post.called)
                self.assertEqual(op.provenance[-1]['provider'],'standalone')
                self.assertEqual(op.provenance[-1]['task'],task)
                if task=='chat':self.assertEqual(result,OUTPUTS[task])
                if task=='discovery_assess':
                    self.assertIsInstance(post.call_args.kwargs['json']['format'],dict)
                    self.assertEqual(post.call_args.kwargs['json']['options']['num_predict'],8192)

    def test_all_thirteen_aster_routes_use_only_bound_offline_fixture(self):
        self.choose('aster')
        with patch.object(p.requests,'post',side_effect=AssertionError('Hidden Ollama request')) as post:
            for task,run in self.routes().items():
                with self.subTest(task=task),self.scope(transport=self.fixture()) as op:
                    result=run()
                    self.assertEqual(self.seen[-1].task,task)
                    self.assertEqual(op.provenance[-1]['provider'],'aster')
                    self.assertTrue(op.provenance[-1]['test_only'])
                    if task=='chat':self.assertEqual(result,OUTPUTS[task])
            post.assert_not_called()
        for request in self.seen:
            self.assertEqual(request.app_id,'ideaforge')
            self.assertEqual(request.project_id,'10000001')
            self.assertEqual(request.session_id,p.SESSION_ID)
            self.assertEqual(request.config_revision,1)
            self.assertTrue(request.input_digest)
            self.assertFalse(request.allow_personal_memory)
            self.assertFalse(request.allow_training)
            self.assertLessEqual(request.deadline,time.time()+180)
        self.assertEqual(len({r.request_id for r in self.seen}),len(self.seen))

    def test_all_thirteen_unavailable_routes_raise_without_fallback(self):
        self.choose('aster')
        with patch.object(p.requests,'post',side_effect=AssertionError('Hidden model')) as post:
            for task,run in self.routes().items():
                with self.subTest(task=task),self.scope(),self.assertRaises(ProviderUnavailable):run()
            post.assert_not_called()
        self.assertEqual(self.remember.call_count,0)
        self.saved_inventory.assert_not_called()
        self.assertFalse((self.root/'research/RESEARCH_BRIEF.md').exists())
        with ledger.connect(self.root) as db:
            self.assertEqual(db.execute('SELECT state FROM candidates').fetchone()[0],'pending')
            self.assertEqual(db.execute('SELECT count(*) FROM reports').fetchone()[0],0)

    def test_all_thirteen_unsupported_routes_raise_without_fallback(self):
        self.choose('aster')
        with patch.object(p.requests,'post',side_effect=AssertionError('Hidden model')) as post:
            for task,run in self.routes().items():
                with self.subTest(task=task),self.scope(transport=self.fixture(capabilities=[])),self.assertRaises(UnsupportedCapability):run()
            post.assert_not_called()

    def test_nested_chat_extraction_uses_same_selection_session_and_no_model(self):
        self.choose('aster')
        with self.scope(transport=self.fixture()) as op,patch.object(p.requests,'post') as post,patch('core.chat_context.load_all',return_value={'items':[]}):
            answer=self.chat.ask('I have a test printer; it must use width 20 mm')
            self.assertIn(OUTPUTS['chat'],answer)
            self.assertEqual([r.task for r in self.seen],['equipment_extract','project_memory','chat'])
            self.assertEqual(len({r.config_digest for r in self.seen}),1)
            self.assertEqual(len({r.session_id for r in self.seen}),1)
            self.assertTrue(all(r.request_id.startswith(op.request_prefix) for r in self.seen))
            post.assert_not_called()

    def test_config_change_during_call_discards_result_before_publication(self):
        self.choose('aster')
        def respond(request):
            self.choose('standalone',2)
            return ProviderResponse.for_request(request,OUTPUTS[request.task])
        with self.scope(transport=self.fixture(respond)),patch.object(p.requests,'post') as post,self.assertRaises(StaleSelection):
            summarize(self.root,str(self.ai))
        post.assert_not_called()
        self.assertFalse((self.root/'research/RESEARCH_BRIEF.md').exists())

    def test_language_model_config_change_is_stale_not_silent_reselection(self):
        def respond(*args,**kwargs):
            cfg=json.loads(self.ai.read_text());cfg['language_model']['model']='other'
            self.write(self.ai,cfg)
            result=Mock();result.json.return_value={'message':{'content':'late'}};return result
        with self.scope(),patch.object(p.requests,'post',side_effect=respond),self.assertRaises(StaleSelection):
            summarize(self.root,str(self.ai))
        self.assertFalse((self.root/'research/RESEARCH_BRIEF.md').exists())

    def test_cancellation_after_response_blocks_generated_files(self):
        self.choose('aster');cancel=threading.Event()
        def respond(request):
            cancel.set()
            return ProviderResponse.for_request(request,OUTPUTS[request.task])
        with self.scope(cancellation=cancel,transport=self.fixture(respond)),self.assertRaises(ProviderCancelled):
            prototype(self.root,str(self.ai))
        self.assertFalse((self.root/'fabrication/prototype_plan.json').exists())

    def test_expired_operation_never_calls_a_model(self):
        with patch.object(p.requests,'post') as post,self.assertRaises(DeadlineExceeded):
            with self.scope(deadline=time.time()-1):self.routes()['chat']()
        post.assert_not_called()

    def test_cancelled_discovery_releases_pending_lease(self):
        self.choose('aster');cancel=threading.Event()
        def respond(request):
            cancel.set();return ProviderResponse.for_request(request,OUTPUTS[request.task])
        with self.scope(cancellation=cancel,transport=self.fixture(respond)),self.assertRaises(ProviderCancelled):
            self.routes()['discovery_assess']()
        with ledger.connect(self.root) as db:
            self.assertEqual(db.execute('SELECT state FROM candidates').fetchone()[0],'pending')
            self.assertEqual(db.execute('SELECT count(*) FROM reports').fetchone()[0],0)

    def test_close_rejects_a_chat_worker_that_has_not_started(self):
        self.chat.close()
        with patch.object(p.requests,'post') as post,self.assertRaises(ProviderCancelled):
            self.chat.ask('hello')
        post.assert_not_called()
        self.assertEqual(self.chat.history,[])

    def test_cross_project_nested_call_is_rejected(self):
        other=self.base/'10000002';other.mkdir();self.write(other/'project.json',{'project_id':'10000002'})
        with self.scope(),patch.object(p.requests,'post') as post,self.assertRaises(StaleSelection):
            summarize(other,str(self.ai))
        post.assert_not_called()

    def test_project_identity_mutation_discards_late_result(self):
        def respond(*args,**kwargs):
            self.write(self.root/'project.json',{'project_id':'10000002','name':'Changed'})
            result=Mock();result.json.return_value={'message':{'content':'late'}};return result
        with self.scope(),patch.object(p.requests,'post',side_effect=respond),self.assertRaises(StaleSelection):
            self.routes()['research_summary']()
        self.assertFalse((self.root/'research/RESEARCH_BRIEF.md').exists())

    def test_project_switch_discards_late_result(self):
        other=self.base/'10000002';other.mkdir()
        def respond(*args,**kwargs):
            self.chat.current_project=other
            result=Mock();result.json.return_value={'message':{'content':'late'}};return result
        with self.scope(project_current=lambda:self.chat.current_project),patch.object(p.requests,'post',side_effect=respond),self.assertRaises(ProviderCancelled):
            self.routes()['research_summary']()
        self.assertFalse((self.root/'research/RESEARCH_BRIEF.md').exists())

    def test_new_project_definition_binds_new_project_without_provider_reselection(self):
        self.choose('aster');self.chat.current_project=None
        self.stack.enter_context(patch('core.projects.ROOT',self.base/'new-projects'))
        with p.operation(None,self.ai,transport=self.fixture(),selection_path=self.selection) as op:
            original=op.selection
            created=self.chat.maybe_create_project('I want to build a new test')
            self.assertIsNotNone(created)
            self.assertEqual(self.seen[0].project_id,'workspace')
            self.assertEqual(op.selection.provider,original.provider)
            self.assertEqual(op.selection.config_digest,original.config_digest)
            self.assertEqual(op.project,p.project_id(created[1]))
            self.chat._call([{'role':'user','content':'continue'}])
            self.assertEqual(self.seen[-1].project_id,op.project)

    def test_vision_is_explicitly_disabled_in_aster_before_file_or_model_access(self):
        self.choose('aster')
        with self.scope(),patch.object(p.requests,'post') as post,self.assertRaises(UnsupportedCapability):
            analyze_image(self.base/'absent.png','problem',self.chat.cfg)
        post.assert_not_called()

    def test_standalone_vision_specialist_is_separate(self):
        picture=self.base/'fixture.png';picture.write_bytes(b'offline image fixture')
        response=Mock();response.json.return_value={'message':{'content':'visible details'}}
        with self.scope(),patch.object(p.requests,'post',return_value=response) as post:
            self.assertEqual(analyze_image(picture,'problem',self.chat.cfg),'visible details')
        self.assertEqual(post.call_args.kwargs['json']['model'],'qwen3-vl:8b')
        self.assertIn('images',post.call_args.kwargs['json']['messages'][1])

    def manager(self):
        manager=BackgroundResearchManager.__new__(BackgroundResearchManager)
        manager.ai_config=self.ai;manager.q=queue.Queue();manager.active={}
        manager.stop_event=threading.Event();manager.watch_cfg={'auto_virtual_build':False}
        manager.interval_minutes=60;manager.event_callback=None
        manager.workspace_manager=Mock()
        return manager

    def test_background_unavailable_is_error_and_keeps_downloaded_evidence(self):
        self.choose('aster');manager=self.manager()
        self.write(self.root/'research/technology_horizon.json',{'watch_queries':[]})
        events=[]
        def event(kind,payload):
            events.append(kind)
            if kind=='research_error':manager.stop_event.set()
        manager.event_callback=event
        before=(self.root/'research/research.json').read_bytes()
        manager.enqueue(self.root,'quick')
        with patch('research_engine.research_project.research_project',return_value=self.bundle),patch.object(p.requests,'post') as post:
            manager._loop()
        post.assert_not_called()
        self.assertIn('research_error',events);self.assertNotIn('research_complete',events)
        self.assertEqual(load_state(self.root)['research_status'],'error')
        self.assertEqual((self.root/'research/research.json').read_bytes(),before)

    def test_failed_synthesis_keeps_new_download_as_pending_not_baseline(self):
        self.choose('aster');manager=self.manager()
        old={'web':[{'title':'Old','url':'https://example.org/old'}]}
        self.write(self.root/'research/research.json',old)
        self.write(self.root/'research/technology_horizon.json',{'watch_queries':[]})
        def download(*args,**kwargs):
            self.write(self.root/'research/research.json',self.bundle)
            return self.bundle
        with patch('research_engine.research_project.research_project',side_effect=download),self.assertRaises(ProviderUnavailable):
            manager._run_pass(self.root,'quick')
        with ledger.connect(self.root) as db:
            rows=db.execute('SELECT data,state FROM candidates').fetchall()
        self.assertEqual({json.loads(row['data'])['url']:row['state'] for row in rows},
                         {'https://example.org/old':'baseline','https://example.org/source':'pending'})
        self.assertEqual(json.loads((self.root/'research/research.json').read_text()),self.bundle)

    def test_full_background_pipeline_keeps_one_captured_operation(self):
        self.choose('aster');manager=self.manager();manager.watch_cfg['auto_virtual_build']=True
        self.write(self.root/'research/research.json',{'web':[]})
        with self.scope(transport=self.fixture()) as op,patch.object(p.requests,'post') as post,\
             patch('research_engine.research_project.research_project',return_value=self.bundle),\
             patch('research_engine.gallery.build_gallery',return_value=[]):
            result=manager._run_pass(self.root,'deep')
            self.assertEqual([r.task for r in self.seen],['research_horizon','research_summary',
                             'reference_variants','discovery_assess','virtual_build'])
            self.assertTrue(all(r.request_id.startswith(op.request_prefix) for r in self.seen))
            self.assertTrue(result[-1]);post.assert_not_called()

    def test_unavailable_project_definition_does_not_create_project(self):
        self.choose('aster');self.chat.current_project=None
        with patch('ai.chat.create_project') as create,patch.object(p.requests,'post') as post,\
             self.assertRaises(ProviderUnavailable):
            self.chat.maybe_create_project('I want to build a new test')
        create.assert_not_called();post.assert_not_called()

    def test_only_text_router_and_explicit_vision_can_post_model_requests(self):
        root=Path(__file__).resolve().parents[1]
        matches=[]
        for folder in ('ai','core','inventory','research_engine','fabrication','simulation','troubleshooting'):
            for source in (root/folder).glob('*.py'):
                if 'requests.post(' in source.read_text():matches.append(source.relative_to(root).as_posix())
        self.assertEqual(sorted(matches),['ai/provider.py','ai/vision.py'])

    def test_background_capture_is_stale_after_provider_change_not_reselected(self):
        manager=self.manager();manager.enqueue(self.root)
        key,mode,captured=manager.q.get_nowait()
        self.choose('aster',2)
        with patch.object(p.requests,'post') as post,self.assertRaises(StaleSelection):
            with p.activate(captured):manager._run_pass(self.root,mode)
        post.assert_not_called()

    def test_restart_marks_pending_interrupted_without_replay(self):
        for state in ('queued','running'):
            set_research(self.root,state)
            manager=self.manager();manager.resume_pending([{'path':str(self.root)}])
            self.assertTrue(manager.q.empty())
            self.assertEqual(load_state(self.root)['research_status'],'interrupted')

    def test_fresh_process_has_new_session_and_no_replayed_requests(self):
        code='from ai.provider import SESSION_ID, current_operation; print(SESSION_ID); print(current_operation())'
        result=subprocess.check_output([sys.executable,'-c',code],text=True).splitlines()
        self.assertNotEqual(result[0],p.SESSION_ID)
        self.assertEqual(result[1],'None')

    def test_context_and_response_bounds_fail_without_truncation(self):
        with self.scope(),patch.object(p.requests,'post') as post,self.assertRaises(InvalidRequest):
            p.text_call([{'role':'user','content':'x'*(p.MAX_MESSAGE_CHARS+1)}],task='chat')
        post.assert_not_called()
        response=Mock();response.json.return_value={'message':{'content':'x'*(p.MAX_RESPONSE_CHARS+1)}}
        with self.scope(),patch.object(p.requests,'post',return_value=response),self.assertRaises(InvalidRequest):
            self.routes()['research_summary']()
        self.assertFalse((self.root/'research/RESEARCH_BRIEF.md').exists())

    def test_selector_changes_explicit_config_and_truthfully_reports_unavailable(self):
        with patch('builtins.print') as output,patch.object(p.requests,'post') as post:
            p.main(['--provider','aster','--selection-path',str(self.selection),'--config',str(self.ai)])
        post.assert_not_called()
        data=json.loads(self.selection.read_text());self.assertEqual(data['provider'],'aster')
        self.assertEqual(data['revision'],2)
        self.assertIn('unavailable',output.call_args.args[0])
        self.assertNotIn('base_url',data)

    def test_selection_symlink_rejected_consistently_by_operation_and_status(self):
        target=self.base/'selection-target.json'
        target.write_bytes(self.selection.read_bytes())
        self.selection.unlink();self.selection.symlink_to(target)
        with self.assertRaises(InvalidRequest):
            with self.scope():pass
        with self.assertRaises(InvalidRequest):p.status(self.ai,self.selection)

    def test_selection_replaced_by_symlink_cannot_publish_to_old_target(self):
        target=self.base/'selection-target.json';target.write_bytes(self.selection.read_bytes())
        def respond(*args,**kwargs):
            self.selection.unlink();self.selection.symlink_to(target)
            result=Mock();result.json.return_value={'message':{'content':'late'}};return result
        with self.scope(),patch.object(p.requests,'post',side_effect=respond),self.assertRaises(InvalidRequest):
            self.routes()['research_summary']()
        self.assertFalse((self.root/'research/RESEARCH_BRIEF.md').exists())

    def test_default_missing_selection_is_standalone(self):
        self.selection.unlink()
        with self.scope() as op:self.assertEqual(op.selection.provider,'standalone')


if __name__=='__main__':unittest.main()
