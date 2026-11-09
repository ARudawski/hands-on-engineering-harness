"""Fabricated values check admission/assessment guards, never native acceptance."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from evaluation import signed_in_native as native
from evaluation.signed_in import RequestStore
from evaluation.signed_in_workflow import LegacyWorkflowFixture as WorkflowFixture, assess_report, checked_json, expected_fixture_hashes, own_read, received_skill, received_review_task, collaboration_code, NESTED, CODE_MODE_GUIDANCE
from evaluation.signed_in_fixture import WindowsPathLocks
from evaluation.signed_in_worker import CHECKS, CASE_READS, fixture_snapshot
from evaluation.worker import native_foundation_files


def examples(actual=False):
    return [dict(input=list(case),expected=sum(case),**({'actual':sum(case)+1} if actual else {})) for case in ((2,3),())]


class FixtureGuards(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.base=Path(directory.name);self.consumer=self.base/'consumer';self.consumer.mkdir();(self.consumer/'.tmp').mkdir()
        self.origin,self.request,self.root=(str(uuid4()) for _ in range(3))
        self.store=RequestStore(self.base/'store');self.store.submit(self.origin,self.request,'native-foundation',120)
        self.store.claim_launch(self.origin,self.request)
        with self.store.request(self.origin,self.request) as state:
            state.update(native_root=self.root,native_purpose='workflow-fixture')
        owner=SimpleNamespace(store=self.store,origin=self.origin,request_id=self.request,remaining=lambda *a,**k:90)
        self.connection=SimpleNamespace(owner=owner,call=Mock(side_effect=RuntimeError('uncertain_write')))
        self.result={'root_thread_id':self.root,'children':{},'boundary_passed':False}
        if os.name!='nt':
            locks=patch('evaluation.signed_in_workflow.WindowsPathLocks');locks.start();self.addCleanup(locks.stop)
        self.probe=WorkflowFixture(self.connection,self.result,lambda:None,consumer=self.consumer,home=self.base,
            marker='SYNTHETIC_SECRET',preflight='PREFLIGHT',inspect='INSPECT',command={'command':['shell','PREFLIGHT']})
        self.addCleanup(self.probe.close_after_stop,True)

    def test_unverified_bootstrap_never_releases_fixture(self):
        with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):self.probe.materialize()
        self.assertFalse(self.probe.fixture.exists())
        self.connection.call.assert_not_called()

    def test_unverified_received_bootstrap_task_blocks_fixture_release(self):
        self.probe.root_turn=str(uuid4());children=[str(uuid4()),str(uuid4())]
        self.probe.bootstrap_turns={c:str(uuid4()) for c in children}
        self.probe._change('bootstrap_ready','bootstrap_active')
        self.result.update(boundary_passed=True,children={c:{'completed':True,'assessment_status':'received',
            'role':role,'isolation_reads':{'task_read':True,'protected_reads':True}}
            for c,role in zip(children,('plan-reviewer','code-reviewer'))})
        self.probe.context_gate=Mock();self.probe.snapshot=Mock()
        self.probe.task_gate=Mock(side_effect=RuntimeError('workflow_probe_incomplete'))
        for capability in (False,None,1,'SYNTHETIC_SECRET','MISSING'):
            def read(method,params):
                thread=params['threadId'];turn=self.probe.root_turn if thread==self.root else self.probe.bootstrap_turns[thread]
                info={'id':thread,'turns':[{'id':turn,'status':'completed'}]}
                if capability!='MISSING':info['canAcceptDirectInput']=capability
                return {'thread':info}
            self.connection.call=Mock(side_effect=read)
            with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):self.probe.materialize()
            self.probe.snapshot.assert_not_called()
            self.assertFalse(self.probe.fixture.exists())
            self.assertNotIn('SYNTHETIC_SECRET',json.dumps(self.result))

    def test_parent_route_observes_capability_but_never_starts_children_directly(self):
        self.probe.root_turn=str(uuid4());children=[str(uuid4()),str(uuid4())]
        self.probe.bootstrap_turns={c:str(uuid4()) for c in children}
        self.result['children']={c:{} for c in children}
        def read(method,params):
            thread=params['threadId'];turn=self.probe.root_turn if thread==self.root else self.probe.bootstrap_turns[thread]
            return {'thread':{'id':thread,'turns':[{'id':turn,'status':'completed'}],'canAcceptDirectInput':False}}
        self.connection.call=Mock(side_effect=read);self.probe.checkpoints()
        self.assertEqual(self.result['reviewer_direct_input_capability'],{c:False for c in children})
        self.assertTrue(all(c.args[0]=='thread/read' for c in self.connection.call.call_args_list))
        self.connection.call=Mock(return_value={'thread':{'id':str(uuid4()),'canAcceptDirectInput':True}})
        with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):self.probe.checkpoints()

    def test_uncertain_turn_send_consumes_phase_intent_without_retry(self):
        with self.assertRaisesRegex(RuntimeError,'^uncertain_write$'):self.probe.run_turn('bootstrap','PUBLIC')
        with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):self.probe.run_turn('bootstrap','PUBLIC')
        self.assertEqual(self.connection.call.call_count,1)
        with self.store.request(self.origin,self.request) as state:
            self.assertEqual(state['native_workflow']['phase'],'bootstrap_starting')

    def test_foreign_closed_or_duplicate_controller_cannot_restart(self):
        with self.assertRaises(RuntimeError):self.probe._change('admitted','workflow_starting')
        with self.assertRaises(RuntimeError):
            WorkflowFixture(self.connection,self.result,lambda:None,consumer=self.consumer,home=self.base,
                marker='x',preflight='PREFLIGHT',inspect='INSPECT',command={'command':['shell','PREFLIGHT']})
        self.store.stop(self.origin,self.request,'interrupted')
        with self.assertRaises(RuntimeError):self.probe._change('bootstrap_ready','bootstrap_starting')

    def test_fixture_drift_blocks_next_model_call(self):
        self.probe.fixture.mkdir()
        for name,text in native_foundation_files().items():(self.probe.fixture/name).write_text(text,encoding='utf-8',newline='\n')
        self.probe.expected=expected_fixture_hashes()
        (self.probe.fixture/'after.py').write_text('SYNTHETIC_SECRET')
        self.connection.call=Mock(return_value={'exitCode':0,'stdout':json.dumps(fixture_snapshot(self.consumer))})
        with self.assertRaises(RuntimeError):self.probe.run_turn('workflow','PUBLIC')
        self.assertTrue(self.result['fixture_drift']);self.assertEqual(self.connection.call.call_count,1)
        self.assertEqual(self.connection.call.call_args.args[0],'command/exec')

    def test_locks_are_not_released_before_job_empty(self):
        handle=Mock();self.probe.locks.append(handle)
        self.assertFalse(self.probe.close_after_stop(False));handle.close.assert_not_called()
        self.assertTrue(self.probe.close_after_stop(True));handle.close.assert_called_once_with()

    def test_snapshot_rejects_unbounded_or_unknown_fields(self):
        for output in ['x'*16385,json.dumps({'hashes':{},'extra_files':False,'record_present':False,'extra':'value'})]:
            self.connection.call=Mock(return_value={'exitCode':0,'stdout':output})
            with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):self.probe.snapshot()

    def test_mixed_or_non_low_workflow_request_allocates_nothing(self):
        with patch.object(native,'RequestStore') as factory:
            for flags in [dict(mode='prepare',workflow_probe=True),dict(mode='diagnose',workflow_probe='yes'),
                dict(mode='diagnose',workflow_probe=True,interaction_probe=True),
                dict(mode='diagnose',workflow_probe=True,isolation_probe=True),
                dict(mode='prepare',parent_review_probe=True),dict(mode='diagnose',parent_review_probe='yes'),
                dict(mode='diagnose',parent_review_probe=True,workflow_probe=True),
                dict(mode='diagnose',parent_review_probe=True,isolation_probe=True)]:
                with self.assertRaises(ValueError):native.run_native({},**flags)
            factory.assert_not_called()

    def test_bootstrap_events_bind_two_own_reviewers_before_case_release(self):
        turn=str(uuid4());child_ids=[str(uuid4()),str(uuid4())];events=[]
        def item(thread,t,value):return {'method':'item/completed','params':{'threadId':thread,'turnId':t,'item':value}}
        def done(thread,t):return {'method':'turn/completed','params':{'threadId':thread,'turn':{'id':t,'status':'completed'}}}
        events.append(item(self.root,turn,{'type':'commandExecution','command':'PREFLIGHT','status':'completed','exitCode':0,
            'aggregatedOutput':json.dumps({k:True for k in CHECKS})}))
        for child in child_ids:
            child_turn=str(uuid4())
            events.append({'method':'item/started','params':{'threadId':self.root,'turnId':turn,'item':{
                'type':'subAgentActivity','kind':'started','agentThreadId':child}}})
            events.extend([item(child,child_turn,{'type':'commandExecution','command':'INSPECT','status':'completed',
                'exitCode':0,'aggregatedOutput':json.dumps({'task_read':True,'protected_reads':True})}),
                item(child,child_turn,{'type':'agentMessage','phase':'final_answer','text':'PUBLIC_ASSESSMENT'}),done(child,child_turn)])
        events.append(done(self.root,turn))
        self.connection.call=Mock(return_value={'turn':{'id':turn}});self.connection.event=Mock(side_effect=events)
        self.probe.run_turn('bootstrap','PUBLIC')
        self.assertTrue(self.result['boundary_passed']);self.assertEqual(set(self.result['children']),set(child_ids))
        self.assertTrue(all(c['completed'] and c['assessment_status']=='received' for c in self.result['children'].values()))
        self.assertFalse(self.probe.fixture.exists())

    def test_parent_review_turn_binds_original_children_own_reads_and_interactions(self):
        self.probe.reviewers_only=True
        with self.store.request(self.origin,self.request) as state:state['native_purpose']='parent-review-fixture'
        self.probe._change('bootstrap_ready','workflow_held',workflow_held=True)
        turn=str(uuid4());child_ids=[str(uuid4()),str(uuid4())];events=[]
        self.result['children']={c:{'role':role} for c,role in zip(child_ids,('plan-reviewer','code-reviewer'))}
        self.probe.bootstrap_turns={c:str(uuid4()) for c in child_ids}
        for child,role in zip(child_ids,('plan-reviewer','code-reviewer')):
            t=str(uuid4())
            events.append({'method':'item/completed','params':{'threadId':self.root,'turnId':turn,
                'item':{'type':'subAgentActivity','kind':'interacted','agentThreadId':child}}})
            operations=('case-contract','case-plan') if role=='plan-reviewer' else ('case-contract','case-before','case-after')
            for op in operations:
                command=native.powershell_probe(self.consumer/'h12-probe.py',op)
                events.append({'method':'item/completed','params':{'threadId':child,'turnId':t,'item':{
                    'type':'commandExecution','command':command,'status':'completed','exitCode':0,
                    'aggregatedOutput':native_foundation_files()[CASE_READS[op]]}}})
            events.extend([{'method':'item/completed','params':{'threadId':child,'turnId':t,'item':{
                'type':'agentMessage','phase':'final_answer','text':'{}'}}},
                {'method':'turn/completed','params':{'threadId':child,'turn':{'id':t,'status':'completed'}}}])
        events.insert(0,{'method':'turn/completed','params':{'threadId':self.root,'turn':{'id':turn,'status':'completed'}}})
        old_root=str(uuid4());self.probe.root_turns.add(old_root)
        events.insert(0,{'method':'item/completed','params':{'threadId':self.root,'turnId':old_root,
            'item':{'type':'subAgentActivity','kind':'completed','agentThreadId':child_ids[0]}}})
        self.connection.call=Mock(return_value={'turn':{'id':turn}});self.connection.event=Mock(side_effect=events)
        tasks=[{'target':t,'message':'TRUSTED PUBLIC '+t} for t in child_ids]
        prompt=collaboration_code('followup_task',tasks);self.probe.run_turn('reviews',prompt)
        self.assertEqual(set(self.probe.review_turns),set(child_ids))
        calls=self.connection.call.call_args_list
        self.assertEqual(len(calls),1);self.assertEqual(calls[0].args[1]['threadId'],self.root)
        self.assertEqual(calls[0].args[1]['input'],[{'type':'text','text':prompt}])
        self.assertEqual(self.probe.interacted,set(child_ids))
        self.assertIs(self.result['evaluated_case_dispatched'],True)
        self.assertEqual(self.probe.reads[child_ids[1]],{'contract.md','before.py','after.py'})

    def test_unsolicited_new_reviewer_during_workflow_hold_is_rejected(self):
        self.probe._change('bootstrap_ready','admitted')
        turn=str(uuid4())
        self.connection.call=Mock(return_value={'turn':{'id':turn}})
        self.connection.event=Mock(return_value={'method':'item/started','params':{'threadId':self.root,'turnId':turn,
            'item':{'type':'subAgentActivity','kind':'started','agentThreadId':str(uuid4())}}})
        with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):self.probe.run_turn('workflow','PUBLIC',skill=True)
        sent=self.connection.call.call_args.args[1]['input']
        self.assertEqual(sent[-1]['type'],'skill');self.assertEqual(sent[-1]['name'],'deliver-task')

    def test_review_rejects_execution_instead_of_assigned_read_only_commands(self):
        self.probe._change('bootstrap_ready','workflow_held',workflow_held=True)
        turn,child,child_turn=(str(uuid4()) for _ in range(3))
        other=str(uuid4());self.result['children']={child:{'role':'code-reviewer'},other:{'role':'plan-reviewer'}}
        self.probe.bootstrap_turns={t:str(uuid4()) for t in (child,other)}
        self.connection.call=Mock(return_value={'turn':{'id':turn}})
        self.connection.event=Mock(return_value={'method':'item/started','params':{'threadId':child,'turnId':child_turn,
            'item':{'type':'commandExecution','command':'python after.py'}}})
        with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):
            self.probe.run_turn('reviews','PUBLIC')
        self.assertNotIn('fixture_review_assessments',self.result)

    def test_native_only_root_starts_and_each_phase_intent_is_single_use(self):
        child=str(uuid4());other=str(uuid4())
        self.probe._change('bootstrap_ready','reviews_starting',admitted_reviewers={child:'code-reviewer'},review_intents={child:'ready'})
        conn=object.__new__(native.NativeConnection)
        conn.owner=self.connection.owner;conn.owner.lock=threading.RLock()
        conn.mode='diagnose';conn.profile={'profile_id':'PUBLIC'};conn._write=Mock()
        with patch.object(native,'require_binding') as binding:
            with self.assertRaisesRegex(RuntimeError,'^native_method_blocked$'):
                conn.send({'method':'turn/start','params':{'threadId':child}})
            conn.send({'method':'turn/start','params':{'threadId':self.root}})
            self.assertEqual(binding.call_args.kwargs['root_thread'],self.root)
            for target in (child,other,self.root):
                with self.assertRaisesRegex(RuntimeError,'^native_method_blocked$'):
                    conn.send({'method':'turn/start','params':{'threadId':target}})
        conn._write.assert_called_once()

    def test_received_review_task_rejects_coaching_opaque_or_extra_inputs(self):
        turn=str(uuid4());context={'type':'turn_context','payload':{'turn_id':turn}}
        paths={'parent_path':'/root','child_path':'/root/isolation_code_reviewer'}
        envelope='Message Type: NEW_TASK\nTask name: /root/isolation_code_reviewer\nSender: /root\nPayload:\nPUBLIC TASK'
        task={'type':'response_item','payload':{'type':'agent_message','author':'/root',
            'recipient':paths['child_path'],'content':[{'type':'input_text','text':envelope}]}}
        self.assertTrue(received_review_task([context,task],turn,'PUBLIC TASK',**paths))
        for rows in [[task,context],[context,task,task],
                     [context,task,{'type':'response_item','payload':{'type':'agent_message','content':[{'type':'encrypted_content','encrypted_content':'OPAQUE'}]}}]]:
            self.assertFalse(received_review_task(rows,turn,'PUBLIC TASK',**paths))
        self.assertFalse(received_review_task([context,task],turn,'PUBLIC TASK plus answer',**paths))
        for field in ('author','recipient'):
            bad={'type':'response_item','payload':{**task['payload'],field:'/foreign'}}
            self.assertFalse(received_review_task([context,bad],turn,'PUBLIC TASK',**paths))
        user={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'coaching'}]}}
        self.assertFalse(received_review_task([context,task,user],turn,'PUBLIC TASK',**paths))

    def test_task_gate_requires_exact_full_native_history_and_metadata(self):
        child=str(uuid4());first=str(uuid4());second=str(uuid4());path='/root/isolation_code_reviewer'
        self.result['children']={child:{'role':'code-reviewer'}}
        meta={'type':'session_meta','payload':{'id':child,'parent_thread_id':self.root,'agent_path':path}}
        def message(role,text):return {'type':'response_item','payload':{'type':'message','role':role,
            'content':[{'type':'input_text','text':text}]}}
        config=self.consumer/'.codex/agents';config.mkdir(parents=True)
        (config/'code-reviewer.toml').write_text('developer_instructions="ORIGINAL_ROLE"',encoding='utf-8')
        rows=[meta,message('developer','NATIVE_POLICY'),message('developer','ORIGINAL_ROLE'),
            message('developer',CODE_MODE_GUIDANCE),message('user','NATIVE_CONTEXT')]
        for turn,task_text in [(first,'BOOTSTRAP'),(second,'REVIEW')]:
            rows.extend([{'type':'turn_context','payload':{'turn_id':turn}},
                {'type':'response_item','payload':{'type':'agent_message','author':'/root','recipient':path,
                    'content':[{'type':'input_text','text':'Message Type: NEW_TASK\nTask name: '+path+'\nSender: /root\nPayload:\n'+task_text}]}}])
        self.probe.bootstrap_root_turn=str(uuid4())
        root=[{'type':'session_meta','payload':{'id':self.root,'agent_path':'/root'}},
            message('developer','NATIVE_POLICY'),message('developer',CODE_MODE_GUIDANCE),message('user','NATIVE_CONTEXT'),
            {'type':'turn_context','payload':{'turn_id':self.probe.bootstrap_root_turn}},message('user','ROOT_TASK_NOT_NATIVE_CONTEXT')]
        self.probe.session_rows=Mock(side_effect=lambda t:root if t==self.root else rows)
        self.probe.task_gate(child,[(first,'BOOTSTRAP'),(second,'REVIEW')])
        original=list(rows);original_root=list(root)
        for target in (rows,root):
            target[:]=[r for r in target if r.get('type')!='turn_context']
            self.probe.initial_context=None
            with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):
                self.probe.task_gate(child,[(first,'BOOTSTRAP'),(second,'REVIEW')])
            rows[:]=original;root[:]=original_root
        self.probe.initial_context=None
        for context_row in [r for r in root+rows if r.get('type')=='turn_context']:
            correct=context_row['payload']['turn_id']
            for wrong in (str(uuid4()),'SYNTHETIC_SECRET',None):
                context_row['payload']['turn_id']=wrong;self.probe.initial_context=None
                with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):
                    self.probe.task_gate(child,[(first,'BOOTSTRAP'),(second,'REVIEW')])
            context_row['payload']['turn_id']=correct
        self.probe.initial_context=None
        with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):
            self.probe.task_gate(child,[(first,'BOOTSTRAP plus hint'),(second,'REVIEW')])
        for role in ('user','developer','system'):
            for position in (1,7,len(rows)):
                injected=message(role,'SYNTHETIC_COACHING')
                rows.insert(position,injected)
                with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):
                    self.probe.task_gate(child,[(first,'BOOTSTRAP'),(second,'REVIEW')])
                rows.pop(position)
        meta['payload']['forked_from_id']=self.root
        with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):
            self.probe.task_gate(child,[(first,'BOOTSTRAP'),(second,'REVIEW')])
        meta['payload'].pop('forked_from_id')
        rows.append({'type':'response_item','payload':{'type':'agent_message','author':'/root','recipient':path,'content':[]}})
        with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):
            self.probe.task_gate(child,[(first,'BOOTSTRAP'),(second,'REVIEW')])

    def test_codegen_uses_real_namespaced_native_handlers_and_preserves_data(self):
        tasks=[{'target':'PUBLIC','message':'literal ` $() "\n'}]
        code=collaboration_code('followup_task',tasks)
        self.assertIn('await tools.collaboration__followup_task(task)',code)
        self.assertIn(json.dumps(tasks,separators=(',',':')),code)
        self.assertEqual(len(NESTED),13)
        with self.assertRaises(RuntimeError):collaboration_code('unknown',tasks)
        prompt=native.bootstrap_prompt('PREFLIGHT','UNUSED','gpt-6-luna','low',isolation={
            'routes':True,'checkpoint_only':True,'inspect':'INSPECT','code_mode':True})
        self.assertIn('await tools.collaboration__spawn_agent(task)',prompt)
        self.assertIn('"fork_turns":"none"',prompt)

    def test_unknown_tool_route_cannot_pass_new_context_admission(self):
        p={'role':'root','thread_id':self.root,'excluded_marker_absent':True,
            **{k:True for k in ('lineage_matches','model_effort_matches','policy_matches_root','cwd_matches','approval_matches','role_guidance_matches')},
            'actual_nested_tool_names':sorted(NESTED|{'UNAPPROVED_TOOL'})}
        participants=[p,{**p,'role':'plan-reviewer'},{**p,'role':'code-reviewer'}]
        with patch.object(native,'audit_isolation_sessions',return_value=participants):
            with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):self.probe.context_gate()

    def test_protected_marker_is_not_folded_into_assessment(self):
        turn=str(uuid4());self.connection.call=Mock(return_value={'turn':{'id':turn}})
        self.connection.event=Mock(return_value={'method':'item/completed','params':{'threadId':self.root,'turnId':turn,
            'item':{'type':'agentMessage','phase':'final_answer','text':'SYNTHETIC_SECRET'}}})
        with self.assertRaisesRegex(RuntimeError,'^protected_disclosure$'):self.probe.run_turn('bootstrap','PUBLIC')
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(self.result))

    def test_case_request_uncertain_ack_and_safe_guard_location(self):
        self.probe.reviewers_only=True
        with self.store.request(self.origin,self.request) as state:state['native_purpose']='parent-review-fixture'
        self.probe._change('bootstrap_ready','workflow_held',workflow_held=True)
        with self.assertRaisesRegex(RuntimeError,'^uncertain_write$'):self.probe.run_turn('reviews','PUBLIC')
        self.assertIsNone(self.result['evaluated_case_dispatched'])
        self.assertIs(self.result['fixture_turn_requested'],True)
        try:assess_report('{"secret":"SYNTHETIC_SECRET"}','unknown')
        except RuntimeError as error:location=native.probe_guard_location(error)
        else:self.fail('Expected guard failure')
        self.assertEqual(location['module'],'signed_in_workflow');self.assertEqual(location['function'],'assess_report')
        self.assertIs(type(location['line']),int);self.assertGreater(location['line'],0)
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(location))


class AssessmentGuards(unittest.TestCase):
    def test_actual_case_results_required_not_status_or_parent_claim(self):
        code={'kind':'code-review','findings':[{'file':'after.py','line':2,'severity':'P2','examples':examples(True),'correction':'sum(values)'}]}
        self.assertEqual(assess_report(json.dumps(code),'code-reviewer')['findings'][0]['verified_behavior'],'positive_offset')
        for changed in [dict(kind='code-review',findings=[]),{**code,'parent_claim':'SYNTHETIC_SECRET'}]:
            with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):assess_report(json.dumps(changed),'code-reviewer')
        code['findings'][0]['examples'][0]['actual']=5
        with self.assertRaises(RuntimeError):assess_report(json.dumps(code),'code-reviewer')

    def test_plan_must_cover_contract_examples_and_actual_dependency(self):
        plan={'kind':'plan-review','scope_reviewed':True,'examples':examples(),
            'dependencies':[{'before':'P1','after':'P2'}],'finding_count':0}
        self.assertEqual(assess_report(json.dumps(plan),'plan-reviewer')['dependencies'],plan['dependencies'])
        plan['dependencies'].reverse();plan['dependencies'][0]={'before':'P2','after':'P1'}
        with self.assertRaises(RuntimeError):assess_report(json.dumps(plan),'plan-reviewer')

    def test_workflow_requires_explicit_held_stage_and_correct_understanding(self):
        report={'kind':'workflow-pause','stage':1,'next_stage':2,'approval_required':True,'examples':examples()}
        self.assertTrue(assess_report(json.dumps(report),'workflow')['approval_required'])
        for field,value in [('approval_required',False),('stage',True),('next_stage',3),('examples',[])]:
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                assess_report(json.dumps({**report,field:value}),'workflow')

    def test_unknown_secret_fields_duplicates_and_nonfinite_values_are_not_retained(self):
        for raw in ['{"kind":"a","kind":"b"}','{"expected":NaN}', '[]', '```json\n{}\n``` trailing']:
            with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):checked_json(raw)
        report={'kind':'workflow-pause','stage':1,'next_stage':2,'approval_required':True,'examples':examples(),'auth':'SYNTHETIC_SECRET'}
        with self.assertRaises(RuntimeError) as raised:assess_report(json.dumps(report),'workflow')
        self.assertNotIn('SYNTHETIC_SECRET',str(raised.exception))

    def test_own_read_requires_exact_thread_turn_command_and_public_bytes(self):
        thread,turn=str(uuid4()),str(uuid4());expected='PUBLIC_READ'
        event={'method':'item/completed','params':{'threadId':thread,'turnId':turn,'item':{
            'type':'commandExecution','command':expected,'status':'completed','exitCode':0,
            'aggregatedOutput':native_foundation_files()['after.py'].replace('\n','\r\n')}}}
        self.assertTrue(own_read(event,thread,turn,'case-after',expected))
        self.assertFalse(own_read(event,str(uuid4()),turn,'case-after',expected))
        self.assertFalse(own_read(event,thread,str(uuid4()),'case-after',expected))
        event['params']['item']['aggregatedOutput']='SYNTHETIC_SECRET'
        with self.assertRaises(RuntimeError):own_read(event,thread,turn,'case-after',expected)

    def test_native_skill_context_cannot_be_replaced_by_assistant_claim(self):
        expected='PUBLIC_SKILL_BODY'
        assistant={'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'text':expected}]}}
        self.assertFalse(received_skill([assistant],expected))
        loaded={'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':expected}]}}
        self.assertTrue(received_skill([loaded],expected))
