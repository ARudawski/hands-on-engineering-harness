"""Paired native protocol traces, not model behavior or primary acceptance."""
from collections import deque
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from evaluation.signed_in_workflow import CandidateObservation
from evaluation import signed_in_native as native


class OpenObservation(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.consumer = Path(directory.name); (self.consumer/'.tmp').mkdir()
        self.root, self.turn = str(uuid4()), str(uuid4())
        self.result = {'root_thread_id':self.root,'installation':{'files':{}},'boundary_passed':True}
        self.metadata = {self.root:{'id':self.root,'source':'appServer','status':{'type':'idle'}}}
        def read(method, params, **kwargs):
            self.assertEqual(method, 'thread/read')
            self.assertIs(params['includeTurns'], False)
            return {'thread':self.metadata[params['threadId']]}
        self.connection = SimpleNamespace(owner=SimpleNamespace(remaining=lambda:90),pending=deque(),call=Mock(side_effect=read))
        self.observer = CandidateObservation(self.connection,self.result,lambda:None,consumer=self.consumer,marker='PROTECTED_CANARY')

    def turn_event(self, thread, turn, status='completed'):
        return {'method':'turn/completed' if status != 'inProgress' else 'turn/started',
                'params':{'threadId':thread,'turn':{'id':turn,'status':status}}}

    def message(self, thread, turn, text, item='message'):
        return {'method':'item/completed','params':{'threadId':thread,'turnId':turn,
                'item':{'id':item,'type':'agentMessage','text':text}}}

    def child(self, identifier, name, parent=None):
        self.metadata[identifier] = {'id':identifier,'cwd':str(self.consumer),'agentRole':name,
            'source':{'subAgent':{'thread_spawn':{'parent_thread_id':parent or self.root}}},'status':{'type':'idle'}}
        return {'method':'thread/started','params':{'thread':self.metadata[identifier]}}

    def test_changed_roles_counts_and_free_form_messages_do_not_change_completion(self):
        for count in (0,1,3):
            observer = CandidateObservation(self.connection,self.result,lambda:None,consumer=self.consumer,marker='PROTECTED_CANARY')
            observer.feed(self.message(self.root,self.turn,'Ordinary assessment; two findings and a question.'))
            observer.feed(self.turn_event(self.root,self.turn))
            for n in range(count):
                child, turn = str(uuid4()), str(uuid4())
                observer.feed(self.child(child,'specialist_'+str(n)))
                observer.feed(self.message(child,turn,'Review in my usual format.'))
                observer.feed(self.turn_event(child,turn))
            observer.reconcile()
            self.assertTrue(observer.complete())
            report = observer.snapshot('completed')
            self.assertEqual(report['task_assessment'],'unassessed')
            self.assertEqual(len(report['participants']),count+1)

    def test_optional_child_failure_does_not_erase_recovered_root_assessment(self):
        child,turn=str(uuid4()),str(uuid4())
        self.observer.feed(self.child(child,'optional'))
        self.observer.feed({'method':'item/started','params':{'threadId':child,'turnId':turn,
            'item':{'id':'aborted_command','type':'commandExecution'}}})
        self.observer.feed(self.turn_event(child,turn,'failed'))
        self.observer.feed(self.message(self.root,self.turn,'After adds1: [2,3]6 instead of5.'))
        self.observer.feed(self.turn_event(self.root,self.turn))
        self.observer.reconcile()
        self.assertTrue(self.observer.complete())
        report=self.observer.snapshot('completed')
        self.assertEqual(report['infrastructure_limitations'],[])
        self.assertIn({'thread_id':child,'turn_id':turn,'status':'failed'},report['turns'])
        self.assertEqual(report['behavior_warnings'],[{'kind':'turn_failed','thread_id':child,'turn_id':turn}])

    def test_failed_earlier_root_can_recover_but_failed_or_incomplete_latest_root_has_no_frame(self):
        self.observer.feed(self.turn_event(self.root,self.turn,'failed'))
        self.assertIsNone(self.observer.seal_completion())
        later=str(uuid4());self.observer.begin_root_turn(later)
        self.observer.feed(self.message(self.root,later,'Correct recovered assessment'))
        self.assertIsNone(self.observer.seal_completion())
        self.observer.feed(self.turn_event(self.root,later));self.observer.reconcile()
        self.assertTrue(self.observer.complete())
        self.assertEqual(self.observer.seal_completion()['turn'],later)
        self.assertEqual(self.observer.limitations,set())

    def test_delayed_failure_of_earlier_turn_does_not_replace_current_turn(self):
        current=str(uuid4());self.observer.begin_root_turn(current)
        self.observer.feed(self.turn_event(self.root,self.turn,'failed'))
        self.observer.feed(self.message(self.root,current,'Recovered assessment'))
        self.observer.feed(self.turn_event(self.root,current));self.observer.reconcile()
        self.assertTrue(self.observer.complete())
        self.assertEqual(self.observer.root_turn(),current)
        self.assertEqual(self.observer.seal_completion()['turn'],current)

    def test_failed_root_waits_for_active_child_pending_question_and_unfinished_work(self):
        child,turn=str(uuid4()),str(uuid4())
        self.observer.feed(self.child(child,'optional'))
        self.observer.feed(self.turn_event(self.root,self.turn,'failed'))
        self.observer.feed(self.turn_event(child,turn,'inProgress'));self.observer.reconcile()
        self.assertFalse(self.observer.quiescent())
        self.observer.feed(self.turn_event(child,turn));self.assertTrue(self.observer.quiescent())
        request={'id':7,'method':'item/tool/requestUserInput','params':{'threadId':self.root,'turnId':self.turn}}
        self.observer.feed(request);self.assertFalse(self.observer.quiescent())
        self.observer.feed({'method':'serverRequest/resolved','params':{'threadId':self.root,'requestId':7}})
        self.assertTrue(self.observer.quiescent())
        self.observer.feed({'method':'item/started','params':{'threadId':child,'turnId':turn,
            'item':{'id':'unconfirmed','type':'commandExecution'}}})
        self.assertFalse(self.observer.quiescent())

    def test_completion_time_is_immediate_but_frame_includes_queued_messages_and_is_retired(self):
        with patch('evaluation.signed_in_workflow.time.time',return_value=123):
            self.observer.feed(self.turn_event(self.root,self.turn))
        self.connection.pending.append(self.message(self.root,self.turn,'Queued assessment'))
        self.observer.reconcile();self.observer.drain_observations()
        frame=self.observer.seal_completion()
        self.assertEqual(frame['observed_at'],123)
        self.assertEqual(frame['messages'][0]['text'],'Queued assessment')
        self.observer.feed(self.message(self.root,self.turn,'Further output','later'))
        self.assertFalse(self.observer.frame_current(frame))
        self.observer.retire_completion()
        self.assertIsNone(self.observer.seal_completion())
        next_turn=str(uuid4());self.observer.begin_root_turn(next_turn)
        self.assertIsNone(self.observer.seal_completion())
        self.observer.feed(self.turn_event(self.root,next_turn,'failed'))
        self.assertIsNone(self.observer.seal_completion())

    def test_root_and_child_snapshot_settings_survive_metadata_without_fields(self):
        self.result['thread_configuration']={'model':'requested-root','effort':'low'}
        observer=CandidateObservation(self.connection,self.result,lambda:None,consumer=self.consumer,marker='PROTECTED_CANARY')
        child,turn=str(uuid4()),str(uuid4())
        observer.feed({'method':'item/completed','params':{'threadId':self.root,'turnId':self.turn,
            'item':{'id':'activity','type':'subAgentActivity','kind':'started','agentThreadId':child,
                    'model':'different-child','reasoningEffort':'high'}}})
        observer.feed(self.child(child,'varied'))
        observer.feed(self.turn_event(child,turn));observer.feed(self.turn_event(self.root,self.turn))
        observer.reconcile()
        participants={p['thread_id']:p for p in observer.snapshot('completed')['participants']}
        self.assertEqual(participants[self.root]['thread_configuration'],{'model':'requested-root','effort':'low'})
        self.assertEqual(participants[child]['thread_configuration'],{'model':'different-child','effort':'high'})
        self.assertEqual(participants[child]['role'],'varied')
        self.assertEqual(participants[child]['execution_settings'],'unknown')

    def test_interleaved_early_events_duplicate_notifications_and_followups_are_allowed(self):
        child, turn, followup = str(uuid4()), str(uuid4()), str(uuid4())
        early = self.message(child,turn,'First attempt')
        self.observer.feed(early)
        self.observer.feed(self.child(child,'renamed_role'))
        self.observer.feed(early)  # Equivalent duplicate must not duplicate prose.
        self.observer.feed(self.turn_event(child,turn))
        self.observer.feed(self.turn_event(child,turn,'inProgress'))  # Late started notification.
        self.observer.feed(self.message(child,followup,'Corrected after investigation','followup'))
        self.observer.feed(self.turn_event(child,followup))
        self.observer.feed(self.turn_event(self.root,self.turn))
        self.observer.reconcile()
        self.assertTrue(self.observer.complete())
        self.assertEqual(len(self.observer.snapshot('completed')['agent_messages']),2)

    def test_pending_decisions_wait_to_deadline_without_auto_reply(self):
        for method in ('item/tool/requestUserInput','item/commandExecution/requestApproval','item/fileChange/requestApproval'):
            observer = CandidateObservation(self.connection,self.result,lambda:None,consumer=self.consumer,marker='PROTECTED_CANARY')
            observer.feed({'id':17,'method':method,'params':{'threadId':self.root,'turnId':self.turn}})
            observer.feed(self.turn_event(self.root,self.turn))
            observer.reconcile()
            self.assertFalse(observer.complete())
            report = observer.snapshot('deadline')
            self.assertTrue(report['waiting'])
            self.assertEqual(report['execution_end'],'deadline')
            self.assertEqual(report['infrastructure_limitations'],[])
            self.assertTrue(all(c.args[0]=='thread/read' for c in self.connection.call.call_args_list))

    def test_nested_reordered_events_reconcile_without_assuming_root_is_the_parent(self):
        child, grandchild, a, b = (str(uuid4()) for _ in range(4))
        self.observer.feed(self.message(grandchild,b,'Early nested assessment'))
        self.observer.feed(self.turn_event(grandchild,b))
        self.observer.feed(self.child(grandchild,'nested',parent=child))
        self.observer.feed(self.child(child,'parent_role'))
        self.observer.feed(self.turn_event(child,a))
        self.observer.feed(self.turn_event(self.root,self.turn))
        self.observer.reconcile()
        self.assertTrue(self.observer.complete())
        self.assertEqual(self.observer.threads[grandchild]['parent'],child)

    def test_interrupted_followup_is_not_a_successful_root_completion(self):
        self.observer.feed(self.turn_event(self.root,self.turn))
        self.observer.feed(self.turn_event(self.root,str(uuid4()),'interrupted'))
        self.observer.reconcile()
        self.assertFalse(self.observer.complete())
        report = self.observer.snapshot('interrupted')
        self.observer.finalize_cleanup(True)
        self.assertEqual(report['execution_end'],'interrupted')
        self.assertEqual(report['cleanup'],'verified')
        self.assertEqual(report['task_assessment'],'unassessed')

    def test_root_done_child_active_and_cleanup_failure_are_distinct(self):
        child, turn = str(uuid4()), str(uuid4())
        self.observer.feed(self.child(child,'worker'))
        self.observer.feed(self.turn_event(child,turn,'inProgress'))
        self.observer.feed(self.turn_event(self.root,self.turn))
        self.observer.reconcile()
        self.assertFalse(self.observer.complete())
        report = self.observer.snapshot('deadline')
        self.observer.finalize_cleanup(False)
        self.assertEqual(report['execution_end'],'deadline')
        self.assertEqual(report['cleanup'],'failed')
        self.assertFalse(report['primary_acceptance'])
        self.observer.feed(self.turn_event(child,turn))
        self.observer.reconcile()
        self.assertTrue(self.observer.complete())

    def test_only_native_introduced_metadata_is_queried_and_wrong_parent_rejected(self):
        child, turn = str(uuid4()), str(uuid4())
        activity = {'method':'item/completed','params':{'threadId':self.root,'turnId':self.turn,
            'item':{'id':'spawn','type':'subAgentActivity','kind':'started','agentThreadId':child}}}
        self.observer.feed(activity)
        self.child(child,'role')
        self.observer.feed(self.message(child,turn,'Buffered until metadata confirms parent'))
        self.observer.reconcile()
        self.assertIn(child,self.observer.threads)
        self.assertFalse(self.observer.can_read_metadata(str(uuid4())))
        self.metadata[child]['source']['subAgent']['thread_spawn']['parent_thread_id'] = str(uuid4())
        with self.assertRaisesRegex(RuntimeError,'^candidate_observation_incomplete$'):
            self.observer.reconcile()
        with self.assertRaisesRegex(RuntimeError,'^protected_disclosure$'):
            self.observer.feed(self.message(self.root,self.turn,'PROTECTED_CANARY'))

    def test_task_records_and_scratch_files_are_allowed_but_case_drift_is_rejected(self):
        with patch('evaluation.signed_in_workflow.WindowsPathLocks'):
            self.observer.materialize()
        (self.consumer/'.tmp/work/notes.md').write_text('Ordinary notes')
        (self.consumer/'.tmp/work/build').mkdir()
        (self.consumer/'.tmp/work/build/output.txt').write_text('Ordinary artifact')
        self.observer.unchanged()
        (self.consumer/'case/after.py').write_text('Changed immutable input')
        with self.assertRaisesRegex(RuntimeError,'^candidate_input_changed$'):
            self.observer.unchanged()

    def test_candidate_observation_is_internal_and_exclusive(self):
        payload={'request_id':str(uuid4()),'case':'native-foundation','seconds':120,
                 'candidate_revision':'a'*40,'model':'gpt-6-luna','effort':'low'}
        with patch.object(native,'RequestStore') as factory:
            for flags in [dict(mode='prepare',candidate_run=True),dict(mode='diagnose',candidate_run=True,workflow_probe=True),
                          dict(mode='diagnose',candidate_run='yes'),dict(mode='diagnose')]:
                with self.assertRaises(ValueError):
                    native.run_native(payload,**flags)
            factory.assert_not_called()
        with patch.object(native,'RequestStore') as factory:
            with self.assertRaisesRegex(ValueError,'^candidate_admission_unverified$'):
                native.run_native({**payload,'profile_id':str(uuid4())},mode='diagnose',candidate_run=True)
            factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
