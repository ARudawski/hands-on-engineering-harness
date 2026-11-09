"""Model-free request guards; no native runtime, authentication or worker is used."""

import concurrent.futures
import json
import io
import os
import queue
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from evaluation import signed_in
from evaluation import signed_in_native


class RequestGuards(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.now = [10000.0, 1000.0]
        self.store = signed_in.RequestStore(self.root, clock=lambda: tuple(self.now))
        self.origin, self.request = str(uuid4()), str(uuid4())

    def submit(self, seconds=900):
        return self.store.submit(self.origin, self.request, 'native-foundation', seconds)

    @unittest.skipUnless(os.name == 'nt', 'native preparation uses Windows')
    def test_changed_versions_reach_install_checks_and_still_reject_failed_install(self):
        project = self.root/'Harness/project'
        project.mkdir(parents=True)
        store = signed_in.RequestStore(project/'.tmp/evaluation-signed-in')
        for codex_version, apm_version in [('codex-cli 0.167.0-alpha.3.2', 'Agent Package Manager (APM) CLI version 0.35.0'),
                                           ('codex-cli 0.166.0-alpha.6', 'Agent Package Manager (APM) CLI version future')]:
            with self.subTest(codex=codex_version, apm=apm_version):
                def run(command, **kwargs):
                    if command == ['codex', '--version']: return codex_version
                    if command == ['apm', '--version']: return apm_version
                    if command[:2] == ['apm', 'install']: raise RuntimeError('installation_changed')
                    return ''
                owner = SimpleNamespace(run=Mock(side_effect=run), cleanup_deadline=time.monotonic()+60,
                    close=lambda reason: {'job_empty':True,'within_budget':True})
                with patch.object(signed_in_native, 'ROOT', project), \
                     patch.object(signed_in_native, 'RequestStore', return_value=store), \
                     patch.object(signed_in_native.shutil, 'which', return_value='codex'), \
                     patch('evaluation.signed_in_process.AttemptProcesses', return_value=owner), \
                     patch('native_support.digest', return_value='a'*64), \
                     patch.dict(os.environ, CODEX_THREAD_ID=self.origin, APM_BIN='apm'):
                    result = signed_in_native.run_native({'request_id':str(uuid4()),'case':'native-foundation',
                        'seconds':60,'model':'gpt-6-luna','effort':'low'},mode='prepare')
                self.assertTrue(any(c.args[0][:2] == ['apm', 'install'] for c in owner.run.call_args_list))
                self.assertEqual(result['controller_version'], codex_version)
                self.assertEqual(result['apm_version'], apm_version)
                self.assertEqual(result['error_code'], 'installation_changed')
                self.assertFalse(result['model_turn_started'])
                self.assertFalse(result['admission_open'])
                self.assertTrue(result['cleanup_verified'])

    def test_python_read_paths_cover_venv_configuration_without_parent_access(self):
        runtime, environment = self.root/'python', self.root/'venv'
        with patch.object(sys, 'executable', str(environment/'Scripts/python.exe')), \
             patch.object(sys, 'prefix', str(environment)), patch.object(sys, 'base_prefix', str(runtime)):
            self.assertEqual(signed_in_native.python_read_paths(), {
                str(environment.resolve()/'Scripts'):'read', str(runtime.resolve()):'read',
                str(environment.resolve()/'pyvenv.cfg'):'read'})

    def test_command_gate_rejects_failed_malformed_or_partial_canaries(self):
        from evaluation.signed_in_worker import CHECKS
        checks = {k:True for k in CHECKS}
        self.assertEqual(signed_in_native.command_gate_checks({'exitCode':0,'stdout':json.dumps(checks)}),checks)
        for response in [None, {}, {'exitCode':1,'stdout':''}, {'exitCode':False,'stdout':json.dumps(checks)},
                         {'exitCode':0,'stdout':'[]'}, {'exitCode':0,'stdout':'SYNTHETIC_SECRET'},
                         {'exitCode':0,'stdout':json.dumps({**checks,'child':False})}]:
            with self.subTest(response=response), self.assertRaisesRegex(RuntimeError,'^native_boundary_failed$'):
                signed_in_native.command_gate_checks(response)

    def test_distinct_deadlines_and_duplicate_delivery(self):
        first = self.submit()
        self.now[:] = [10100, 1100]
        self.assertEqual(self.submit()['attempt_id'], first['attempt_id'])
        self.assertEqual(self.submit()['deadline'], 10900)
        second = self.store.submit(self.origin, str(uuid4()), 'native-foundation', 1800)
        self.assertEqual(second['deadline'], 11900)
        self.assertNotEqual(first['attempt_id'], second['attempt_id'])
        self.assertTrue(self.store.claim_launch(self.origin, self.request))
        self.assertFalse(self.store.claim_launch(self.origin, self.request))

    def test_observer_wait_preserves_callback_before_turn_acknowledgement(self):
        connection = signed_in_native.NativeConnection.__new__(signed_in_native.NativeConnection)
        connection.observer = object()
        connection.pending, connection.replies = deque(), {}
        connection.request_methods = {1: 'turn/start'}
        callback = {'id': 17, 'method': 'item/tool/requestUserInput', 'params': {'threadId': self.origin}}
        def receive(**kwargs):
            if not connection.pending:
                return callback
            connection.replies[1] = {'id': 1, 'result': {'turn': {'id': self.request}}}
            return connection.replies[1]
        connection.receive = receive
        self.assertEqual(connection.wait(1), {'turn': {'id': self.request}})
        self.assertEqual(list(connection.pending), [callback])

    def test_native_purpose_cannot_change_on_duplicate_request(self):
        self.submit()
        selection={'model':'gpt-6-luna','effort':'low'}
        profile={'profile_id':str(uuid4()),'reference_sha256':'a'*64}
        signed_in_native.bind_mode(self.store,self.origin,self.request,'diagnose',selection,profile,purpose='interactions')
        signed_in_native.bind_mode(self.store,self.origin,self.request,'diagnose',selection,profile,purpose='interactions')
        with self.assertRaises(ValueError):
            signed_in_native.bind_mode(self.store,self.origin,self.request,'diagnose',selection,profile)
        with self.assertRaises(ValueError):
            signed_in_native.bind_mode(self.store,self.origin,self.request,'prepare',selection,profile,purpose='interactions')

    def test_isolation_probe_cannot_switch_purpose_or_increase_model_effort(self):
        self.submit()
        profile={'profile_id':str(uuid4()),'reference_sha256':'a'*64}
        selection={'model':'gpt-6-luna','effort':'low'}
        signed_in_native.bind_mode(self.store,self.origin,self.request,'diagnose',selection,profile,purpose='isolation')
        with self.assertRaises(ValueError):
            signed_in_native.bind_mode(self.store,self.origin,self.request,'diagnose',selection,profile,purpose='interactions')
        for chosen, chosen_profile in [({'model':'gpt-6-luna','effort':'medium'},profile),(selection,None)]:
            with self.assertRaises(ValueError):
                signed_in_native.bind_mode(self.store,self.origin,str(uuid4()),'diagnose',chosen,chosen_profile,purpose='isolation')
        with patch.object(signed_in_native,'RequestStore') as factory:
            for flags in [dict(mode='prepare',isolation_probe=True),
                          dict(mode='diagnose',isolation_probe=True,interaction_probe=True),
                          dict(mode='diagnose',isolation_probe='yes'),
                          dict(mode='diagnose',isolation_routes=True),
                          dict(mode='diagnose',isolation_probe=True,isolation_routes='yes')]:
                with self.assertRaises(ValueError): signed_in_native.run_native({},**flags)
            factory.assert_not_called()

    def test_mcp_status_admission_requires_complete_empty_known_root(self):
        self.assertTrue(signed_in_native.empty_mcp_status({'data':[],'nextCursor':None}))
        for response in [None,{}, {'data':{}},{'data':[{'name':'SYNTHETIC_SECRET'}]},
                         {'data':[],'nextCursor':'more'}]:
            self.assertFalse(signed_in_native.empty_mcp_status(response))
        connection=signed_in_native.NativeConnection.__new__(signed_in_native.NativeConnection)
        connection.mode='diagnose';connection.profile={'profile_id':str(uuid4()),'reference_sha256':'a'*64}
        connection.inspection=True;connection.started={'thread':{'id':self.origin}}
        with self.assertRaisesRegex(RuntimeError,'^native_method_blocked$'):
            connection.send({'method':'mcpServerStatus/list','params':{'threadId':str(uuid4())}})
        connection.inspection=False
        with self.assertRaisesRegex(RuntimeError,'^native_method_blocked$'):
            connection.send({'method':'mcpServerStatus/list','params':{'threadId':self.origin}})

    def test_blocked_callback_summary_is_fixed_nonsecret_metadata(self):
        value={'method':'item/fileChange/requestApproval','id':17,
            'params':{'threadId':'SYNTHETIC_SECRET','itemId':'SYNTHETIC_SECRET',
                'reason':'SYNTHETIC_SECRET','grantRoot':'SYNTHETIC_SECRET'}}
        summary=signed_in_native.blocked_callback_summary(value,{'thread':{'id':str(uuid4())}})
        self.assertEqual(summary,{'kind':'file','root_matches':False,'item_present':True})
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(summary))
        self.assertEqual(signed_in_native.blocked_callback_summary({'method':[],'params':[]},None),
            {'kind':'other','root_matches':False,'item_present':False})

    def test_synthetic_inspection_reports_access_breach_without_contents(self):
        from evaluation.signed_in_worker import inspect_reads
        task=self.root/'h12-public'; task.mkdir()
        (task/'contract.md').write_text('PUBLIC_ALLOWED')
        protected=self.root/'synthetic-protected'; protected.write_text('SYNTHETIC_SECRET')
        checks=inspect_reads({'protected':[str(protected)]},self.root)
        self.assertEqual(checks,{'task_read':True,'protected_reads':False})
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(checks))

    def test_inventory_requires_exact_native_code_and_correlated_actual_output(self):
        call={'type':'custom_tool_call','name':'exec','input':signed_in_native.ISOLATION_INVENTORY,'call_id':'issued'}
        output={'type':'custom_tool_call_output','call_id':'issued','output':[
            {'type':'input_text','text':json.dumps({'h12_native_tools':['exec_command','apply_patch']})}]}
        self.assertEqual(signed_in_native.isolation_inventory([call,output]),['apply_patch','exec_command'])
        for items in [[output],[call,{**output,'call_id':'foreign'}],[call,output,output],
            [{**call,'input':'text({h12_native_tools:["exec_command"]})'},output]]:
            self.assertIsNone(signed_in_native.isolation_inventory(items))
        invalid={**output,'output':[{'type':'input_text','text':json.dumps({'h12_native_tools':[{}]})}]}
        self.assertIsNone(signed_in_native.isolation_inventory([call,invalid]))

    def test_native_patch_evidence_requires_issued_root_turn_and_exact_path(self):
        event={'method':'item/completed','params':{'threadId':self.origin,'turnId':self.request,
            'item':{'type':'fileChange','status':'completed','changes':[{'path':'allowed','diff':'SYNTHETIC_SECRET'}]}}}
        expected={'kind':'allowed','completed':True,'status':'completed'}
        self.assertEqual(signed_in_native.isolation_patch_event(event,self.origin,self.request,'allowed','protected'),expected)
        self.assertIsNone(signed_in_native.isolation_patch_event(event,str(uuid4()),self.request,'allowed','protected'))
        self.assertIsNone(signed_in_native.isolation_patch_event(event,self.origin,str(uuid4()),'allowed','protected'))
        event['params']['item']['changes'].append({'path':'foreign'})
        evidence=signed_in_native.isolation_patch_event(event,self.origin,self.request,'allowed','protected')
        self.assertEqual(evidence['kind'],'other')
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(evidence))

    def test_invalid_requests_allocate_nothing(self):
        for case, seconds in [('unknown', 900), ('native-foundation', True),
                              ('native-foundation', 10), ('native-foundation', 7201),
                              ('native-foundation', '900'), ('native-foundation', 30.5)]:
            with self.subTest(case=case, seconds=seconds), self.assertRaises(ValueError):
                self.store.submit(self.origin, self.request, case, seconds)
        with self.assertRaises(KeyError):
            self.store.get(self.origin, self.request)
        self.submit()
        with self.assertRaises(ValueError):
            self.submit(1800)

    def test_foreign_origin_cannot_read_interrupt_or_adopt_request(self):
        self.submit()
        foreign = str(uuid4())
        for action in [lambda: self.store.get(foreign, self.request),
                       lambda: self.store.stop(foreign, self.request, 'interrupted'),
                       lambda: self.store.submit(foreign, self.request, 'native-foundation', 900)]:
            with self.assertRaises(PermissionError):
                action()
        self.assertTrue(self.store.get(self.origin, self.request)['admission_open'])

    def test_atomic_parallel_duplicate_and_launch_claim(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            attempts = list(pool.map(lambda _: self.submit()['attempt_id'], range(8)))
            claims = list(pool.map(lambda _: self.store.claim_launch(self.origin, self.request), range(8)))
        self.assertEqual(len(set(attempts)), 1)
        self.assertEqual(sum(claims), 1)

    def test_preparation_expiry_and_clock_rollback_close_admission(self):
        for elapsed in [890, 901]:
            self.request = str(uuid4())
            self.now[:] = [10000, 1000]
            self.submit()
            self.now[:] = [10000 + elapsed, 1000 + elapsed]
            self.assertFalse(self.store.claim_launch(self.origin, self.request))
            self.assertEqual(self.store.get(self.origin, self.request)['first_failure'], 'deadline_exhausted')
        self.request = str(uuid4())
        self.now[:] = [10000, 1000]
        self.submit()
        self.now[:] = [9999, 1001]
        self.assertFalse(self.store.claim_launch(self.origin, self.request))
        self.assertEqual(self.store.get(self.origin, self.request)['first_failure'], 'clock_changed')

    def test_interrupt_and_failed_cleanup_never_reopen_or_replace_cause(self):
        self.submit()
        self.assertTrue(self.store.claim_launch(self.origin, self.request))
        result = self.store.stop(self.origin, self.request, 'interrupted')
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(self.store.cleanup(self.origin, self.request, False)['cleanup'], 'failed')
        for _ in range(2):
            self.assertFalse(self.store.claim_launch(self.origin, self.request))
            self.assertEqual(self.submit()['first_failure'], 'interrupted')
        self.assertEqual(self.store.get(self.origin, self.request)['cleanup_failure'], 'cleanup_failed')
        self.assertEqual(self.store.stop(self.origin, self.request, 'protected_disclosure')['status'], 'invalid')
        self.assertEqual(self.store.stop(self.origin, self.request, 'interrupted')['status'], 'invalid')

    def test_safe_records_drop_foreign_content_and_credentials_before_storage(self):
        self.submit()
        thread = str(uuid4())
        self.assertTrue(self.store.record(self.origin, self.request, {
            'kind': 'preparation', 'status': 'completed', 'token': 'SYNTHETIC_SECRET',
            'message': 'SYNTHETIC_SECRET', 'error': {'credential': 'SYNTHETIC_SECRET'}}))
        self.assertFalse(self.store.record(self.origin, self.request, {
            'kind': 'review', 'status': 'completed', 'thread_id': str(uuid4()),
            'message': 'FOREIGN_HISTORY'}, allowed_threads={thread}))
        self.assertFalse(self.store.record(self.origin, self.request, {
            'kind': 'error', 'status': 'SYNTHETIC_SECRET'}))
        for event in [{'kind': [], 'status': 'completed'}, {'kind': 'review', 'status': {}},
                      {'kind': 'review', 'status': 'completed', 'thread_id': []},
                      {'kind': 'error', 'status': 'failed', 'code': {}}]:
            self.assertFalse(self.store.record(self.origin, self.request, event))
        self.store.stop(self.origin, self.request, 'reviewer_route_unverified')
        for path in self.root.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'SYNTHETIC_SECRET', path.read_bytes())
                self.assertNotIn(b'FOREIGN_HISTORY', path.read_bytes())
        result = self.store.get(self.origin, self.request)
        self.assertEqual(result['first_failure'], 'reviewer_route_unverified')
        self.assertEqual(result['status'], 'rejected_before_launch')
        self.assertEqual(len(result['events']), 1)
        self.assertTrue(all(v == 'skipped' for v in result['checks'].values()))
        self.assertIsNone(result['model'])

    def test_cli_errors_never_echo_untrusted_input(self):
        script = Path(signed_in.__file__)
        for payload in [{'request_id': 'SYNTHETIC_SECRET', 'case': 'native-foundation', 'seconds': 900},
                        {'request_id': self.request, 'case': 'SYNTHETIC_SECRET', 'seconds': 900},
                        {'credential': 'SYNTHETIC_SECRET'}, ['SYNTHETIC_SECRET']]:
            run = subprocess.run([sys.executable, str(script)], input=json.dumps(payload),
                                 text=True, capture_output=True, timeout=10,
                                 env={**os.environ, 'CODEX_THREAD_ID': self.origin})
            self.assertNotIn('SYNTHETIC_SECRET', run.stdout + run.stderr)
            self.assertEqual(json.loads(run.stdout)['error'], 'request_rejected')

    def test_native_bootstrap_only_matches_exact_commands(self):
        self.assertEqual(signed_in_native.disabled_mcp_options({'node_repl': {}}),
                         {'mcp_servers.node_repl.enabled': False})
        with self.assertRaises(ValueError):
            signed_in_native.disabled_mcp_options({'ambiguous.name': {}})
        expected = "& 'C:\\Python\\python.exe' -I -B 'C:\\trial\\h12-probe.py' preflight"
        self.assertTrue(signed_in_native.command_matches(expected, expected))
        self.assertTrue(signed_in_native.command_matches(['powershell.exe', '-NoProfile', '-Command', expected], expected))
        self.assertFalse(signed_in_native.command_matches(['powershell.exe', '-Command', expected+'; Get-Content C:\\outside'], expected))
        self.assertFalse(signed_in_native.command_matches(expected + '; cat /outside', expected))
        self.assertFalse(signed_in_native.command_matches('cat /outside', expected))

    def test_native_terminal_rpcs_are_cleanup_only_and_not_prepare(self):
        connection = signed_in_native.NativeConnection.__new__(signed_in_native.NativeConnection)
        connection.mode = 'diagnose'
        connection.owner = SimpleNamespace(lock=threading.RLock(), remaining=lambda **kwargs:1)
        connection.process = SimpleNamespace(stdin=io.StringIO())
        for method in ('thread/backgroundTerminals/list','thread/backgroundTerminals/terminate'):
            with self.assertRaisesRegex(RuntimeError,'^native_method_blocked$'):
                connection.send({'method':method},cleanup=False)
            connection.send({'method':method},cleanup=True)
            connection.mode='prepare'
            with self.assertRaisesRegex(RuntimeError,'^native_method_blocked$'):
                connection.send({'method':method},cleanup=True)
            connection.mode='diagnose'

    def test_native_terminal_cleanup_targets_only_known_item_and_process(self):
        expected = 'PUBLIC_HEARTBEAT'
        row = {'itemId':'owned-item','processId':'1234','command':expected}
        connection = SimpleNamespace(call=Mock(return_value={'data':[row],'nextCursor':None}))
        self.assertEqual(signed_in_native.terminate_heartbeat_terminal(connection,'root','owned-item','1234',expected),'terminated')
        self.assertEqual(connection.call.call_args.args,
            ('thread/backgroundTerminals/terminate',{'threadId':'root','processId':'1234'}))
        for rows,cursor in (([{**row,'processId':'foreign'}],None),([{**row,'command':expected+'; extra'}],None),
                            ([row,row],None),([row],'next')):
            connection.call = Mock(return_value={'data':rows,'nextCursor':cursor})
            with self.assertRaisesRegex(RuntimeError,'^native_terminal_ambiguous$'):
                signed_in_native.terminate_heartbeat_terminal(connection,'root','owned-item','1234',expected)
            self.assertEqual(connection.call.call_count,1)
        connection.call = Mock(return_value={'data':[{**row,'itemId':'foreign-item'}],'nextCursor':None})
        self.assertEqual(signed_in_native.terminate_heartbeat_terminal(connection,'root','owned-item','1234',expected),'absent')
        self.assertEqual(connection.call.call_count,1)
        with self.assertRaisesRegex(RuntimeError,'^missing_terminal_identity$'):
            signed_in_native.terminate_heartbeat_terminal(connection,'root',None,'1234',expected)

    def test_native_stop_observer_distinguishes_late_stop_from_forced_cleanup(self):
        beat = self.root/'beat';beat.write_text('1',encoding='ascii')
        owner = SimpleNamespace(remaining=lambda *args,**kwargs:1,terminated=False)
        with patch('evaluation.signed_in_process.process_stopped',side_effect=[False,True,True,True]):
            observed = signed_in_native.observe_tree_stop(owner,99,beat,seconds=.3,stable_seconds=.02)
        self.assertTrue(observed['verified'])
        owner.terminated=True
        observed = signed_in_native.observe_tree_stop(owner,99,beat,seconds=.1,stable_seconds=.02)
        self.assertFalse(observed['verified']);self.assertTrue(observed['forced_job_stop'])
        owner.terminated=False;beat.write_text('invalid',encoding='ascii')
        with patch('evaluation.signed_in_process.process_stopped',return_value=True):
            observed = signed_in_native.observe_tree_stop(owner,99,beat,seconds=.1,stable_seconds=.02)
        self.assertFalse(observed['verified']);self.assertFalse(observed['heartbeat_stable'])
        beat.write_text('1'+' '*64+'UNREAD',encoding='ascii')
        self.assertIsNone(signed_in_native.heartbeat_value(beat))

    def test_native_bootstrap_prompt_separates_exact_commands_from_prose(self):
        preflight = "& 'C:\\Python\\python.exe' -I -B 'C:\\trial\\h12-probe.py' preflight"
        heartbeat = preflight.removesuffix('preflight')+'heartbeat'
        prompt = signed_in_native.bootstrap_prompt(preflight, heartbeat, 'gpt-6-luna', 'medium')
        blocks = [part.split('\n```',1)[0] for part in prompt.split('```powershell\n')[1:]]
        self.assertEqual(blocks, [preflight, heartbeat])
        self.assertIn('fork_turns=none', prompt)
        self.assertIn('gpt-6-luna', prompt)
        self.assertIn('reasoning effort medium', prompt)
        self.assertFalse(signed_in_native.command_matches(preflight+'.', preflight))
        self.assertFalse(signed_in_native.command_matches(heartbeat+'.', heartbeat))
        fixture = json.loads((Path(__file__).parent/'fixtures/signed-in-command.json').read_text(encoding='utf-8'))
        self.assertFalse(signed_in_native.command_matches(fixture['display'].replace('preflight','preflight.'), fixture['expected']))

    def test_native_api_display_is_decoded_to_exact_argv(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/signed-in-command.json').read_text(encoding='utf-8'))
        with patch.object(signed_in_native.shutil, 'which', side_effect=lambda name: fixture['argv'][0] if name == 'powershell.exe' else None):
            self.assertTrue(signed_in_native.command_matches(fixture['display'], fixture['expected']))
            self.assertTrue(signed_in_native.command_matches(fixture['argv'], fixture['expected']))
            heartbeat = fixture['display'].replace('preflight', 'heartbeat')
            self.assertTrue(signed_in_native.command_matches(heartbeat, fixture['expected'].replace('preflight', 'heartbeat')))
            for invalid in (fixture['display']+'; Get-Content outside',
                            fixture['display'].replace('preflight', 'preflight; Get-Content outside'),
                            fixture['display'].replace('-NoProfile', '-NoProfile -File outside'),
                            fixture['display'].replace('powershell.exe', 'other.exe'), '"unterminated'):
                self.assertFalse(signed_in_native.command_matches(invalid, fixture['expected']))

    def test_native_preflight_gate_requires_own_completed_turn_before_child(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/signed-in-command.json').read_text(encoding='utf-8'))
        checks = {k: True for k in ('task_write','protected_reads','protected_writes','local_network','external_network','dns','child')}
        event = {'method':'item/completed','params':{'threadId':self.origin,'turnId':self.request,
            'item':{'type':'commandExecution','status':'completed','command':fixture['display'],
                    'exitCode':0,'aggregatedOutput':json.dumps(checks)}}}
        child = {'method':'item/started','params':{'threadId':self.origin,'turnId':self.request,
            'item':{'type':'subAgentActivity','kind':'started','agentThreadId':str(uuid4())}}}
        with self.assertRaisesRegex(RuntimeError, '^unexpected_child_dispatch$'):
            signed_in_native.register_child(child, self.origin, False, {})
        with patch.object(signed_in_native.shutil, 'which', side_effect=lambda name: fixture['argv'][0] if name == 'powershell.exe' else None):
            gate = signed_in_native.preflight_completed(event, self.origin, self.request, fixture['expected'])
            self.assertTrue(gate)
            self.assertTrue(signed_in_native.register_child(child, self.origin, gate, {}))
            for key, value in (('threadId',str(uuid4())),('turnId',str(uuid4())),('turnId',None)):
                changed = json.loads(json.dumps(event)); changed['params'][key] = value
                self.assertFalse(signed_in_native.preflight_completed(changed, self.origin, self.request, fixture['expected']))
            for key, value in (('status','failed'),('exitCode',1),('exitCode',False),
                               ('aggregatedOutput','[]'),('aggregatedOutput','SYNTHETIC_SECRET'),
                               ('aggregatedOutput',json.dumps({**checks,'child':False}))):
                changed = json.loads(json.dumps(event)); changed['params']['item'][key] = value
                with self.assertRaisesRegex(RuntimeError, '^native_boundary_failed$'):
                    signed_in_native.preflight_completed(changed, self.origin, self.request, fixture['expected'])

    def test_native_assessment_export_excludes_all_child_prose_before_storage(self):
        for prose in ['{"refresh_token":"SYNTHETIC_SECRET"}', 'password=SYNTHETIC_SECRET',
                      'opaque-token SYNTHETIC_SECRET', 'Bearer SYNTHETIC_SECRET',
                      'Ordinary public reviewer conclusion']:
            exported = {'assessment_status': signed_in_native.assessment_status(prose)}
            receipt = self.root / 'receipt.json'
            receipt.write_text(json.dumps(exported), encoding='utf-8')
            self.assertEqual(json.loads(receipt.read_text(encoding='utf-8')), {'assessment_status': 'received'})
            self.assertNotIn(prose, receipt.read_text(encoding='utf-8'))
        for empty in ['', '  ', None, {'refresh_token': 'SYNTHETIC_SECRET'}]:
            self.assertEqual(signed_in_native.assessment_status(empty), 'missing')

    def test_native_bootstrap_requires_explicit_bounded_invocation(self):
        run = subprocess.run([sys.executable, signed_in_native.__file__], input='SYNTHETIC_SECRET',
                             text=True, capture_output=True, timeout=5)
        self.assertEqual(json.loads(run.stdout), {'error': 'bootstrap_rejected'})
        self.assertNotIn('SYNTHETIC_SECRET', run.stdout + run.stderr)
        with self.assertRaises(ValueError):
            signed_in_native.diagnose({'request_id': self.request, 'case': 'native-foundation', 'seconds': 901,
                                       })
        for mode in ('prepare', 'diagnose'):
            client = signed_in_native.NativeConnection.__new__(signed_in_native.NativeConnection)
            client.mode = mode
            for method in ('thread/shellCommand', 'thread/fork', 'thread/resume', 'process/spawn'):
                with self.assertRaisesRegex(RuntimeError, 'native_method_blocked'):
                    client.send({'method': method})
        client.mode = 'prepare'
        for method in ('turn/start', 'turn/steer', 'review/start', 'account/read'):
            with self.assertRaisesRegex(RuntimeError, 'native_method_blocked'):
                client.send({'method': method})

    def test_native_errors_export_only_known_codes(self):
        self.assertEqual(signed_in_native.native_error_code({
            'message': 'failed to load workspace requirements: invalid input parameter',
            'codexErrorInfo': 'other'}), 'workspace_requirements_unavailable')
        self.assertEqual(signed_in_native.native_error_code({'message': 'SYNTHETIC_SECRET',
            'codexErrorInfo': {'token': 'SYNTHETIC_SECRET'}}), 'native_turn_failed')
        self.assertEqual(signed_in_native.native_error_code({'codexErrorInfo': 'usageLimitExceeded'}), 'usageLimitExceeded')

    def test_native_children_require_root_start_after_boundary_and_deduplicate(self):
        children = {}
        event = {'method': 'item/started', 'params': {'threadId': 'root', 'item': {
            'type': 'subAgentActivity', 'kind': 'started', 'agentThreadId': str(uuid4())}}}
        with self.assertRaises(RuntimeError):
            signed_in_native.register_child(event, 'root', False, children)
        self.assertFalse(signed_in_native.register_child(event, 'foreign', True, children))
        self.assertTrue(signed_in_native.register_child(event, 'root', True, children))
        self.assertFalse(signed_in_native.register_child(event, 'root', True, children))
        event['method'] = 'item/completed'
        self.assertFalse(signed_in_native.register_child(event, 'root', True, children))
        event['method'] = 'item/started'
        event['params']['item']['agentThreadId'] = str(uuid4())
        self.assertTrue(signed_in_native.register_child(event, 'root', True, children))
        event['params']['item']['agentThreadId'] = str(uuid4())
        with self.assertRaises(RuntimeError):
            signed_in_native.register_child(event, 'root', True, children)

    def test_native_cleanup_failure_closes_both_receipt_and_shared_request(self):
        for controller, worker, budget in [(True, True, True), (False, True, True),
                                           (True, False, True), (True, True, False), (None, True, True)]:
            with self.subTest(controller=controller, worker=worker, budget=budget):
                self.request = str(uuid4())
                self.submit()
                self.store.claim_launch(self.origin, self.request)
                self.store.stop(self.origin, self.request, 'interrupted')
                result = {'expected_interrupt': True, 'controller_stopped': controller,
                          'worker_stopped': worker, 'cleanup_within_budget': budget}
                signed_in_native.finish_cleanup(self.store, self.origin, self.request, result, True, True)
                state = self.store.get(self.origin, self.request)
                succeeded = controller is True and worker is True and budget is True
                self.assertEqual(result['cleanup_verified'], succeeded)
                self.assertEqual(result['status'], 'observed_pending_assessment' if succeeded else 'incomplete')
                self.assertEqual(state['cleanup'], 'completed' if succeeded else 'failed')
                self.assertEqual(state['first_failure'], 'interrupted')
                self.assertFalse(state['admission_open'])

    def test_native_mode_binding_cannot_promote_preparation_to_live(self):
        self.submit()
        signed_in_native.bind_mode(self.store, self.origin, self.request, 'prepare')
        signed_in_native.bind_mode(self.store, self.origin, self.request, 'prepare')
        with self.assertRaises(ValueError):
            signed_in_native.bind_mode(self.store, self.origin, self.request, 'diagnose')
        with self.assertRaises(ValueError):
            signed_in_native.bind_mode(self.store, self.origin, self.request, 'SYNTHETIC_SECRET')
        with self.store.request(self.origin, self.request) as state:
            self.assertEqual(state['native_mode'], 'prepare')

    def test_native_errors_and_callbacks_cannot_export_prose_or_grant_approval(self):
        client = signed_in_native.NativeConnection.__new__(signed_in_native.NativeConnection)
        client.request_methods={1:'turn/start'}
        client.replies = {1: {'error': {'message': 'SYNTHETIC_SECRET', 'credential': 'SYNTHETIC_SECRET'}}}
        with self.assertRaisesRegex(RuntimeError, '^native_rpc_failed$'):
            client.wait(1)
        self.assertEqual(client.last_rpc_error,{'method':'turn/start','code':None,'kind':'unknown'})
        self.assertEqual(client.request_methods,{})
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(client.last_rpc_error))
        self.assertEqual(signed_in_native.rpc_error_summary('SYNTHETIC_SECRET',{'code':-32600}),
                         {'method':'other','code':-32600,'kind':'invalid_request'})
        client.pending = deque()
        client.receive = lambda **kwargs: {'id': 99, 'method': 'item/commandExecution/requestApproval',
                                          'params': {'reason': 'SYNTHETIC_SECRET'}}
        with self.assertRaisesRegex(RuntimeError, '^native_callback_blocked$'):
            client.wait(2)

    def test_native_install_rejects_materialized_source_drift(self):
        source = self.root/'apm_modules/ARudawski/hands-on-engineering-harness'
        source.mkdir(parents=True)
        (source/'README.md').write_text('MODIFIED_SOURCE', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, '^installation_changed$'):
            signed_in_native.verify_install(self.root, '100644 blob '+('0'*40)+'\tREADME.md\n')

    def test_native_route_rejects_embedded_provider_auth_overrides(self):
        for override in ({'experimental_bearer_token': 'SYNTHETIC_SECRET'},
                         {'env_key': 'SYNTHETIC_SECRET'}, {'http_headers': {'Authorization': 'SYNTHETIC_SECRET'}},
                         {'base_url': 'SYNTHETIC_SECRET'}):
            with self.assertRaisesRegex(RuntimeError, '^unselected_controller_configuration$'):
                signed_in_native.selected_settings({'model_providers': {'openai': override}})
        self.assertEqual(signed_in_native.selected_settings({'model_providers': {'openai': {}}}),
                         ('gpt-6.1-sol', 'high'))

    def test_native_explicit_model_selection_is_bounded_and_frozen(self):
        choice = {'model': 'gpt-6-luna', 'effort': 'medium'}
        self.assertEqual(signed_in_native.selected_settings(
            {'model': 'gpt-6.1-sol', 'model_reasoning_effort': 'high'}, **choice),
            ('gpt-6-luna', 'medium'))
        for invalid in ({'model': 'gpt-6-luna'}, {'effort': 'medium'},
                        {'model': 'gpt-6-luna', 'effort': 'high'},
                        {'model': 'SYNTHETIC SECRET', 'effort': 'low'}):
            with self.assertRaisesRegex(RuntimeError, '^unsupported_model_configuration$'):
                signed_in_native.selected_settings({}, **invalid)
        self.submit()
        signed_in_native.bind_mode(self.store, self.origin, self.request, 'diagnose', choice)
        signed_in_native.bind_mode(self.store, self.origin, self.request, 'diagnose', choice)
        for changed in (None, {'model': 'gpt-6-luna', 'effort': 'low'}):
            with self.assertRaises(ValueError):
                signed_in_native.bind_mode(self.store, self.origin, self.request, 'diagnose', changed)
        with self.assertRaisesRegex(ValueError, '^Explicit model selection required$'):
            signed_in_native.diagnose({'request_id': self.request, 'case': 'native-foundation', 'seconds': 900})

    def test_native_shell_environment_excludes_host_runtime_search_paths(self):
        env = {'SYSTEMROOT': str(self.root), 'PATH': 'HOST_codex-runtimes_PATH'}
        with patch.object(Path, 'is_file', side_effect=[True, False]), patch.object(signed_in_native.shutil, 'which', return_value=None):
            shell, bounded = signed_in_native.native_environment(env, self.root)
        self.assertNotEqual(bounded['PATH'], env['PATH'])
        self.assertNotIn('codex-runtimes', bounded['PATH'].lower())
        self.assertEqual(Path(bounded['PATH'].split(os.pathsep)[0]), shell.parent)
        self.assertEqual(env['PATH'], 'HOST_codex-runtimes_PATH')
        for exists, discovered in ((False, None), (True, 'UNSELECTED_PWSH'), (True, None)):
            with patch.object(Path, 'is_file', return_value=exists), patch.object(signed_in_native.shutil, 'which', return_value=discovered):
                with self.assertRaisesRegex(RuntimeError, '^unsupported_shell_configuration$'):
                    signed_in_native.native_environment(env, self.root)
        (self.root/'.env').write_text('SYNTHETIC_SECRET', encoding='ascii')
        with self.assertRaisesRegex(RuntimeError, '^unselected_controller_configuration$'):
            signed_in_native.native_environment(env, self.root)

    def test_native_interrupt_tolerates_quiet_polling_but_requires_exact_turn(self):
        terminal = {'method': 'turn/completed', 'params': {'threadId': 'root', 'turn': {'id': 'turn', 'status': 'interrupted'}}}
        foreign = {'method': 'turn/completed', 'params': {'threadId': 'foreign', 'turn': {'id': 'turn', 'status': 'interrupted'}}}
        owner = SimpleNamespace(remaining=Mock(side_effect=[1, 1, 1]))
        client = SimpleNamespace(owner=owner, event=Mock(side_effect=[queue.Empty(), foreign, terminal]))
        self.assertTrue(signed_in_native.wait_for_interrupt(client, 'root', 'turn'))
        self.assertEqual(client.event.call_count, 3)
        owner.remaining = Mock(side_effect=TimeoutError('cutoff'))
        with self.assertRaises(TimeoutError):
            signed_in_native.wait_for_interrupt(client, 'root', 'turn')


if __name__ == '__main__':
    unittest.main()
