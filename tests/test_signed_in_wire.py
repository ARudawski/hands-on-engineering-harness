"""Scripted stdio exercises real controller IO, never Codex/model acceptance."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock
import unittest
from unittest.mock import patch
from uuid import uuid4

from evaluation import signed_in_native as native
from evaluation import signed_in_profiles as profiles
from evaluation.signed_in import RequestStore
from evaluation.signed_in_interactions import NativeInteractions, marker_command
from evaluation.signed_in_process import AttemptProcesses


SERVER = r'''
import json,subprocess,sys,time
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_text())
info=data['info']; root=info['thread']['id']; turns=data['turns']
def emit(v): print(json.dumps(v),flush=True)
def done(t): emit({'method':'turn/completed','params':{'threadId':root,'turn':{'id':t,'status':'completed'}}})
for line in sys.stdin:
 v=json.loads(line)
 with Path(data['log']).open('a') as f: f.write(json.dumps(v)+'\n')
 m=v.get('method'); i=v.get('id')
 if m in data.get('rpc_errors',{}):
  response={'id':data.get('rpc_error_id',i),'error':data['rpc_errors'][m]}
  emit(response)
  if data.get('duplicate_rpc_error'):emit(response)
  continue
 if m=='initialize': emit({'id':i,'result':{}})
 elif m=='initialized': pass
 elif m=='thread/start': emit({'id':i,'result':info})
 elif m=='thread/read' and data.get('observation'):
  assert v['params']=={'threadId':root,'includeTurns':False}
  emit({'id':i,'result':{'thread':{'id':root,'source':'appServer','status':{'type':'idle'}}}})
 elif m=='thread/resume':
  assert v['params']=={'threadId':root,'excludeTurns':True}
  info['thread']['turns']=[{'id':turns[0],'status':'completed'}]
  if data.get('duplicate_history'): info['thread']['turns']*=2
  if data.get('resume_change'): info.update(data['resume_change'])
  if data.get('resume_thread_change'): info['thread'].update(data['resume_thread_change'])
  if data.get('paginated'):
   info['thread']['turns']=[]; info['turnsBackwardsCursor']='anchor'
  emit({'id':i,'result':info})
 elif m=='thread/turns/list':
  assert v['params']=={'threadId':root,'sortDirection':'asc','itemsView':'notLoaded','limit':2}
  page={'data':[{'id':turns[0],'status':'completed'}],'nextCursor':None}
  page.update(data.get('history_change',{}))
  emit({'id':i,'result':page})
 elif m=='turn/start':
  if data.get('observation'):
   t=turns[0]
   emit({'id':i,'result':{'turn':{'id':t}}})
   emit({'method':'item/completed','params':{'threadId':root,'turnId':t,'item':{
    'id':'free-form','type':'agentMessage','text':'Ordinary review: several observations. Please decide the next step.'}}})
   done(t)
   continue
  text=v['params']['input'][0]['text']
  kind='question' if 'har5_choice' in text else 'permission' if 'HAR5_APPROVED' in text else 'workflow'
  n={'question':0,'permission':1,'workflow':2}[kind]; t=turns[n]; pending_n=n
  if kind!='workflow':
   p={'threadId':root,'turnId':t,'itemId':'issued-item'}
   if n==0:
    p.update(isBlocking=True,questions=[{'header':'Label','id':'har5_choice',
      'question':'Which label should the public probe use?',
      'options':[{'label':'Alpha','description':'A'},{'label':'Beta','description':'B'}]}])
   else:
    p.update(startedAtMs=1,command=data['command'],cwd=info['cwd'])
    if 'callback_environment' in data: p['environmentId']=data['callback_environment']
    p.update(data.get('permission_change',{}))
   p.update(data.get('callback_change',{}))
   emit({'id':17 if data.get('reuse_callback_id') else 17+n,'method':'item/tool/requestUserInput' if n==0 else 'item/commandExecution/requestApproval','params':p})
   if data.get('duplicate_callback'): emit({'id':17+n,'method':'item/tool/requestUserInput','params':p})
  emit({'id':i,'result':{'turn':{'id':t}}})
  if n==2: done(t)
 elif 'result' in v:
  n=pending_n; t=turns[n]
  expected={'answers':{'har5_choice':{'answers':['Alpha']}}} if n==0 else {'decision':'accept'}
  assert v['result']==expected
  if n==1:
   output=subprocess.check_output([sys.executable,'-I','-B','-c',"print('HAR5_APPROVED')"],text=True)
   emit({'method':'item/completed','params':{'threadId':root,'turnId':t,'item':{
    'id':'issued-item','type':'commandExecution','command':data['command'],
    'status':'completed','exitCode':0,'aggregatedOutput':output}}})
  emit({'method':'serverRequest/resolved','params':{'threadId':root,'requestId':i}})
  done(t)
 else: emit({'id':i,'error':{'message':'SYNTHETIC_SECRET'}})
if data.get('hang_exit'): time.sleep(30)
'''


@unittest.skipUnless(os.name == 'nt', 'owned native transport uses Windows Jobs')
class NativeWire(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.root = self.base/'Harness/project'; self.root.mkdir(parents=True)
        self.consumer = self.base/'consumer'; self.consumer.mkdir()
        (self.consumer/'AGENTS.md').write_text('PUBLIC_GUIDANCE')
        self.home = self.base/'.tmp/h12-n-12345678'/('auth-profile-'+str(uuid4()))
        self.home.mkdir(parents=True)
        (self.home/'auth.json').write_text('SYNTHETIC_SECRET')
        self.store = RequestStore(self.root/'.tmp/evaluation-signed-in')
        self.origin, self.request_id, self.thread, profile_id = (str(uuid4()) for _ in range(4))
        setup = {'operation_id':profile_id, 'home':str(self.home), 'status':'authenticated_only',
            'account_type':'chatgpt', 'cleanup_verified':True, 'model_turns':0, 'evaluated_requests':0,
            'credentials_copied':False, 'job_cleanup':{'job_empty':True,'within_budget':True,
                'closure_failed':False,'termination_failed':False}}
        self.ref = profiles.register_profile(self.store,self.origin,setup,'a'*64,root=self.root)
        request = self.store.submit(self.origin,self.request_id,'native-foundation',30)
        native.bind_mode(self.store,self.origin,self.request_id,'diagnose',{'model':'gpt-6-luna','effort':'low'},self.ref)
        profiles.bind_root(self.store,self.origin,self.request_id,self.thread,self.ref)
        self.store.claim_launch(self.origin,self.request_id)
        self.owner = AttemptProcesses(self.store,self.origin,request)
        self.addCleanup(self.close_owner)
        self.patching = patch.object(native,'ROOT',self.root); self.patching.start()
        self.addCleanup(self.patching.stop)
        self.turns = [str(uuid4()) for _ in range(3)]
        info = {'model':'gpt-6-luna','modelProvider':'openai','reasoningEffort':'low',
            'cwd':str(self.consumer),'runtimeWorkspaceRoots':[str(self.consumer)],
            'approvalPolicy':'on-request','approvalsReviewer':'user',
            'activePermissionProfile':{'id':'har12-native'},'sandbox':{'type':'workspaceWrite'},
            'instructionSources':[str(self.consumer/'AGENTS.md')],
            'thread':{'id':self.thread,'sessionId':self.thread,'cwd':str(self.consumer),
                'modelProvider':'openai','source':'cli','cliVersion':'TEST_SCRIPT',
                'ephemeral':False,'turns':[]}}
        self.log = self.base/'wire.jsonl'
        self.data = {'info':info,'turns':self.turns,'log':str(self.log),'command':marker_command(sys.executable)}
        self.data_path = self.base/'server.json'; self.save_data()
        self.server = self.base/'server.py'; self.server.write_text(SERVER)

    def close_owner(self):
        result = getattr(self, 'closed_cleanup', None)
        if result is None:
            result = self.owner.close('interrupted')
        self.assertTrue(result['job_empty'])
        self.assertTrue(result['within_budget'])

    def save_data(self):
        self.data_path.write_text(json.dumps(self.data))

    def connect(self, attach=True):
        connection = native.NativeConnection(self.owner,[sys.executable,'-I','-u',str(self.server),str(self.data_path)],
            self.consumer,os.environ.copy(),mode='diagnose',profile=self.ref)
        connection.call('initialize',{'clientInfo':{'name':'test','version':'1'}})
        connection.send({'method':'initialized'})
        connection.call('thread/start',{})
        if not attach: return connection
        return NativeInteractions(connection,python_executable=sys.executable)

    def to_checkpoint(self, adapter):
        self.assertEqual(adapter.start('question'),self.turns[0])
        for _ in range(3): adapter.event()

    def test_rpc_errors_keep_only_safe_correlated_method_and_standard_code(self):
        secret='SYNTHETIC_SECRET'
        self.data['rpc_errors']={'configRequirements/read':{'code':-32600,'message':secret,'data':{'token':secret}},
                                'command/exec':{'code':-32602,'message':secret}}
        self.save_data();conn=self.connect(attach=False)
        first=conn.begin('configRequirements/read',{});second=conn.begin('command/exec',{})
        with self.assertRaisesRegex(RuntimeError,'^native_rpc_failed$'):conn.wait(second)
        self.assertEqual(conn.last_rpc_error,{'method':'command/exec','code':-32602,'kind':'invalid_params'})
        self.assertNotIn(secret,json.dumps(conn.last_rpc_error));self.assertIn(first,conn.request_methods)
        with self.assertRaisesRegex(RuntimeError,'^native_rpc_failed$'):conn.wait(first)
        self.assertEqual(conn.last_rpc_error,{'method':'configRequirements/read','code':-32600,'kind':'invalid_request'})
        self.assertEqual(conn.request_methods,{});self.assertNotIn(secret,json.dumps(conn.last_rpc_error))

    def test_rpc_response_id_rejects_foreign_malformed_and_consumed_duplicate(self):
        for invalid in (999999,True,'SYNTHETIC_SECRET'):
            with self.subTest(response_id=invalid):
                self.data.update(rpc_errors={'command/exec':{'code':-32600,'message':'SYNTHETIC_SECRET'}},rpc_error_id=invalid)
                self.save_data();conn=self.connect(attach=False)
                with self.assertRaisesRegex(RuntimeError,'^native_protocol_failed$'):conn.call('command/exec',{})
                self.assertIsNone(conn.last_rpc_error)
        self.data.pop('rpc_error_id');self.data['duplicate_rpc_error']=True
        self.save_data();conn=self.connect(attach=False)
        with self.assertRaisesRegex(RuntimeError,'^native_rpc_failed$'):conn.call('command/exec',{})
        with self.assertRaisesRegex(RuntimeError,'^native_protocol_failed$'):conn.receive()

    def test_rpc_unknown_numeric_or_malformed_error_never_exports_raw_payload(self):
        for value in ({'code':987654321,'message':'SYNTHETIC_SECRET'},{'code':True,'data':'SYNTHETIC_SECRET'},'SYNTHETIC_SECRET'):
            self.data['rpc_errors']={'command/exec':value};self.save_data();conn=self.connect(attach=False)
            with self.assertRaisesRegex(RuntimeError,'^native_rpc_failed$'):conn.call('command/exec',{})
            self.assertEqual(conn.last_rpc_error,{'method':'command/exec','code':None,'kind':'unknown'})

    def test_candidate_observer_uses_native_wire_without_phase_or_answer_schema(self):
        from evaluation.signed_in_workflow import CandidateObservation
        self.data['observation'] = True; self.save_data()
        connection = self.connect(attach=False)
        with self.store.request(self.origin,self.request_id) as state:
            state.update(native_purpose='candidate-observe',candidate_revision='a'*40,
                         candidate_admission={'root':self.thread})  # Explicit synthetic wire fixture, not admission proof.
        result = {'root_thread_id':self.thread,'boundary_passed':True,'installation':{'files':{}}}
        observer = CandidateObservation(connection,result,lambda:None,consumer=self.consumer,marker='PROTECTED_CANARY')
        try:
            report = observer.run()
            self.assertEqual(report['execution_end'],'completed')
            self.assertEqual(report['task_assessment'],'unassessed')
            self.assertIn('Please decide',report['agent_messages'][0]['text'])
            with self.assertRaisesRegex(RuntimeError,'^native_method_blocked$'):
                connection.call('turn/start',{'threadId':self.thread,'input':[]})
            with self.assertRaisesRegex(RuntimeError,'^native_method_blocked$'):
                connection.call('thread/read',{'threadId':str(uuid4()),'includeTurns':False})
        finally:
            cleanup = self.closed_cleanup = self.owner.close('interrupted')
            self.assertTrue(observer.close_after_stop(cleanup['job_empty']))

    def test_complete_wire_sequence_same_attempt_and_budget(self):
        adapter = self.connect()
        before = self.store.get(self.origin,self.request_id)
        self.to_checkpoint(adapter)
        old = adapter.connection.process
        adapter.resume()
        self.assertIsNotNone(old.poll())
        self.assertIs(adapter.connection.owner,self.owner)
        self.assertEqual(adapter.start('permission'),self.turns[1])
        for _ in range(4): adapter.event()
        adapter.start('workflow')
        self.assertEqual(adapter.event(),'workflow_held_unassessed')
        with self.assertRaises(ValueError): adapter.start('workflow')
        after = self.store.get(self.origin,self.request_id)
        for key in ('attempt_id','deadline','seconds'): self.assertEqual(before[key],after[key])
        writes = [json.loads(s) for s in self.log.read_text().splitlines()]
        self.assertEqual([v for v in writes if v.get('method')=='thread/resume'][0]['params'],
            {'threadId':self.thread,'excludeTurns':True})
        self.assertEqual(len([v for v in writes if 'result' in v]),2)
        self.assertEqual(len([v for v in writes if v.get('method')=='thread/start']),1)

    def test_default_transport_still_rejects_callbacks_and_raw_resume(self):
        connection = self.connect(False)
        for v in ({'id':17,'result':{}},{'id':7,'method':'thread/resume','params':{'threadId':self.thread}},
                  {'id':8,'method':'thread/turns/list','params':{'threadId':self.thread}}):
            with self.assertRaisesRegex(RuntimeError,'^native_method_blocked$'): connection.send(v)
        with self.assertRaisesRegex(RuntimeError,'^native_callback_blocked$'):
            connection.call('turn/start',{'threadId':self.thread,'input':[{'type':'text','text':'har5_choice'}]})

    def test_foreign_callback_never_replies(self):
        self.data['callback_change']={'threadId':str(uuid4())}; self.save_data()
        adapter = self.connect()
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.start('question')
        self.assertNotIn('result',[k for v in map(json.loads,self.log.read_text().splitlines()) for k in v])

    def test_forged_callback_and_changed_inventory_never_write(self):
        adapter = self.connect(); adapter.start('question')
        callback = adapter.connection.event()
        forged = json.loads(json.dumps(callback)); forged['params']['questions'][0]['question']='SYNTHETIC_SECRET'
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.reply(forged)
        (self.consumer/'AGENTS.md').write_text('CHANGED')
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.reply(callback)
        self.assertNotIn('result',[k for v in map(json.loads,self.log.read_text().splitlines()) for k in v])

    def test_reply_consumed_before_uncertain_write_no_retry(self):
        adapter = self.connect(); adapter.start('question'); callback=adapter.connection.event()
        with patch.object(adapter.connection,'_write',side_effect=BrokenPipeError('SYNTHETIC_SECRET')):
            with self.assertRaisesRegex(RuntimeError,'^native_interaction_failed$'): adapter.reply(callback)
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.reply(callback)

    def test_resume_rejects_metadata_drift_and_cannot_repeat(self):
        adapter=self.connect(); self.to_checkpoint(adapter)
        self.data['resume_change']={'reasoningEffort':'medium'}; self.save_data()
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.resume()
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.resume()

    def test_closed_admission_blocks_late_reply_and_resume(self):
        adapter=self.connect(); adapter.start('question'); callback=adapter.connection.event()
        self.store.stop(self.origin,self.request_id,'interrupted')
        with self.assertRaises((ValueError,RuntimeError,TimeoutError)): adapter.reply(callback)
        with self.assertRaises((ValueError,RuntimeError,TimeoutError)): adapter.resume()

    def test_disconnect_failure_does_not_restart(self):
        self.data['hang_exit']=True; self.save_data()
        adapter=self.connect(); self.to_checkpoint(adapter)
        wait = adapter.connection.process.wait
        with patch.object(adapter.connection.process,'wait',side_effect=lambda timeout:wait(timeout=min(.1,timeout))):
            with self.assertRaisesRegex(RuntimeError,'^native_interaction_failed$'): adapter.resume()
        self.assertEqual(len(self.owner.processes),1)

    def test_duplicate_callback_before_ack_cannot_be_answered(self):
        self.data['duplicate_callback']=True; self.save_data()
        adapter=self.connect()
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.start('question')
        self.assertFalse(any('result' in v for v in map(json.loads,self.log.read_text().splitlines())))

    def test_paginated_resume_reads_exact_attributed_checkpoint(self):
        self.data['paginated']=True; self.save_data()
        adapter=self.connect(); self.to_checkpoint(adapter)
        adapter.resume()
        self.assertEqual(adapter.resume_history_source,'thread/turns/list')
        with self.store.request(self.origin,self.request_id) as state:
            self.assertEqual(state['native_interaction']['resume_history_read'],
                {'root':self.thread,'rpc_id':adapter.resume_history_request_id})
        self.assertEqual(adapter.start('permission'),self.turns[1])

    def test_paginated_history_with_remaining_page_is_not_checkpoint_proof(self):
        self.data.update(paginated=True,history_change={'nextCursor':'OLDER'}); self.save_data()
        adapter=self.connect(); self.to_checkpoint(adapter)
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.resume()
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.start('permission')

    def test_paginated_foreign_or_unfinished_turn_cannot_confirm_resume(self):
        self.data.update(paginated=True,history_change={'data':[{'id':str(uuid4()),'status':'completed'}]})
        self.save_data(); adapter=self.connect(); self.to_checkpoint(adapter)
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.resume()

    def test_optional_model_metadata_is_compared_by_effective_value(self):
        self.data['resume_thread_change']={'model':'gpt-6-luna','reasoningEffort':'low'};self.save_data()
        adapter=self.connect();self.to_checkpoint(adapter);adapter.resume()
        self.assertEqual(adapter.start('permission'),self.turns[1])

    def test_specific_driver_stops_after_permission_without_workflow_or_reviewers(self):
        self.data['paginated']=True;self.save_data()
        adapter=self.connect(); result={}; save=Mock()
        native.run_interaction_probe(adapter,result,save)
        self.assertTrue(result['interaction_probe_completed'])
        self.assertEqual(set(result['interactions']),{'question','resume','permission'})
        self.assertTrue(all(row['completed'] for row in result['interactions'].values()))
        turns=[v for v in map(json.loads,self.log.read_text().splitlines()) if v.get('method')=='turn/start']
        self.assertEqual(len(turns),2)

    def test_server_request_ids_restart_only_after_confirmed_reconnect(self):
        self.data.update(paginated=True,reuse_callback_id=True);self.save_data()
        adapter=self.connect();result={}
        native.run_interaction_probe(adapter,result,lambda:None)
        self.assertTrue(result['interaction_probe_completed'])
        with self.store.request(self.origin,self.request_id) as state:
            cp=state['native_interaction']
            self.assertEqual(cp['callback_epoch'],1)
            self.assertEqual(len(cp['callback_ids']),2)
            self.assertNotEqual(cp['callback_ids'][0],cp['callback_ids'][1])

    def test_permission_accepts_only_the_environment_bound_to_actual_root(self):
        environment={'environmentId':'selected-environment','cwd':str(self.consumer),
                     'runtimeWorkspaceRoots':[str(self.consumer)]}
        self.data['info']['thread']['environments']=[environment]
        self.data['callback_environment']='selected-environment';self.save_data()
        adapter=self.connect();result={}
        native.run_interaction_probe(adapter,result,lambda:None)
        self.assertTrue(result['interaction_probe_completed'])

    def test_permission_rejects_foreign_environment(self):
        self.data['info']['thread']['environments']=[{'environmentId':'selected-environment',
            'cwd':str(self.consumer),'runtimeWorkspaceRoots':[str(self.consumer)]}]
        self.data['callback_environment']='foreign-environment';self.save_data()
        adapter=self.connect();result={}
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'):
            native.run_interaction_probe(adapter,result,lambda:None)
        self.assertFalse(result.get('interaction_probe_completed',False))
        replies=[v for v in map(json.loads,self.log.read_text().splitlines()) if 'result' in v]
        self.assertEqual(len(replies),1)

    def test_native_policy_proposals_receive_only_one_command_acceptance(self):
        self.data['permission_change']={
            'proposedExecpolicyAmendment':['SYNTHETIC_SECRET'],
            'proposedNetworkPolicyAmendments':[{'host':'SYNTHETIC_SECRET','action':'allow'}],
            'availableDecisions':['accept','acceptForSession',
                {'acceptWithExecpolicyAmendment':{'execpolicy_amendment':['SYNTHETIC_SECRET']}}]}
        self.save_data()
        adapter=self.connect();result={}
        native.run_interaction_probe(adapter,result,lambda:None)
        self.assertTrue(result['interaction_probe_completed'])
        replies=[v for v in map(json.loads,self.log.read_text().splitlines()) if 'result' in v]
        self.assertEqual(len(replies),2)
        self.assertEqual(replies[-1]['result'],{'decision':'accept'})
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(adapter.callback_observations))

    def test_root_environment_must_have_exact_consumer_scope(self):
        self.data['info']['thread']['environments']=[{'environmentId':'selected-environment',
            'cwd':str(self.consumer/'other'),'runtimeWorkspaceRoots':[str(self.consumer)]}]
        self.save_data()
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'):self.connect()

    def test_callback_observations_exclude_raw_rejected_values(self):
        self.data['callback_change']={'environmentId':'SYNTHETIC_SECRET'};self.save_data()
        adapter=self.connect();self.to_checkpoint(adapter);adapter.resume()
        adapter.start('permission')
        callback=adapter.connection.event()
        for _ in range(2):
            with self.assertRaises(ValueError):adapter.reply(callback)
        observations=adapter.callback_observations
        self.assertEqual(len(observations),2)
        self.assertEqual(observations[-1]['kind'],'command')
        self.assertFalse(observations[-1]['environment_matches'])
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(observations))
        self.assertTrue(all(type(v) is bool for row in observations for k,v in row.items() if k!='kind'))

    def test_duplicate_resume_turns_are_ambiguous(self):
        adapter=self.connect(); self.to_checkpoint(adapter)
        self.data['duplicate_history']=True; self.save_data()
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.resume()

    def test_profile_drift_rejects_pending_reply_without_consuming_it(self):
        adapter=self.connect(); adapter.start('question'); callback=adapter.connection.event()
        (self.home/'.env').write_text('SYNTHETIC_SECRET')
        with self.assertRaisesRegex(RuntimeError,'^profile_binding_changed$'): adapter.reply(callback)
        self.assertEqual(len(adapter.callbacks),1)
        with self.store.request(self.origin,self.request_id) as state:
            self.assertEqual(state['native_interaction']['phase'],'question_active')

    def test_resume_requires_actual_metadata_and_completed_checkpoint(self):
        adapter=self.connect()
        with self.assertRaisesRegex(ValueError,'^interaction_rejected$'): adapter.resume()
        self.assertEqual(len(self.owner.processes),1)

    def test_deadline_closure_persists_and_late_callback_never_writes(self):
        adapter=self.connect(); adapter.start('question'); callback=adapter.connection.event()
        wall, mono=self.store.clock()
        self.store.clock=lambda:(wall+30,mono+30)
        with self.assertRaises((ValueError,RuntimeError,TimeoutError)): adapter.reply(callback)
        self.assertFalse(self.store.get(self.origin,self.request_id)['admission_open'])


if __name__ == '__main__': unittest.main()
