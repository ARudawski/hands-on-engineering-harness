"""Controller/transport replays only: no native process, account or model execution."""
from collections import deque
from io import StringIO
from contextlib import ExitStack
import json
import os
import queue
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from evaluation import signed_in_delivery as delivery
from evaluation.signed_in import RequestStore
from evaluation.signed_in_workflow import CandidateObservation
from evaluation import signed_in_native as native
import threading
import time
import sys
from evaluation import signed_in


class Channel:
    def __init__(self, answer=None):
        self.answer, self.events, self.queue = answer, [], deque()
    def emit(self, event, **kwargs):
        self.events.append(event)
        if self.answer:
            value = self.answer(event)
            self.queue.append({**{k:v for k,v in event.items() if k != 'body'}, 'response': value})
    def poll(self, seconds=.1):
        return self.queue.popleft() if self.queue else None


class ConnectedDelivery(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.origin, self.request, self.profile, self.thread, self.turn = (str(uuid4()) for _ in range(5))
        self.input = {'request_id':self.request,'case':'native-foundation','seconds':120,
                      'profile_id':self.profile,'candidate_ref':'feature/candidate'}
        self.resolve = Mock(return_value='a'*40)
        self.channel = Channel(lambda event: {'verdict':'pass','reason':'The answer identifies the wrong sum with [1,2].'})

    def replay(self, payload, **kwargs):
        self.assertTrue(kwargs['delivery'].matches(payload))
        self.assertTrue(kwargs['candidate_run'])
        messages=[{'thread_id':self.thread,'turn_id':self.turn,
                   'item_id':'answer','text':'The sum is wrong: [1,2] should be 3.'}]
        return {'root_thread_id':self.thread,'cleanup_verified':True,'status':'observed_pending_assessment',
                'elapsed_seconds':3.2,'candidate_observation':{'execution_end':'completed','safety':'no_observed_breach',
                'participants':[{'thread_id':self.thread,'thread_configuration':{'model':None,'effort':None}}],
                'subagent_coverage':'unknown','agent_messages':messages,
                'completion':{'root':self.thread,'turn':self.turn,'generation':0,'artifact_sha256':'f'*64,
                              'messages':messages,'observed_at':100,'elapsed_seconds':2}}}

    def run_delivery(self, **kwargs):
        return delivery.deliver(self.input,self.channel,root=self.root,origin=self.origin,
                                resolver=self.resolve,native_runner=kwargs.pop('runner',self.replay),**kwargs)

    def session(self):
        store = RequestStore(self.root/'store')
        store.submit(self.origin,self.request,'native-foundation',120)
        return delivery.Delivery(store,self.origin,self.request,self.channel)

    def test_first_report_survives_moved_ref_and_duplicate_never_relaunches(self):
        runner = Mock(side_effect=self.replay)
        result = self.run_delivery(runner=runner)
        self.resolve.return_value='b'*40
        again = self.run_delivery(runner=runner)
        self.assertEqual(again,result)
        self.assertEqual(again['candidate_revision'],'a'*40)
        self.assertEqual(again['assessment']['verdict'],'pass')
        self.assertEqual(self.resolve.call_count,1)
        self.assertEqual(runner.call_count,1)

    def test_changed_and_foreign_requests_reject_before_resolution_or_launch(self):
        self.run_delivery()
        self.input['seconds']=121
        with self.assertRaisesRegex(ValueError,'inputs changed'):
            self.run_delivery()
        self.input['seconds']=120
        with self.assertRaises(PermissionError):
            delivery.deliver(self.input,self.channel,root=self.root,origin=str(uuid4()),resolver=self.resolve)
        self.assertEqual(self.resolve.call_count,1)

    def test_invalid_case_budget_and_selector_reject_without_resolver(self):
        for key,value in [('case','other'),('seconds',901),('candidate_ref','')]:
            old=self.input[key]; self.input[key]=value
            with self.assertRaises(ValueError):self.run_delivery()
            self.input[key]=old
        self.resolve.assert_not_called()

    def test_grading_uses_trusted_response_for_good_wrong_and_missing_answers(self):
        for verdict in ('pass','fail','unassessed'):
            self.input['request_id']=str(uuid4())
            self.channel.answer=lambda event,v=verdict:{'verdict':v,'reason':'Independent rubric assessment.'}
            report=self.run_delivery()
            self.assertEqual(report['assessment']['verdict'],verdict)
        def missing(payload,**kwargs):
            value=self.replay(payload,**kwargs);value['candidate_observation']['agent_messages']=[];return value
        self.input['request_id']=str(uuid4());before=len(self.channel.events)
        self.assertEqual(self.run_delivery(runner=missing)['assessment']['verdict'],'unassessed')
        self.assertEqual(len(self.channel.events),before)

    def test_final_report_has_one_answer_copy_and_large_retrieval_reaches_the_real_channel(self):
        for answer in ('A'*65536, '\U0001f642'*16384, '\x01'*65536):
            with self.subTest(character=repr(answer[0])):
                self.input['request_id']=str(uuid4())
                def runner(payload,**kwargs):
                    result=self.replay(payload,**kwargs)
                    result['candidate_observation']['agent_messages'][0]['text']=answer
                    return result
                first=self.run_delivery(runner=runner)
                self.assertFalse('messages' in first['completion'])
                self.assertEqual(first['deliverable'][0]['text'],answer)
                self.assertEqual(first['assessment']['verdict'],'pass')
                wires=[]
                for _ in range(2):
                    output=StringIO()
                    with patch.object(signed_in,'ROOT',self.root),patch.object(sys,'argv',['signed_in.py']), \
                         patch.object(sys,'stdin',StringIO(json.dumps(self.input)+'\n')), \
                         patch.object(sys,'stdout',output),patch.dict(os.environ,CODEX_THREAD_ID=self.origin):
                        self.assertIsNone(signed_in.main())
                    raw=output.getvalue();self.assertLessEqual(len(raw.encode('ascii')),131072)
                    response=json.loads(raw);self.assertEqual(response['kind'],'result')
                    body=response['body'];self.assertEqual(body['request_id'],self.input['request_id'])
                    self.assertEqual(body['assessment'],first['assessment'])
                    self.assertEqual(body['evidence'],first['evidence'])
                    self.assertEqual(body['cleanup_verified'],True)
                    if answer[0]!='A':
                        self.assertTrue(body['details_omitted'])
                        self.assertNotIn('deliverable',body)
                    else:self.assertEqual(body['deliverable'],first['deliverable'])
                    wires.append(raw)
                self.assertEqual(wires[0],wires[1])
                self.assertEqual(self.run_delivery(runner=Mock(side_effect=AssertionError('relaunch'))),first)

    def test_oversize_legacy_result_is_projected_without_rewriting_its_receipt(self):
        first=self.run_delivery()
        first['completion']['messages']=[{**first['deliverable'][0],'text':'A'*65536}]
        first['deliverable']=first['completion']['messages']
        store=RequestStore(self.root/'.tmp/evaluation-signed-in')
        with store.request(self.origin,self.request) as state:state['delivery_receipt']=first
        output=StringIO();channel=delivery.JsonChannel(StringIO(''),output)
        again=self.run_delivery(runner=Mock(side_effect=AssertionError('relaunch')))
        channel.emit({'kind':'result','body':again})
        body=json.loads(output.getvalue())['body']
        self.assertTrue(body['details_omitted']);self.assertEqual(body['evidence'],first['evidence'])
        self.assertNotIn('messages',body['completion'])
        self.assertEqual(self.run_delivery(),first)

    def test_integrity_failures_withhold_grade_but_optional_child_warning_does_not(self):
        def warned(payload,**kwargs):
            value=self.replay(payload,**kwargs)
            value['candidate_observation']['behavior_warnings']=[{'kind':'turn_failed','thread_id':str(uuid4())}]
            return value
        self.assertEqual(self.run_delivery(runner=warned)['assessment']['verdict'],'pass')
        changes=[('cleanup_verified',False),('source_drift',True),('candidate_input_drift',True),
                 ('error_code','protected_disclosure')]
        observations=[('infrastructure_limitations',['unattributed_events']),('safety','invalid'),
                      ('pending_decisions',[{'kind':'question'}]),('completion',None)]
        for target,key,value in [('result',k,v) for k,v in changes]+[('observation',k,v) for k,v in observations]:
            self.input['request_id']=str(uuid4());count=len(self.channel.events)
            def damaged(payload,**kwargs):
                result=self.replay(payload,**kwargs)
                (result if target=='result' else result['candidate_observation'])[key]=value
                return result
            with self.subTest(target=target,key=key):
                report=self.run_delivery(runner=damaged)
                self.assertEqual(report['assessment']['verdict'],'unassessed')
                self.assertEqual(len(self.channel.events),count)

    def test_retired_assessment_or_late_wait_cannot_reopen_or_grade_a_new_frame(self):
        session=self.session()
        first={'root':self.thread,'turn':self.turn,'artifact_sha256':'a'*64,'messages':['first']}
        second={**first,'turn':str(uuid4()),'artifact_sha256':'b'*64,'messages':['second']}
        session.provisional_assessment=(first['artifact_sha256'],{'verdict':'pass','reason':'old'})
        with self.assertRaisesRegex(ValueError,'controller_reply_rejected'):
            session.final_assessment(second)
        session.provisional_assessment=None
        self.channel.answer=lambda e:{'status':'waiting','question':'Can I change the code?'}
        result=session.final_assessment(second)
        self.assertEqual(result['verdict'],'unassessed')
        self.assertEqual(len(self.channel.events),1)
        self.assertEqual(session.operator_wait['frame_sha256'],second['artifact_sha256'])

    def test_disconnect_during_assessment_retains_first_incomplete_report(self):
        original=self.channel.poll
        def poll(seconds=.1):
            if self.channel.events and self.channel.events[-1]['kind']=='assessment':raise ConnectionError()
            return original(seconds)
        self.channel.poll=poll
        first=self.run_delivery()
        self.assertEqual(first['assessment']['verdict'],'unassessed')
        self.assertIn('assessment_unavailable',first['limitations'])
        self.assertEqual(self.run_delivery(runner=Mock(side_effect=AssertionError('relaunch'))),first)

    def test_cancel_during_assessment_also_retains_first_receipt(self):
        self.channel.answer=None
        original=self.channel.emit
        def emit(event,**kwargs):
            original(event,**kwargs)
            self.channel.queue.append({'origin':self.origin,'request_id':self.request,'action':'cancel'})
        self.channel.emit=emit
        first=self.run_delivery()
        self.assertEqual(first['assessment']['verdict'],'unassessed')
        self.assertEqual(self.run_delivery(runner=Mock(side_effect=AssertionError('relaunch'))),first)

    def test_slow_resolution_releases_shared_store_and_duplicate_returns_progress(self):
        entered,release=threading.Event(),threading.Event();results=[];errors=[]
        def resolve(*args):
            entered.set()
            if not release.wait(3):raise AssertionError('fixture timeout')
            return 'a'*40
        def first():
            try:results.append(delivery.deliver(self.input,self.channel,root=self.root,origin=self.origin,
                                               resolver=resolve,native_runner=self.replay))
            except Exception as error:errors.append(error)
        thread=threading.Thread(target=first);thread.start()
        try:
            self.assertTrue(entered.wait(1))
            duplicate=self.run_delivery(runner=Mock(side_effect=AssertionError('relaunch')))
            self.assertEqual(duplicate['status'],'resolving')
            self.resolve.assert_not_called()
            store=RequestStore(self.root/'.tmp/evaluation-signed-in')
            original=store.get(self.origin,self.request)
            with self.assertRaisesRegex(ValueError,'inputs changed'):
                store.submit(self.origin,self.request,'native-foundation',120)
            with self.assertRaisesRegex(ValueError,'mode changed'):
                native.bind_mode(store,self.origin,self.request,'prepare',
                                 {'model':'gpt-6-luna','effort':'low'},purpose='candidate-prepare')
            unchanged=store.get(self.origin,self.request)
            self.assertEqual(unchanged['deadline'],original['deadline'])
            self.assertEqual(unchanged['attempt_id'],original['attempt_id'])
            self.assertTrue(unchanged['admission_open'])
            other=str(uuid4());store.submit(self.origin,other,'native-foundation',120)
            self.assertTrue(store.get(self.origin,other)['admission_open'])
        finally:release.set();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual(results[0]['attempt_id'],duplicate['attempt_id'])

    def test_expired_resolution_never_opens_native_account_or_worker(self):
        now=[100.0,100.0]
        def resolve(*args):now[:]=[230.0,230.0];return 'a'*40
        runner=Mock(side_effect=AssertionError('native launch'))
        report=delivery.deliver(self.input,self.channel,root=self.root,origin=self.origin,
                               resolver=resolve,native_runner=runner,clock=lambda:tuple(now))
        runner.assert_not_called();self.assertEqual(report['execution_end'],'deadline_exhausted')

    def test_unresponsive_output_writer_is_bounded_without_stalling_controller(self):
        release=threading.Event()
        class Blocked:
            def write(self,value):release.wait(2)
            def flush(self):pass
        channel=delivery.JsonChannel(StringIO(''),Blocked())
        started=time.monotonic()
        try:
            with self.assertRaises(ConnectionError):channel.emit({'kind':'question'},timeout=.02)
            self.assertLess(time.monotonic()-started,.5)
        finally:release.set()

    def test_cleanup_failure_never_receives_a_passing_grade(self):
        def failed(payload,**kwargs):
            r=self.replay(payload,**kwargs);r['cleanup_verified']=False;return r
        result=self.run_delivery(runner=failed)
        self.assertEqual(result['assessment']['verdict'],'unassessed')
        self.assertFalse(result['cleanup_verified']);self.assertEqual(self.channel.events,[])

    def test_one_use_checkpoint_rejects_foreign_or_stale_response(self):
        session=self.session()
        self.channel.answer=None
        self.channel.queue.append({'origin':str(uuid4()),'response':{}})
        with self.assertRaisesRegex(ValueError,'controller_reply_rejected'):
            session.checkpoint('native_decision',{})
        self.channel.answer=lambda event: {'action':'finish'}
        session.checkpoint('candidate_output',{})
        stale={**{k:v for k,v in self.channel.events[-1].items() if k!='body'},'response':{'action':'finish'}}
        self.channel.queue.append(stale)
        with self.assertRaises(ValueError):session.checkpoint('candidate_output',{})

    def test_permission_expansion_is_forwarded_but_cannot_be_granted(self):
        session=self.session(); self.channel.answer=lambda event:{'decision':'accept'}
        owner=SimpleNamespace(remaining=Mock(return_value=30))
        observer=SimpleNamespace(owner=owner,connection=SimpleNamespace(respond=Mock()))
        request={'id':7,'method':'item/commandExecution/requestApproval',
                 'params':{'threadId':self.thread,'turnId':self.turn,'command':'outside-boundary'}}
        with self.assertRaisesRegex(ValueError,'permission_expansion_outside_trial'):
            session.native_decision(observer,request)
        observer.connection.respond.assert_not_called()
        self.assertFalse(self.channel.events[-1]['body']['permission_expansion_allowed'])

    def test_authorized_question_answers_are_forwarded_once(self):
        session=self.session(); answer={'answers':{'q':{'answers':['Inspect only']}}}
        self.channel.answer=lambda event:answer
        observer=SimpleNamespace(owner=SimpleNamespace(remaining=lambda:30),connection=SimpleNamespace(respond=Mock()))
        request={'id':7,'method':'item/tool/requestUserInput','params':{
            'threadId':self.thread,'turnId':self.turn,'questions':[{'id':'q','question':'Scope?'}]}}
        session.native_decision(observer,request)
        observer.connection.respond.assert_called_once_with(request,answer)

    def test_global_cancel_and_closed_connection_are_not_approval(self):
        session=self.session()
        self.channel.queue.append({'origin':self.origin,'request_id':self.request,'action':'cancel'})
        with self.assertRaises(InterruptedError):session.check_connected()
        channel=delivery.JsonChannel(StringIO(''),StringIO())
        channel.closed.wait(1)
        with self.assertRaises(ConnectionError):channel.poll(0)

    def test_successful_cleanup_reason_does_not_create_a_failure(self):
        session=self.session();session.store.claim_launch(self.origin,self.request)
        state=session.store.stop(self.origin,self.request,'completed')
        self.assertEqual(state['status'],'completed');self.assertIsNone(state['first_failure'])
        self.assertFalse(state['admission_open'])

    def test_public_entry_preserves_multiline_legacy_json_and_trailing_data_rejection(self):
        payload={k:self.input[k] for k in ('request_id','case','seconds')}
        for suffix in ('', '\nBAD_TRAILING_DATA'):
            output=StringIO()
            with patch.object(signed_in,'ROOT',self.root),patch.object(sys,'argv',['signed_in.py']), \
                 patch.object(sys,'stdin',StringIO(json.dumps(payload,indent=2)+suffix)), \
                 patch.object(sys,'stdout',output),patch.dict(os.environ,CODEX_THREAD_ID=self.origin):
                result=signed_in.main()
            value=json.loads(output.getvalue())
            if suffix:
                self.assertEqual(result,1);self.assertEqual(value,{'error':'request_rejected'})
            else:
                self.assertEqual(result,0);self.assertEqual(value['first_failure'],'deployment_unavailable')

    def test_finalized_success_cannot_expire_during_later_assessment_or_retrieval(self):
        now=[100.0,100.0];store=RequestStore(self.root/'clock',clock=lambda:tuple(now))
        store.submit(self.origin,self.request,'native-foundation',120)
        store.claim_launch(self.origin,self.request);store.stop(self.origin,self.request,'completed')
        now[:]=[1000.0,1000.0]
        self.assertEqual(store.get(self.origin,self.request)['status'],'completed')

    def test_native_response_rejects_second_wire_reply(self):
        session=self.session();session.store.claim_launch(self.origin,self.request)
        conn=native.NativeConnection.__new__(native.NativeConnection)
        conn.owner=SimpleNamespace(remaining=lambda:30,store=session.store,origin=self.origin,request_id=self.request)
        conn.profile={};conn._write=Mock()
        request={'id':7,'method':'item/tool/requestUserInput','params':{'threadId':self.thread,'turnId':self.turn}}
        conn.observer=SimpleNamespace(root=self.thread,callbacks={('int',7):(self.thread,self.turn,request['method'])},
                                      resolved=set(),answered=set())
        with patch.object(native,'require_binding'):
            conn.respond(request,{'answers':{}})
            with self.assertRaisesRegex(RuntimeError,'native_method_blocked'):
                conn.respond(request,{'answers':{}})
        conn._write.assert_called_once()

    def test_only_authorized_completed_checkpoint_can_prepare_second_root_turn(self):
        session=self.session();conn=native.NativeConnection.__new__(native.NativeConnection)
        conn.mode='diagnose';conn.profile={};conn._write=Mock()
        conn.owner=SimpleNamespace(remaining=lambda **kw:30,lock=threading.RLock(),store=session.store,
                                   origin=self.origin,request_id=self.request)
        with session.store.request(self.origin,self.request) as state:
            state.update(native_purpose='candidate-observe',native_root=self.thread,candidate_admission={'root':self.thread})
        value={'method':'turn/start','params':{'threadId':self.thread}}
        with patch.object(native,'require_binding'):
            conn.send(value)
            with self.assertRaises(RuntimeError):conn.send(value)
            self.channel.answer=lambda event: ({'status':'waiting','question':'Continue assessment?'}
                if event['kind']=='assessment' else {'action':'continue','text':'Continue the read-only assessment.'})
            frame={'root':self.thread,'turn':self.turn,'artifact_sha256':'f'*64,'messages':['question']}
            observer=SimpleNamespace(root=self.thread,owner=conn.owner,snapshot=lambda end:{},
                seal_completion=lambda:frame,frame_current=lambda f:True,drain_observations=lambda:None,
                retire_completion=Mock())
            self.assertEqual(session.completed_turn(observer,self.turn),'Continue the read-only assessment.')
            observer.retire_completion.assert_called_once()
            conn.send(value)
            with self.assertRaises(RuntimeError):conn.send(value)
        self.assertEqual(conn._write.call_count,2)


class ActualRootGate(unittest.TestCase):
    setUp = ConnectedDelivery.setUp
    session = ConnectedDelivery.session
    def gate_fixture(self):
        session=self.session();consumer=self.root/'consumer';consumer.mkdir();home=self.root/'home';home.mkdir()
        from evaluation.signed_in_worker import CANDIDATE_CHECKS
        from evaluation.signed_in_candidate import create_runtime_view
        from native_support import inventory
        full=self.root/'install';full.mkdir();(full/'AGENTS.md').write_text('deployed instructions')
        consumer.rmdir()
        installed={'files':inventory(full),'roles':{}}
        view=create_runtime_view(full,consumer,installed)
        options={'windows.sandbox':'mxc','default_permissions':'har12-native',
            'permissions.har12-native.network.enabled':False,'model_provider':'openai',
            'cli_auth_credentials_store':'file','shell_environment_policy.inherit':'none',
            'allow_login_shell':False,'web_search':'disabled','features.skip_host_skill_discovery':True,
            'features.multi_agent_v2.non_code_mode_only':False,'features.multi_agent_v2.tool_namespace':'collaboration',
            'permissions.har12-native.filesystem':{':root':'deny',str(home):'deny',str(full):'deny',':workspace_roots':{'.':'read','.tmp':'write'}}}
        options.update({'features.'+k:False for k in delivery.DISABLED})
        result={'root_thread_id':self.thread,'revision':'a'*40,'command_gate':dict.fromkeys(CANDIDATE_CHECKS,True),
                'effective_configuration':dict.fromkeys(delivery.CONFIG_CHECKS,True),
                'isolation_mcp_empty':True,'auth_mode':'chatgpt','installation':installed,'policy_sha256':'p',
                'installation_root':str(full),'consumer_view':view}
        with session.store.request(self.origin,self.request) as state:
            state.update(native_root=self.thread,native_purpose='candidate-observe',revision='a'*40,
                         delivery_payload={'candidate_revision':'a'*40})
        return session,result,options,consumer,home

    def test_gate_rejects_binary_optional_tool_and_access_drift_before_release(self):
        session,result,options,consumer,home=self.gate_fixture()
        with patch('native_support.digest',return_value='unassessed'):
            with self.assertRaisesRegex(RuntimeError,'candidate_executable_unassessed'):
                session.admit(result,'codex',options,consumer,home)
        from native_support import digest
        with patch('native_support.digest',side_effect=lambda p:digest(p) if Path(p).is_file() else delivery.CODEX_SHA256),patch('evaluation.signed_in_candidate.verify_candidate'):
            options['features.apps']=True
            with self.assertRaisesRegex(RuntimeError,'candidate_authority_changed'):
                session.admit(result,'codex',options,consumer,home)
            options['features.apps']=False;result['isolation_mcp_empty']=False
            with self.assertRaisesRegex(RuntimeError,'candidate_boundary_unverified'):
                session.admit(result,'codex',options,consumer,home)
            result['isolation_mcp_empty']=True
            session.admit(result,'codex',options,consumer,home)
        self.assertTrue(result['boundary_passed'])
        self.assertEqual(result['candidate_admission']['root'],self.thread)


class NativePipeline(unittest.TestCase):
    setUp = ConnectedDelivery.setUp

    def test_real_entry_to_native_gate_observer_cleanup_and_first_report_with_fake_wire(self):
        self.run_pipeline(False)

    def test_failed_actual_root_control_withholds_fixture_and_turn(self):
        self.run_pipeline(True)

    def test_question_then_continuation_share_original_request_and_budget(self):
        self.run_pipeline(False, 'question_continue')

    def test_disconnect_interrupts_active_root_and_retains_incomplete_first_report(self):
        self.run_pipeline(False, 'disconnect')

    def test_deadline_closes_before_any_followup(self):
        self.run_pipeline(False, 'deadline')

    def test_question_queued_during_metadata_reconciliation_is_forwarded(self):
        self.run_pipeline(False, 'queued_question')

    def test_completed_answer_is_graded_after_assessor_cutoff_without_finish_or_second_checkpoint(self):
        self.run_pipeline(False, 'late_assessment')

    def test_message_queued_with_terminal_notification_is_part_of_the_graded_artifact(self):
        self.run_pipeline(False, 'queued_message')

    def test_changed_artifact_while_assessor_replies_cannot_reuse_old_grade(self):
        self.run_pipeline(False, 'stale_assessment')

    def test_native_question_arriving_during_assessment_is_forwarded_before_completion(self):
        self.run_pipeline(False, 'assessment_question')

    def test_followup_without_own_output_cannot_be_graded_on_previous_turn(self):
        self.run_pipeline(False, 'empty_followup')

    def test_failed_idle_root_ends_before_deadline_and_cleans_up(self):
        self.run_pipeline(False, 'root_failed')

    def run_pipeline(self, deny, flow='finish'):
        from evaluation.signed_in_worker import CANDIDATE_CHECKS
        import evaluation.signed_in_workflow as workflow
        project=self.root/'Harness/project';project.mkdir(parents=True)
        (project/'tests/evaluation').mkdir(parents=True)
        (project/'tests/evaluation/signed_in_worker.py').write_bytes((native.ROOT/'tests/evaluation/signed_in_worker.py').read_bytes())
        (project/'tests/evaluation/signed_in_delivery.py').write_text('private rubric')
        home=self.root/'auth-home';home.mkdir()
        store=RequestStore(project/'.tmp/evaluation-signed-in')
        trace=[];outer=self
        class Owner:
            cleanup_deadline=time.monotonic()+60
            def run(self,command,**kwargs):
                if command[-1:] == ['--version']:
                    return '0.35.0' if command[0]=='apm' else 'codex-cli 0.167.0-alpha.3.2'
                if command[-1:] == ['positive']:
                    return json.dumps(dict(local_network=True,external_network=True,dns=True))
                return ''
            def remaining(self,*args,**kwargs):
                if flow=='root_failed':
                    self.ticks=getattr(self,'ticks',0)+1
                    if self.ticks>30 and not kwargs.get('cleanup'):raise TimeoutError()
                if flow=='deadline' and 'turn/start' in trace and not kwargs.get('cleanup'):
                    raise TimeoutError()
                if flow=='late_assessment' and outputs and not kwargs.get('cleanup'):
                    raise TimeoutError()
                return 30
            def begin_cleanup(self,reason):trace.append(('stop',reason))
            def close(self,reason):
                trace.append(('job_empty',reason));return {'job_empty':True,'within_budget':True}
        owner=Owner();owner.store=store;owner.origin=self.origin;owner.request_id=self.request;owner.lock=threading.RLock()
        wire_response=native.NativeConnection.respond
        class Wire:
            def __init__(self,owner,args,consumer,env,**kw):
                self.owner=owner;self.consumer=consumer;self.pending=deque();self.events=deque()
                self.last_rpc_error=None;self.process=SimpleNamespace(poll=lambda:None)
                self.profile=profile;self.starts=0
            def send(self,value):pass
            def call(self,method,params,**kwargs):
                trace.append(method)
                if method=='initialize':return {}
                if method=='configRequirements/read':return {}
                if method=='command/exec':
                    checks=dict.fromkeys(CANDIDATE_CHECKS,True)
                    if deny:checks[next(iter(checks))]=False
                    return {'exitCode':0,'stdout':json.dumps(checks)}
                if method=='thread/start':
                    return {'thread':{'id':outer.thread,'environments':params['environments']},
                        'model':'gpt-6-luna','reasoningEffort':'low','modelProvider':'openai',
                        'approvalPolicy':'on-request','approvalsReviewer':'user',
                        'activePermissionProfile':{'id':'har12-native'},
                        'instructionSources':[str(self.consumer/'AGENTS.md')],
                        'runtimeWorkspaceRoots':[str(self.consumer)]}
                if method=='mcpServerStatus/list':return {'data':[],'nextCursor':None}
                if method=='account/read':return {'account':{'type':'chatgpt'}}
                if method=='turn/start':
                    self.starts+=1
                    turn=outer.turn if self.starts==1 else str(uuid4())
                    outer.assertTrue((self.consumer/'case/contract.md').is_file())
                    if flow=='question_continue' and self.starts==1:
                        self.events.append({'id':7,'method':'item/tool/requestUserInput','params':{
                            'threadId':outer.thread,'turnId':turn,'questions':[{'id':'q','question':'Assess only?'}]}})
                    if not (flow=='empty_followup' and self.starts==2) and flow!='root_failed':
                        self.events.append({'method':'item/completed','params':{'threadId':outer.thread,'turnId':turn,
                            'item':{'type':'agentMessage','id':'answer','text':'The sum is wrong: [1,2] must be 3.'}}})
                    self.events.append({'method':'turn/completed','params':{'threadId':outer.thread,
                            'turn':{'id':turn,'status':'failed' if flow=='root_failed' else 'completed'}}})
                    return {'turn':{'id':turn}}
                if method=='thread/read':
                    if flow=='queued_message' and not getattr(self,'queued',False):
                        self.queued=True
                        self.pending.append({'method':'item/completed','params':{'threadId':outer.thread,'turnId':outer.turn,
                            'item':{'id':'queued_answer','type':'agentMessage','text':'For [] the result is1 instead of0.'}}})
                    if flow=='queued_question' and not getattr(self,'queued',False):
                        self.queued=True
                        self.pending.append({'id':7,'method':'item/tool/requestUserInput','params':{
                            'threadId':outer.thread,'turnId':outer.turn,'questions':[{'id':'q','question':'Assessment scope?'}]}})
                    return {'thread':{'id':outer.thread,'status':{'type':'idle'}}}
                if method=='turn/interrupt':return {}
                raise AssertionError(method)
            def event(self):
                if not self.events:raise queue.Empty()
                return self.events.popleft()
            def respond(self,request,response):wire_response(self,request,response)
            def _write(self,value):
                trace.append(('reply',value['id']))
                self.events.append({'method':'serverRequest/resolved','params':{'threadId':outer.thread,'requestId':value['id']}})
        outputs=[]
        def answer(event):
            if event['kind']=='native_decision':return {'answers':{'q':{'answers':['Assess only']}}}
            if event['kind']=='operator_decision':
                return {'action':'continue','text':'Continue the authorized assessment.'}
            if event['kind']=='assessment':
                outputs.append(event)
                if flow=='assessment_question':
                    wires[0].pending.append({'id':7,'method':'item/tool/requestUserInput','params':{
                        'threadId':outer.thread,'turnId':outer.turn,'questions':[{'id':'q','question':'Scope?'}]}})
                if flow=='stale_assessment':
                    wires[0].pending.append({'method':'item/completed','params':{'threadId':outer.thread,'turnId':outer.turn,
                        'item':{'id':'late_answer','type':'agentMessage','text':'Additional material changes the artifact.'}}})
                if flow in ('question_continue','empty_followup') and len(outputs)==1:
                    return {'status':'waiting','question':'May I continue the assessment?'}
            return {'verdict':'pass','reason':'Incorrect sum identified with a valid example.'}
        wires=[]
        original_init=Wire.__init__
        def init(wire,*args,**kwargs):
            original_init(wire,*args,**kwargs);wires.append(wire)
        Wire.__init__=init
        channel=Channel(answer)
        if flow=='disconnect':
            def poll(seconds=.1):
                if 'turn/start' in trace:raise ConnectionError()
                return None
            channel.poll=poll
        profile={'profile_id':self.profile,'reference_sha256':'f'*64}
        from native_support import digest as real_digest
        def fixture_digest(path):
            return real_digest(Path(path)) if Path(path).is_file() else delivery.CODEX_SHA256
        def install(run,apm,consumer,*args):
            from native_support import inventory
            (consumer/'AGENTS.md').write_text('installed guidance')
            return {'files':inventory(consumer,root_exclude=('.git','.tmp')),'roles':{}}
        with ExitStack() as stack:
            for target,kwargs in [
                # Exercise the Windows controller through fake transports on
                # any CI host without changing the host's global os.name.
                ('evaluation.signed_in_native.os',{'new':SimpleNamespace(name='nt',environ=os.environ,pathsep=os.pathsep)}),
                ('evaluation.signed_in_native.ROOT',{'new':project}),
                ('evaluation.signed_in_native.RequestStore',{'return_value':store}),
                ('evaluation.signed_in_native.resolve_profile',{'return_value':(home,profile)}),
                ('evaluation.signed_in_native.validate_reference',{}),
                ('evaluation.signed_in_native.require_binding',{}),
                ('evaluation.signed_in_native.shutil.which',{'return_value':'codex'}),
                ('evaluation.signed_in_native.native_environment',{'return_value':(Path('C:/synthetic/shell.exe'),{})}),
                ('evaluation.signed_in_process.AttemptProcesses',{'return_value':owner}),
                ('evaluation.signed_in_native.NativeConnection',{'new':Wire}),
                ('native_support.digest',{'side_effect':fixture_digest}),
                ('evaluation.signed_in_candidate.export_candidate',{'return_value':{'source':'fake'}}),
                ('evaluation.signed_in_candidate.install_candidate',{'side_effect':install}),
                ('evaluation.signed_in_candidate.verify_candidate',{}),
                ('evaluation.signed_in_workflow.WindowsPathLocks',{'return_value':SimpleNamespace(close=lambda:True)})]:
                stack.enter_context(patch(target,**kwargs))
            stack.enter_context(patch.dict(os.environ,CODEX_THREAD_ID=self.origin,APM_BIN='apm'))
            def runner(*args,**kwargs):
                try:
                    result=native.run_native(*args,**kwargs)
                    trace.append(('native_result',result.get('phase'),result.get('error_type'),result.get('error_code')))
                    return result
                except Exception as error:
                    trace.append(('fixture_exception',type(error).__name__,str(error)))
                    raise
            report=delivery.deliver(self.input,channel,root=project,origin=self.origin,resolver=self.resolve,native_runner=runner)
        self.assertTrue(report['cleanup_verified'], (report,trace))
        if deny:
            self.assertNotIn('turn/start',trace)
            self.assertEqual(report['execution_end'],'native_boundary_failed',trace)
            self.assertEqual(list(project.parents[1].glob('.tmp/h12-n-*/work/case')),[])
        elif flow in ('disconnect','deadline'):
            self.assertEqual(report['execution_end'],'disconnected' if flow=='disconnect' else 'deadline', trace)
            self.assertEqual(report['assessment']['verdict'],'unassessed')
            self.assertIn('turn/interrupt',trace)
        elif flow=='stale_assessment':
            self.assertEqual(report['assessment']['verdict'],'unassessed',trace)
            self.assertIn('candidate_observation_incomplete',report['limitations'])
        elif flow=='empty_followup':
            self.assertEqual(report['execution_end'],'completed',trace)
            self.assertEqual(report['assessment']['verdict'],'unassessed',trace)
            self.assertEqual(report['deliverable'],[])
            self.assertEqual(len(outputs),1)
            self.assertEqual(trace.count('turn/start'),2)
        elif flow=='root_failed':
            self.assertEqual(report['execution_end'],'failed',trace)
            self.assertEqual(report['assessment']['verdict'],'unassessed')
            self.assertIn(('job_empty','candidate_failed'),trace)
            self.assertLess(owner.ticks,30)
        else:
            self.assertEqual(report['assessment']['verdict'],'pass',trace)
            self.assertEqual(report['execution_end'],'deadline' if flow=='late_assessment' else 'completed')
            self.assertIsNotNone(report['admission'])
            self.assertIsNotNone(report['completion']['observed_at'])
            self.assertFalse(any(e['kind']=='candidate_output' for e in channel.events))
            if flow=='late_assessment':
                self.assertEqual(len(outputs),1)
                self.assertEqual(len(report['deliverable']),1)
            if flow=='queued_message':
                self.assertEqual(len(report['deliverable']),2)
                self.assertEqual(outputs[0]['body']['completion']['messages'],report['deliverable'])
            if flow=='question_continue':
                self.assertEqual(trace.count('turn/start'),2)
                self.assertEqual(trace.count(('reply',7)),1)
                self.assertEqual(len(report['deliverable']),1)
                frame=outputs[1]['body']['completion']
                self.assertEqual(len(frame['context']),1)
                self.assertTrue(all(m['turn_id']==frame['turn'] for m in frame['messages']))
                self.assertTrue(all(m['turn_id']!=frame['turn'] for m in frame['context']))
            if flow=='queued_question':self.assertEqual(trace.count(('reply',7)),1)
            if flow=='assessment_question':
                self.assertEqual(trace.count(('reply',7)),1)
                self.assertEqual(len(outputs),1)
        again=delivery.deliver(self.input,channel,root=project,origin=self.origin,
                               resolver=Mock(side_effect=AssertionError('resolved again')),
                               native_runner=Mock(side_effect=AssertionError('relaunch')))
        self.assertEqual(again,report)


if __name__=='__main__':unittest.main()
