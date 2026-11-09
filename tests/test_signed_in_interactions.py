"""Fabricated protocol events test controller guards, never native acceptance."""

import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from evaluation.signed_in import RequestStore
from evaluation.signed_in_interactions import Interactions, marker_command


class InteractionGuards(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = [10000., 1000.]
        self.store = RequestStore(self.directory.name, clock=lambda: tuple(self.now))
        self.origin, self.request, self.root = (str(uuid4()) for _ in range(3))
        self.question_turn, self.permission_turn, self.workflow_turn = (str(uuid4()) for _ in range(3))
        self.manifest = 'a' * 64
        self.cwd, self.python = r'C:\trial\consumer', r'C:\Python\python.exe'
        self.command = marker_command(self.python)
        self.store.submit(self.origin, self.request, 'native-foundation', 120)
        self.store.claim_launch(self.origin, self.request)
        self.controller = self.reopen()
        self.controller.bind(self.root, self.manifest, cwd=self.cwd, python_executable=self.python)

    def reopen(self):
        store = RequestStore(self.directory.name, clock=lambda: tuple(self.now))
        return Interactions(store, self.origin, self.request)

    def callback(self, kind='question', request_id=None):
        request_id = (17 if kind == 'question' else 18) if request_id is None else request_id
        params = {'threadId': self.root, 'turnId': self.question_turn if kind == 'question' else self.permission_turn,
                  'itemId': 'issued-item'}
        if kind == 'question':
            params.update(isBlocking=True, questions=[{'header': 'Label', 'id': 'har5_choice',
                'question': 'Which label should the public probe use?', 'isSecret': False, 'isOther': True,
                'options': [{'label': 'Alpha (Recommended)', 'description': 'Public alpha'},
                            {'label': 'Beta', 'description': 'Public beta'}]}])
        else:
            params.update(startedAtMs=10000000, command=self.command, cwd=self.cwd, kind='command')
        return {'id': request_id, 'method': 'item/tool/requestUserInput' if kind == 'question' else
                'item/commandExecution/requestApproval', 'params': params}

    def resolved(self, request_id=17):
        return {'method': 'serverRequest/resolved', 'params': {'threadId': self.root, 'requestId': request_id}}

    def turn_completed(self, turn):
        return {'method': 'turn/completed', 'params': {'threadId': self.root, 'turn': {'id': turn, 'status': 'completed'}}}

    def command_completed(self):
        return {'method': 'item/completed', 'params': {'threadId': self.root, 'turnId': self.permission_turn,
                'item': {'id': 'issued-item', 'type': 'commandExecution', 'command': self.command,
                         'status': 'completed', 'exitCode': 0, 'aggregatedOutput': 'HAR5_APPROVED\n'}}}

    def question_checkpoint(self):
        self.controller.begin('question', self.question_turn)
        answer = self.controller.reply(self.callback())
        self.assertEqual(answer, {'id': 17, 'result': {'answers': {'har5_choice': {'answers': ['Alpha (Recommended)']}}}})
        self.controller.resolved(self.resolved())
        self.controller.completed(self.turn_completed(self.question_turn))

    def resume(self):
        self.question_checkpoint()
        params = self.controller.prepare_resume(self.root, self.question_turn, self.manifest)
        self.assertEqual(params, {'threadId': self.root})
        response = {'thread': {'id': self.root, 'turns': [{'id': self.question_turn, 'status': 'completed'}]}}
        self.controller.confirm_resume(response, self.manifest)
        return response

    def permission(self):
        self.resume()
        self.controller.begin('permission', self.permission_turn)
        self.assertEqual(self.controller.reply(self.callback('permission'), cwd=self.cwd,
            python_executable=self.python), {'id': 18, 'result': {'decision': 'accept'}})

    def test_complete_fabricated_sequence_survives_controller_reconstruction(self):
        self.permission()
        self.controller = self.reopen()
        self.controller.completed(self.command_completed())
        self.controller.resolved(self.resolved(18))
        self.controller.completed(self.turn_completed(self.permission_turn))
        self.controller.begin('workflow', self.workflow_turn)
        self.assertEqual(self.controller.completed(self.turn_completed(self.workflow_turn)), 'workflow_held_unassessed')
        for kind in ('question', 'permission', 'workflow'):
            with self.assertRaises(ValueError): self.controller.begin(kind, str(uuid4()))
        with self.assertRaises(ValueError): self.controller.reply(self.callback())
        self.assertEqual(self.store.get(self.origin, self.request)['deadline'], 10120)

    def test_resume_requires_resolved_completed_question_and_exact_frozen_checkpoint(self):
        with self.assertRaises(ValueError): self.controller.prepare_resume(self.root, self.question_turn, self.manifest)
        self.controller.begin('question', self.question_turn)
        self.controller.reply(self.callback())
        with self.assertRaises(ValueError): self.controller.completed(self.turn_completed(self.question_turn))
        self.controller.resolved(self.resolved())
        self.controller.completed(self.turn_completed(self.question_turn))
        for root, turn, manifest in [(str(uuid4()), self.question_turn, self.manifest),
                                    (self.root, str(uuid4()), self.manifest), (self.root, self.question_turn, 'b' * 64)]:
            with self.assertRaises(ValueError): self.reopen().prepare_resume(root, turn, manifest)
        self.controller.prepare_resume(self.root, self.question_turn, self.manifest)
        with self.assertRaises(ValueError): self.reopen().prepare_resume(self.root, self.question_turn, self.manifest)
        good = {'thread': {'id': self.root, 'turns': [{'id': self.question_turn, 'status': 'completed'}]}}
        for response, manifest in [({'thread': {'id': str(uuid4())}}, self.manifest),
            ({'thread': {'id': self.root, 'turns': []}}, self.manifest), (good, 'b' * 64),
            ({'thread': {'id': self.root, 'turns': [{'id': str(uuid4()), 'status': 'completed'}]}}, self.manifest)]:
            with self.assertRaises(ValueError): self.controller.confirm_resume(response, manifest)
        self.controller.confirm_resume(good, self.manifest)

    def test_resume_history_page_requires_issued_identity_and_complete_known_turns(self):
        self.question_checkpoint()
        self.controller.prepare_resume(self.root,self.question_turn,self.manifest)
        for root, rpc_id in [(str(uuid4()),3),(self.root,True)]:
            with self.assertRaises(ValueError): self.controller.prepare_history_read(root,rpc_id)
        params=self.controller.prepare_history_read(self.root,3)
        self.assertEqual(params,{'threadId':self.root,'sortDirection':'asc','itemsView':'notLoaded','limit':2})
        with self.assertRaises(ValueError): self.controller.prepare_history_read(self.root,4)
        response={'thread':{'id':self.root,'turns':[]},'turnsBackwardsCursor':'anchor'}
        page={'data':[{'id':self.question_turn,'status':'completed'}],'nextCursor':None}
        bad_pages=[{**page,'nextCursor':'more'}, {'data':[]},
                   {'data':[{'id':self.question_turn,'status':'inProgress'}]},
                   {'data':[{'id':self.question_turn,'status':'completed','error':{'message':'SYNTHETIC_SECRET'}}]},
                   {'data':page['data']*2}]
        for bad in bad_pages:
            with self.assertRaisesRegex(ValueError,'^interaction_rejected$'):
                self.controller.confirm_resume(response,self.manifest,history_page=bad,history_request_id=3)
        with self.assertRaises(ValueError):
            self.controller.confirm_resume(response,self.manifest,history_page=page,history_request_id=4)
        with self.assertRaises(ValueError): self.controller.confirm_resume(response,self.manifest)
        self.assertEqual(self.controller.confirm_resume(response,self.manifest,history_page=page,
            history_request_id=3),'resumed')

    def test_question_rejects_foreign_stale_ambiguous_secret_and_malformed_requests(self):
        self.controller.begin('question', self.question_turn)
        variants = [None, [], {}, self.callback()]
        variants[-1]['params']['threadId'] = str(uuid4())
        for field, value in [('turnId', str(uuid4())), ('isBlocking', False), ('itemId', '')]:
            v = self.callback(); v['params'][field] = value; variants.append(v)
        for field, value in [('isOther', 'invalid'), ('isSecret', True), ('question', 'SYNTHETIC_SECRET')]:
            v = self.callback(); v['params']['questions'][0][field] = value; variants.append(v)
        v = self.callback(); v['params']['questions'][0]['options'][1]['label'] = 'Alpha'; variants.append(v)
        for value in variants:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^interaction_rejected$'):
                self.controller.reply(value)
        self.controller.reply(self.callback())
        with self.assertRaises(ValueError): self.reopen().reply(self.callback(request_id=18))

    def test_request_resolution_matches_issued_identity_once(self):
        self.controller.begin('question', self.question_turn)
        self.controller.reply(self.callback())
        for value in [self.resolved(18), self.resolved('17'), {'method': 'serverRequest/resolved',
            'params': {'threadId': str(uuid4()), 'requestId': 17}}]:
            with self.assertRaises(ValueError): self.controller.resolved(value)
        self.controller.resolved(self.resolved())
        with self.assertRaises(ValueError): self.controller.resolved(self.resolved())

    def test_permission_rejects_extra_grants_changed_command_and_wrong_consumer(self):
        self.resume(); self.controller.begin('permission', self.permission_turn)
        for field, value in [('additionalPermissions', {'fileSystem': {'write': ['C:\\']}}),
            ('networkApprovalContext', {}), ('approvalId', 'different-action'), ('environmentId', 'remote'),
            ('kind', 'stdin'), ('command', self.command + '; Write-Output bad'), ('cwd', 'C:\\foreign')]:
            v = self.callback('permission')
            v['params'].update(proposedExecpolicyAmendment=['python'],
                proposedNetworkPolicyAmendments=[{'host':'*','action':'allow'}])
            v['params'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.controller.reply(v, cwd=self.cwd, python_executable=self.python)
        self.controller.reply(self.callback('permission'), cwd=self.cwd, python_executable=self.python)
        with self.assertRaises(ValueError): self.controller.reply(self.callback('permission'), cwd=self.cwd, python_executable=self.python)

    def test_offered_policy_proposals_do_not_change_single_command_acceptance(self):
        self.resume(); self.controller.begin('permission', self.permission_turn)
        callback = self.callback('permission')
        callback['params'].update(proposedExecpolicyAmendment=['SYNTHETIC_SECRET'],
            proposedNetworkPolicyAmendments=[{'host':'SYNTHETIC_SECRET','action':'allow'}],
            availableDecisions=['accept','acceptForSession',
                {'acceptWithExecpolicyAmendment':{'execpolicy_amendment':['SYNTHETIC_SECRET']}}])
        response = self.controller.reply(callback, cwd=self.cwd, python_executable=self.python)
        self.assertEqual(response, {'id':callback['id'], 'result':{'decision':'accept'}})
        with self.store.request(self.origin, self.request) as state:
            self.assertNotIn('SYNTHETIC_SECRET', json.dumps(state))
        with self.assertRaises(ValueError):
            self.controller.reply(callback, cwd=self.cwd, python_executable=self.python)

    def test_permission_needs_same_item_successful_exact_marker_and_resolution(self):
        self.permission()
        with self.assertRaises(ValueError): self.controller.completed(self.turn_completed(self.permission_turn))
        for field, value in [('id', 'foreign-item'), ('command', self.command + '; bad'), ('exitCode', True),
            ('exitCode', 1), ('aggregatedOutput', 'prefix HAR5_APPROVED'), ('status', 'failed')]:
            event = self.command_completed(); event['params']['item'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.controller.completed(event)
        self.controller.completed(self.command_completed())
        with self.assertRaises(ValueError): self.controller.completed(self.turn_completed(self.permission_turn))
        self.controller.resolved(self.resolved(18))
        self.controller.completed(self.turn_completed(self.permission_turn))

    def test_callback_number_can_restart_after_resume_but_remains_single_use(self):
        self.resume(); self.controller.begin('permission', self.permission_turn)
        self.controller.reply(self.callback('permission', 17), cwd=self.cwd, python_executable=self.python)
        with self.assertRaisesRegex(ValueError, '^interaction_rejected$'):
            self.controller.reply(self.callback('permission', 17), cwd=self.cwd, python_executable=self.python)
        self.controller.resolved(self.resolved(17))
        with self.assertRaises(ValueError): self.controller.resolved(self.resolved(17))

    def test_interruption_expiry_and_clock_rollback_persist_closed_admission(self):
        for action in ('interrupted', 'expiry', 'rollback'):
            with self.subTest(action=action):
                self.request = str(uuid4())
                self.now[:] = [10000., 1000.]
                self.store.submit(self.origin, self.request, 'native-foundation', 120)
                self.store.claim_launch(self.origin, self.request)
                self.controller = self.reopen()
                self.controller.bind(self.root, self.manifest, cwd=self.cwd, python_executable=self.python)
                if action == 'interrupted': self.store.stop(self.origin, self.request, 'interrupted')
                elif action == 'expiry': self.now[:] = [10110, 1110]
                else: self.now[:] = [9999, 1001]
                with self.assertRaises(ValueError): self.controller.begin('question', self.question_turn)
                result = self.store.get(self.origin, self.request)
                self.assertFalse(result['admission_open'])
                self.assertEqual(result['first_failure'], {'interrupted': 'interrupted',
                    'expiry': 'deadline_exhausted', 'rollback': 'clock_changed'}[action])

    def test_permission_rejects_malformed_required_fields_and_decision_lists(self):
        self.resume(); self.controller.begin('permission', self.permission_turn)
        for field, value in [('startedAtMs', True), ('startedAtMs', None),
                             ('availableDecisions', 'accept'), ('availableDecisions', {'accept': True})]:
            event = self.callback('permission'); event['params'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.controller.reply(event, cwd=self.cwd, python_executable=self.python)
        self.controller.reply(self.callback('permission'), cwd=self.cwd, python_executable=self.python)

    def test_concurrent_replies_prepare_only_one_envelope(self):
        self.controller.begin('question', self.question_turn)
        def reply(_):
            try: return self.reopen().reply(self.callback())
            except ValueError: return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(v is not None for v in pool.map(reply, range(8))), 1)

    def test_origin_binding_frozen_inputs_and_private_records(self):
        foreign = Interactions(self.store, str(uuid4()), self.request)
        with self.assertRaises(PermissionError): foreign.begin('question', self.question_turn)
        for root, manifest, cwd, python in [(str(uuid4()), self.manifest, self.cwd, self.python),
            (self.root, 'b' * 64, self.cwd, self.python), (self.root, self.manifest, 'C:\\changed', self.python)]:
            with self.assertRaises(ValueError): self.reopen().bind(root, manifest, cwd=cwd, python_executable=python)
        self.controller.begin('question', self.question_turn)
        bad = self.callback(); bad['params']['questions'][0]['question'] = 'SYNTHETIC_SECRET'
        with self.assertRaisesRegex(ValueError, '^interaction_rejected$'): self.controller.reply(bad)
        for path in Path(self.directory.name).rglob('*'):
            if path.is_file(): self.assertNotIn(b'SYNTHETIC_SECRET', path.read_bytes())
        self.assertTrue(all(v == 'skipped' for v in self.store.get(self.origin, self.request)['checks'].values()))


if __name__ == '__main__':
    unittest.main()
