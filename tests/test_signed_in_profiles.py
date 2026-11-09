"""Synthetic profile records exercise controller binding; no real credentials."""
import concurrent.futures
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from evaluation.signed_in import RequestStore
from evaluation import signed_in_native as native
from evaluation import signed_in_profiles as profiles
from evaluation.signed_in_interactions import Interactions


class ProfileGuards(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name).resolve()
        self.root = self.base / 'Harness/project'
        self.root.mkdir(parents=True)
        self.home = self.base / '.tmp/h12-n-12345678' / ('auth-profile-' + str(uuid4()))
        self.home.mkdir(parents=True)
        self.auth = self.home / 'auth.json'
        self.auth.write_text('SYNTHETIC_SECRET', encoding='utf-8')
        self.now = [10000., 1000.]
        self.store = RequestStore(self.root / '.tmp/evaluation-signed-in', clock=lambda: tuple(self.now))
        self.origin, self.request, self.thread = (str(uuid4()) for _ in range(3))
        self.profile_id = str(uuid4())
        self.setup = {'operation_id': self.profile_id, 'home': str(self.home), 'status': 'authenticated_only',
                      'account_type': 'chatgpt', 'cleanup_verified': True, 'model_turns': 0,
                      'evaluated_requests': 0, 'credentials_copied': False,
                      'job_cleanup': {'job_empty': True, 'within_budget': True,
                                      'closure_failed': False, 'termination_failed': False}}
        self.choice = {'model': 'gpt-6-luna', 'effort': 'low'}

    def register(self, setup=None, origin=None, digest='a' * 64):
        return profiles.register_profile(self.store, origin or self.origin,
            self.setup if setup is None else setup, digest, root=self.root)

    def test_explicit_handoff_reuses_home_without_reassigning_owner(self):
        original = self.register()
        target = str(uuid4())
        with self.assertRaises(RuntimeError):
            self.resolve(origin=target)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('No file contents')), \
             patch.object(Path, 'read_text', side_effect=AssertionError('No file contents')):
            granted = profiles.authorize_profile_handoff(self.store, self.origin, target, original, root=self.root)
            self.assertEqual(self.resolve(origin=target), (self.home, granted))
        self.assertEqual(self.resolve(), (self.home, original))
        self.assertNotEqual(granted, original)
        self.assertEqual(profiles.authorize_profile_handoff(self.store, self.origin, target, original,
                                                         root=self.root), granted)
        with self.assertRaises(RuntimeError):
            self.resolve(origin=str(uuid4()))
        with self.store.transaction() as connection:
            owner = connection.execute('SELECT origin FROM profiles WHERE profile_id=?',
                                       (self.profile_id,)).fetchone()[0]
        self.assertEqual(owner, self.origin)
        self.assertEqual(self.auth.read_text(), 'SYNTHETIC_SECRET')

    def test_handoff_does_not_adopt_old_requests_or_accept_modified_grants(self):
        original = self.bind()
        target = str(uuid4())
        profiles.authorize_profile_handoff(self.store, self.origin, target, original, root=self.root)
        with self.assertRaises(PermissionError):
            self.store.get(target, self.request)
        with self.store.transaction() as connection:
            raw = connection.execute('SELECT state FROM profile_handoffs WHERE profile_id=? AND origin=?',
                                     (self.profile_id, target)).fetchone()[0]
            grant = json.loads(raw)
            grant['source_origin'] = str(uuid4())
            connection.execute('UPDATE profile_handoffs SET state=? WHERE profile_id=? AND origin=?',
                               (json.dumps(grant), self.profile_id, target))
        with self.assertRaises(RuntimeError):
            self.resolve(origin=target)

    def test_handoff_rejects_stale_reference_and_cannot_chain_grants(self):
        original = self.register()
        target = str(uuid4())
        with self.assertRaisesRegex(ValueError, 'profile_rejected'):
            profiles.authorize_profile_handoff(self.store, self.origin, target,
                {**original, 'reference_sha256': 'b' * 64}, root=self.root)
        granted = profiles.authorize_profile_handoff(self.store, self.origin, target, original, root=self.root)
        with self.assertRaises(ValueError):
            profiles.authorize_profile_handoff(self.store, target, str(uuid4()), granted, root=self.root)
        with self.store.transaction() as connection:
            state = json.loads(connection.execute('SELECT state FROM profiles WHERE profile_id=?',
                                                 (self.profile_id,)).fetchone()[0])
            state['setup_sha256'] = 'b' * 64
            connection.execute('UPDATE profiles SET state=? WHERE profile_id=?', (json.dumps(state), self.profile_id))
        with self.assertRaises(RuntimeError):
            self.resolve(origin=target)

    def resolve(self, origin=None, profile_id=None):
        return profiles.resolve_profile(self.store, origin or self.origin, profile_id or self.profile_id, root=self.root)

    def bind(self):
        ref = self.register()
        self.store.submit(self.origin, self.request, 'native-foundation', 120)
        native.bind_mode(self.store, self.origin, self.request, 'diagnose', self.choice, ref)
        profiles.bind_root(self.store, self.origin, self.request, self.thread, ref)
        return ref

    def test_registration_is_immutable_origin_bound_and_idempotent(self):
        ref = self.register()
        self.assertEqual(self.register(), ref)
        self.assertEqual(self.resolve(), (self.home, ref))
        self.assertEqual(set(ref), {'profile_id', 'reference_sha256'})
        for action in [lambda: self.register(digest='b' * 64), lambda: self.register(origin=str(uuid4())),
                       lambda: self.resolve(origin=str(uuid4())), lambda: self.resolve(profile_id=str(uuid4()))]:
            with self.assertRaises((ValueError, RuntimeError)): action()

    def test_parallel_registration_has_one_stable_reference(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            refs = list(pool.map(lambda _: self.register(), range(8)))
        self.assertEqual(len({r['reference_sha256'] for r in refs}), 1)

    def test_registration_drops_extra_prose_and_never_opens_auth_contents(self):
        setup = {**self.setup, 'access_token': 'SYNTHETIC_SECRET', 'prose': 'SYNTHETIC_SECRET'}
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('credential read')), \
                patch.object(Path, 'read_text', side_effect=AssertionError('credential read')):
            self.register(setup)
            self.resolve()
        self.assertNotIn(b'SYNTHETIC_SECRET', self.store.path.read_bytes())

    def test_setup_status_or_cleanup_does_not_become_authority(self):
        for key, value in [('status', 'prepared_only'), ('account_type', 'apiKey'), ('cleanup_verified', False),
                           ('credentials_copied', True), ('model_turns', 1), ('evaluated_requests', True)]:
            setup = {**self.setup, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError): self.register(setup)
        setup = deepcopy(self.setup); setup['job_cleanup']['termination_failed'] = True
        with self.assertRaises(ValueError): self.register(setup)

    def test_missing_auth_and_startup_overrides_reject_without_reading(self):
        self.register()
        self.auth.unlink()
        with self.assertRaises(RuntimeError): self.resolve()
        self.auth.write_text('SYNTHETIC_SECRET')
        for name in ('.env', 'config.toml', 'AGENTS.md', 'requirements.toml'):
            p = self.home / name; p.write_text('SYNTHETIC_SECRET')
            with self.subTest(name=name), self.assertRaises(RuntimeError): self.resolve()
            p.unlink()
        self.assertEqual(self.resolve()[0], self.home)

    def test_replaced_directory_and_wrong_layout_are_rejected(self):
        self.register()
        moved = self.home.with_name('retained-original')
        self.assertTrue(self.home.resolve().is_relative_to(self.base))
        self.assertTrue(moved.parent.resolve().is_relative_to(self.base))
        self.home.rename(moved)
        self.home.mkdir()
        (self.home / 'auth.json').write_text('OTHER_SYNTHETIC_TOKEN')
        with self.assertRaises(RuntimeError): self.resolve()
        wrong = {**self.setup, 'home': str(self.root / '.codex')}
        with self.assertRaises(ValueError): self.register(wrong)

    def test_normal_token_refresh_does_not_change_profile_reference(self):
        before = self.register()
        self.auth.unlink()
        self.auth.write_text('REFRESHED_SYNTHETIC_SECRET')
        self.assertEqual(self.resolve()[1], before)

    def test_request_cannot_switch_profile_mode_model_or_root(self):
        ref = self.bind()
        native.bind_mode(self.store, self.origin, self.request, 'diagnose', self.choice, ref)
        for mode, choice, profile in [('prepare', self.choice, ref), ('diagnose', {**self.choice, 'effort': 'medium'}, ref),
                                     ('diagnose', self.choice, None), ('diagnose', self.choice, {**ref, 'reference_sha256': 'b' * 64})]:
            with self.assertRaises(ValueError): native.bind_mode(self.store, self.origin, self.request, mode, choice, profile)
        with self.assertRaises(RuntimeError): profiles.bind_root(self.store, self.origin, self.request, str(uuid4()), ref)
        profiles.require_binding(self.store, self.origin, self.request, ref, root=self.root)

    def test_foreign_checkpoint_cannot_adopt_bound_native_session(self):
        ref = self.bind()
        self.store.claim_launch(self.origin, self.request)
        controller = Interactions(self.store, self.origin, self.request)
        with self.assertRaises(ValueError):
            controller.bind(str(uuid4()), 'c' * 64, cwd=str(self.root), python_executable=str(Path(__file__).resolve()))
        controller.bind(self.thread, 'c' * 64, cwd=str(self.root), python_executable=str(Path(__file__).resolve()))
        with self.store.request(self.origin, self.request) as state:
            self.assertEqual(state['native_interaction']['native_profile'], ref)
            state['native_profile'] = {**ref, 'reference_sha256': 'b' * 64}
        with self.assertRaises(ValueError): controller.begin('question', str(uuid4()))
        with self.store.request(self.origin, self.request) as state:
            state['native_profile'] = ref
            del state['native_mode']
        with self.assertRaises(ValueError): controller.begin('question', str(uuid4()))

    def test_live_send_rechecks_profile_and_cleanup_never_starts_new_work(self):
        ref = self.bind()
        client = native.NativeConnection.__new__(native.NativeConnection)
        client.mode, client.profile = 'diagnose', ref
        client.owner = SimpleNamespace(store=self.store, origin=self.origin, request_id=self.request,
            lock=threading.RLock(), remaining=lambda *a, **kw: 2)
        client.process = SimpleNamespace(stdin=io.StringIO())
        with patch.object(native, 'ROOT', self.root):
            client.send({'id': 1, 'method': 'thread/read', 'params': {'threadId': self.thread}})
            (self.home / '.env').write_text('SYNTHETIC_SECRET')
            with self.assertRaises(RuntimeError): client.send({'id': 2, 'method': 'thread/read', 'params': {'threadId': self.thread}})
            with self.assertRaises(RuntimeError): client.send({'id': 2, 'method': 'thread/start', 'params': {}}, cleanup=True)
            client.send({'id': 2, 'method': 'turn/interrupt', 'params': {'threadId': self.thread}}, cleanup=True)
        sent = client.process.stdin.getvalue()
        self.assertEqual(len(sent.splitlines()), 2)
        self.assertNotIn('SYNTHETIC_SECRET', sent)

    def test_diagnose_without_registered_profile_allocates_no_work(self):
        payload = {'request_id': self.request, 'case': 'native-foundation', 'seconds': 120, **self.choice}
        with patch.object(native, 'ROOT', self.root), patch.dict('os.environ', CODEX_THREAD_ID=self.origin), \
                patch('evaluation.signed_in_process.AttemptProcesses') as owner:
            with self.assertRaises(ValueError): native.run_native(payload, mode='diagnose')
            payload['profile_id'] = self.profile_id
            with self.assertRaises((RuntimeError, ValueError)): native.run_native(payload, mode='diagnose')
            owner.assert_not_called()
        with self.assertRaises(KeyError): self.store.get(self.origin, self.request)

    def test_unbound_transport_cannot_start_models_or_read_account(self):
        client = native.NativeConnection.__new__(native.NativeConnection)
        client.mode, client.profile = 'diagnose', None
        client.owner = SimpleNamespace(lock=threading.RLock(), remaining=lambda **kwargs: 2)
        client.process = SimpleNamespace(stdin=io.StringIO())
        for method in ('turn/start', 'account/read'):
            with self.subTest(method=method), self.assertRaisesRegex(RuntimeError, '^native_method_blocked$'):
                client.send({'id': 1, 'method': method, 'params': {}})
        self.assertEqual(client.process.stdin.getvalue(), '')

    def test_bound_model_start_requires_launch_claim_and_exact_issued_root(self):
        ref = self.bind()
        client = native.NativeConnection.__new__(native.NativeConnection)
        client.mode, client.profile = 'diagnose', ref
        client.owner = SimpleNamespace(store=self.store, origin=self.origin, request_id=self.request,
            lock=threading.RLock(), remaining=lambda *a, **kw: 2)
        client.process = SimpleNamespace(stdin=io.StringIO())
        with patch.object(native, 'ROOT', self.root):
            with self.assertRaises(RuntimeError):
                client.send({'id': 1, 'method': 'turn/start', 'params': {'threadId': self.thread}})
            self.store.claim_launch(self.origin, self.request)
            with self.assertRaises(RuntimeError):
                client.send({'id': 1, 'method': 'turn/start', 'params': {'threadId': str(uuid4())}})
            client.send({'id': 1, 'method': 'turn/start', 'params': {'threadId': self.thread}})
        self.assertEqual(len(client.process.stdin.getvalue().splitlines()), 1)

    def test_profile_reference_and_catalog_never_contain_auth_prose(self):
        ref = self.bind()
        with self.store.request(self.origin, self.request) as state:
            self.assertEqual(state['native_profile'], ref)
        text = json.dumps(self.store.get(self.origin, self.request))
        self.assertNotIn(str(self.home), text)
        self.assertNotIn('SYNTHETIC_SECRET', text)


if __name__ == '__main__':
    unittest.main()
