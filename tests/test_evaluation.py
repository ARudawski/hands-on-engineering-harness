"""Credential/model-free evaluation guards, included in ordinary package discovery."""

import copy
import http.client
import http.server
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import sys
import io
import os
import unittest
from unittest.mock import patch, Mock
import subprocess


def module(name):
    sys.path.insert(0, str(Path(__file__).parent / 'evaluation'))
    spec = importlib.util.spec_from_file_location('evaluation_' + name, Path(__file__).parent / 'evaluation' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


relay = module('relay')
controller = module('run')
native = module('native')
probes = module('probes')
worker = module('worker')


class EvaluationGuards(unittest.TestCase):
    def test_pinned_skill_inventory_accepts_old_and_new_packages_but_not_missing_skills(self):
        baseline = {f'.apm/skills/{name}/SKILL.md' for name in (
            'clarify-scope', 'write-spec', 'plan-slices', 'plan-feature', 'deliver-task', 'implement-slice', 'review-code')}
        for expected in (baseline, baseline | {'.apm/skills/deliver-code/SKILL.md'}):
            with self.subTest(count=len(expected)):
                pinned = {p: 'pinned-hash' for p in expected | {'README.md'}}
                worker.verify_skill_inventory(pinned, expected)
                for missing in expected:
                    with self.assertRaisesRegex(RuntimeError, 'Skill inventory'):
                        worker.verify_skill_inventory(pinned, expected - {missing})
                with self.assertRaisesRegex(RuntimeError, 'Skill inventory'):
                    worker.verify_skill_inventory(pinned, expected | {'.apm/skills/foreign/SKILL.md'})
        incomplete = baseline - {'.apm/skills/write-spec/SKILL.md'}
        with self.assertRaisesRegex(RuntimeError, 'Skill inventory'):
            worker.verify_skill_inventory(incomplete, incomplete)

    def setUp(self):
        self.request = {'model': 'fixed', 'reasoning': {'effort': 'xhigh', 'context': 'all_turns'}, 'store': False,
                        'stream': True, 'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'public probe'}]}]}

    def test_request_cannot_expand_authority(self):
        invalid = [{'previous_response_id': 'foreign'}, {'conversation': 'foreign'}, {'prompt': {'id': 'foreign'}},
                   {'tools': [{'type': 'web_search'}]}, {'tools': [{'type': 'namespace', 'tools': [{'type': 'mcp'}]}]},
                   {'input': [{'type': 'additional_tools', 'role': 'developer', 'tools': [{'type': 'web_search'}]}]},
                   {'store': True}, {'model': 'foreign'}, {'reasoning': {'effort': 'low'}},
                   {'input': [{'type': 'item_reference', 'id': 'foreign'}]},
                   {'input': [{'role': 'user', 'content': [{'type': 'input_image', 'image_url': 'https://foreign'}]}]},
                   {'input': [{'type': 'function_call_output', 'output': [{'type': 'input_file', 'file_id': 'foreign'}]}]},
                   {'max_output_tokens': True}, {'max_output_tokens': 100000}]
        for delta in invalid:
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                relay.validate({**self.request, **delta}, 'fixed', 'xhigh', 'trial')
        valid = relay.validate({**self.request, 'tools': [{'type': 'namespace', 'tools': [{'type': 'function', 'name': 'local'}]}]}, 'fixed', 'xhigh', 'trial')
        self.assertEqual(valid['prompt_cache_key'], 'trial')
        self.assertEqual(valid['max_output_tokens'], 4096)

    def test_local_reviewer_envelopes_cannot_reference_hosted_resources(self):
        message = {'type': 'agent_message', 'author': '/root', 'recipient': '/root/reviewer',
                   'content': [{'type': 'input_text', 'text': 'public scope'},
                               {'type': 'encrypted_content', 'encrypted_content': 'opaque-native-context'}]}
        request = {**self.request, 'input': [message]}
        self.assertEqual(relay.validate(request, 'fixed', 'xhigh', 'trial')['input'], [message])
        for content in ([{'type': 'input_file', 'file_id': 'foreign'}],
                        [{'type': 'input_text', 'text': 'x', 'file_id': 'foreign'}]):
            with self.subTest(content=content), self.assertRaises(ValueError):
                relay.validate({**request, 'input': [{**message, 'content': content}]}, 'fixed', 'xhigh', 'trial')
        safe = native.public_event(message)
        self.assertEqual(safe['content'], [{'type': 'input_text', 'text': 'public scope'}])

    def test_real_relay_denial_and_quota_include_direct_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            state = relay.Relay(directory, 'fixed', 'xhigh', 'trial', 'fixture-only-never-forwarded')
            server = relay.Server(('127.0.0.1', 0), state)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.object(relay.http.client, 'HTTPSConnection') as upstream:
                    for delta in ({'previous_response_id': 'foreign'}, {'store': True}, {}):
                        client = http.client.HTTPConnection(*server.server_address, timeout=3)
                        client.request('POST', '/v1/responses', json.dumps({**self.request, **delta}))
                        response = client.getresponse()
                        self.assertEqual(response.status, 403)
                        response.read()
                        client.close()
                    upstream.assert_not_called()
                    self.assertEqual(state.meter['requests'], 3)
                    self.assertEqual(state.meter['accepted'], 0)
                    Path(directory, 'control.json').write_text(json.dumps({'trial': 'trial', 'expires': time.time() + 5}))
                    state.meter['requests'] = relay.MAX_REQUESTS
                    client = http.client.HTTPConnection(*server.server_address, timeout=3)
                    client.request('POST', '/v1/responses', json.dumps(self.request))
                    response = client.getresponse()
                    self.assertEqual(response.status, 403)
                    self.assertIn('quota', response.read().decode())
                    client.close()
                    upstream.assert_not_called()
            finally:
                state.stop.set()
                server.shutdown()
                server.server_close()

    def test_relay_restart_does_not_reset_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            state = relay.Relay(directory, 'fixed', 'xhigh', 'trial', 'fixture')
            state.stop.set()
            with self.assertRaisesRegex(RuntimeError, 'reset'):
                relay.Relay(directory, 'fixed', 'xhigh', 'trial', 'fixture')

    def test_disarm_terminates_blocked_upstream_setup_process(self):
        # Real subprocess: process exit must interrupt the pre-socket phase,
        # rather than leaving a thread able to send once connect returns.
        with tempfile.TemporaryDirectory() as directory:
            script = '''import sys,time,json,pathlib,threading,http.client
sys.path.insert(0,sys.argv[1])
from relay import Relay,Server
root=pathlib.Path(sys.argv[2])
class Delayed:
    sock=None
    def __init__(self,*a,**k): pass
    def request(self,*a,**k):
        (root/'setup-started').write_text('yes')
        time.sleep(60)
        (root/'late-send').write_text('forbidden')
    def close(self): pass
import relay
relay.http.client.HTTPSConnection=Delayed
state=Relay(root,'fixed','xhigh','trial','public-fixture')
server=Server(('127.0.0.1',0),state)
threading.Thread(target=server.serve_forever,daemon=True).start()
(root/'control.json').write_text(json.dumps({'trial':'trial','expires':time.time()+10}))
request={'model':'fixed','reasoning':{'effort':'xhigh','context':'all_turns'},'store':False,'stream':True,'input':[]}
client=http.client.HTTPConnection(*server.server_address)
client.request('POST','/v1/responses',json.dumps(request))
client.getresponse()
'''
            process = subprocess.Popen([sys.executable, '-c', script, str(Path(relay.__file__).parent), directory],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            root = Path(directory)
            try:
                deadline = time.monotonic() + 5
                while not (root / 'setup-started').exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue((root / 'setup-started').exists())
                # Revoke atomically, just as the controller does.
                (root / 'control.new').write_text(json.dumps({'trial': 'trial', 'expires': 0}))
                (root / 'control.new').replace(root / 'control.json')
                self.assertEqual(process.wait(timeout=2), 70)
                self.assertFalse((root / 'late-send').exists())
                meter = json.loads((root / 'meter.json').read_text())
                self.assertEqual(meter['closed_reason'], 'admission revoked during upstream setup')
                with self.assertRaisesRegex(RuntimeError, 'reset'):
                    relay.Relay(root, 'fixed', 'xhigh', 'trial', 'public-fixture')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)

    def test_native_subagent_activity_retains_actual_child_identity(self):
        class Connection:
            def __init__(self):
                self.events = []
                self.queue = iter([
                    {'method': 'item/completed', 'params': {'threadId': 'parent', 'item': {
                        'type': 'subAgentActivity', 'kind': 'started', 'agentThreadId': 'actual-child'}}},
                    {'method': 'turn/completed', 'params': {'threadId': 'parent', 'turn': {'id': 'turn', 'status': 'completed'}}},
                ])
            def call(self, *args): return {'turn': {'id': 'turn'}}
            def receive(self, *args): return next(self.queue)
        result = probes.run_turn(Connection(), 'parent', 'plan-reviewer', 'scope', 'fixed', 'xhigh',
                                 lambda: None, lambda: None, time.monotonic() + 3, lambda _: None)
        self.assertEqual(result['children'], ['actual-child'])

    def test_native_interrupt_cleans_descendants_before_stability_readback(self):
        class Connection:
            sequence = 0
            stopped = False
            def call(self, *args): return {'turn': {'id': 'turn'}}
            def send(self, value): self.sent = value
            def receive(self, *args):
                return {'method': 'turn/completed', 'params': {'threadId': 'parent', 'turn': {'id': 'turn', 'status': 'interrupted'}}}
            def close(self): self.stopped = True
        connection = Connection()
        counter = 0
        def heartbeat():
            nonlocal counter
            if not connection.stopped: counter += 1
            return str(counter)
        result = probes.run_turn(connection, 'parent', 'cancellation', 'scope', 'fixed', 'xhigh',
                                 heartbeat, lambda: None, time.monotonic() + 3, lambda _: None)
        self.assertTrue(connection.stopped)
        self.assertEqual(result['termination_method'], 'native-interrupt-and-owned-worker-process-cleanup')
        self.assertLess(result['cancellation_seconds'], 3)

    def test_failed_close_is_not_silently_idempotent(self):
        connection = native.Connection.__new__(native.Connection)
        connection.closed, connection.deadline = False, time.monotonic() + 3
        connection.worker, connection.process, connection.errors = 'exact-owned-worker', Mock(), io.StringIO()
        with patch.object(native.subprocess, 'run', side_effect=OSError('termination unavailable')) as run:
            for _ in range(2):
                with self.assertRaises(OSError):
                    connection.close()
                self.assertFalse(connection.closed)
            self.assertEqual(run.call_count, 4)
        self.assertTrue(connection.errors.closed)

    def test_native_failure_retains_actual_error_before_request_assertions(self):
        class Connection:
            def call(self, *args): return {'turn': {'id': 'turn'}}
            def receive(self, *args):
                return {'method': 'turn/completed', 'params': {'threadId': 'parent', 'turn': {
                    'id': 'turn', 'status': 'failed', 'error': {'message': 'Quota exceeded', 'codexErrorInfo': 'usageLimitExceeded'}}}}
        record = {}
        with self.assertRaisesRegex(RuntimeError, 'Quota exceeded'):
            probes.run_turn(Connection(), 'parent', 'approval', 'scope', 'fixed', 'xhigh',
                            lambda: None, lambda: None, time.monotonic() + 3, lambda _: None, record)
        self.assertEqual(record['error']['codexErrorInfo'], 'usageLimitExceeded')

    def test_response_exhaustion_latches_and_blocks_later_calls(self):
        class Upstream:
            sock = None
            status = 200
            def __init__(self, *args, **kwargs):
                self.chunk = b'x' * (relay.MAX_RESPONSE + 1)
            def request(self, *args, **kwargs):
                pass
            def getresponse(self):
                return self
            def read1(self, count):
                result, self.chunk = self.chunk, b''
                return result
            def close(self):
                pass
        with tempfile.TemporaryDirectory() as directory:
            state = relay.Relay(directory, 'fixed', 'xhigh', 'trial', 'fixture')
            Path(directory, 'control.json').write_text(json.dumps({'trial': 'trial', 'expires': time.time() + 5}))
            server = relay.Server(('127.0.0.1', 0), state)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.object(relay.http.client, 'HTTPSConnection', side_effect=Upstream) as upstream:
                    for expected in (200, 403):
                        client = http.client.HTTPConnection(*server.server_address, timeout=3)
                        client.request('POST', '/v1/responses', json.dumps(self.request))
                        response = client.getresponse()
                        self.assertEqual(response.status, expected)
                        response.read()
                        client.close()
                    self.assertEqual(upstream.call_count, 1)
                    self.assertEqual(state.meter['closed_reason'], 'response quota exhausted')
                    self.assertFalse(state.armed())
            finally:
                state.stop.set()
                server.shutdown()
                server.server_close()

    def test_missing_and_changed_launch_inputs_fail_closed(self):
        config = {'comparison_id': 'comparison', 'case_id': 'case-v1', 'variant': 'candidate',
                  'baseline': 'a' * 40, 'candidate': 'b' * 40, 'model': 'fixed', 'effort': 'xhigh',
                  'image_id': 'sha256:' + 'c' * 64, 'limits': controller.LIMITS.copy(),
                  'codex_version': '0.166.0-alpha.6', 'apm_version': '0.35.0', 'fixture_revision': 'fixture-v1'}
        controller.validate_config(config)
        for key in config:
            missing = dict(config)
            del missing[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                controller.validate_config(missing)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller.write_json(root / 'manifest.json', {'output_dir': str(root.resolve()), 'config': config, 'controller_inputs': {}})
            with self.assertRaisesRegex(ValueError, 'changed'):
                controller.load(root)

    def test_valid_config_changes_rejected_against_frozen_inputs(self):
        config = {'comparison_id': 'comparison', 'case_id': 'case-v1', 'variant': 'candidate',
                  'baseline': 'a' * 40, 'candidate': 'b' * 40, 'model': 'fixed', 'effort': 'xhigh',
                  'image_id': 'sha256:' + 'c' * 64, 'limits': controller.LIMITS.copy(),
                  'codex_version': '0.166.0-alpha.6', 'apm_version': '0.35.0', 'fixture_revision': 'fixture-v1'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = {'config': config, 'engine': {}, 'resources': {}, 'seccomp': {}}
            controller.write_json(root / 'inputs.json', frozen)
            for field, changed in [('model', 'other'), ('case_id', 'other'), ('candidate', 'd' * 40),
                                   ('image_id', 'sha256:' + 'd' * 64), ('fixture_revision', 'other')]:
                manifest = {'output_dir': str(root.resolve()), 'config': {**config, field: changed},
                            'controller_inputs': controller.controller_inputs(), 'resources': {}, 'seccomp': {},
                            'frozen_inputs_sha256': controller.digest(root / 'inputs.json')}
                controller.write_json(root / 'manifest.json', manifest)
                with self.subTest(field=field), patch.object(controller, 'engine_identity', return_value={}), self.assertRaisesRegex(ValueError, 'changed'):
                    controller.load(root)

    def test_native_deadline_cannot_be_extended_by_notifications(self):
        connection = native.Connection.__new__(native.Connection)
        connection.sequence = 0
        connection.deadline = None
        connection.send = lambda value: None
        connection.receive = lambda timeout: {'method': 'notification'}
        with patch.object(native.time, 'monotonic', side_effect=[0, 0.25, 0.5, 2]), self.assertRaises(TimeoutError):
            connection.call('test', {}, timeout=1)

    def test_native_reasoning_removed_from_nested_notifications(self):
        for method in ['item/started', 'item/completed']:
            value = {'method': method, 'params': {'threadId': 'parent', 'item': {'type': 'reasoning', 'summary': ['PRIVATE'], 'content': 'PRIVATE'}}}
            self.assertNotIn('PRIVATE', json.dumps(native.public_event(value)))
        self.assertIsNone(native.public_event({'method': 'item/reasoning/textDelta', 'params': {'delta': 'PRIVATE'}}))

    def test_unavailable_remote_cleanup_verification_stops_owned_worker(self):
        connection = native.Connection.__new__(native.Connection)
        connection.worker, connection.process, connection.errors = 'exact-owned-worker', Mock(), io.StringIO()
        connection.closed = False
        connection.deadline = None
        with patch.object(native.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0), subprocess.TimeoutExpired('readback', 2),
                          subprocess.CompletedProcess([], 0)]) as execute, self.assertRaisesRegex(RuntimeError, 'worker stopped'):
            connection.close()
        self.assertEqual(execute.call_args_list[2].args[0], ['docker', 'stop', '--time', '0', 'exact-owned-worker'])
        self.assertLessEqual(sum(call.kwargs['timeout'] for call in execute.call_args_list), 6)

    def test_probe_responses_require_exact_identity_and_command(self):
        request = {'id': 7, 'method': 'item/commandExecution/requestApproval', 'params': {
            'threadId': 'parent', 'turnId': 'turn', 'cwd': '/work/codex', 'command': 'python -c "print(\'HAR5_APPROVED\')"'}}
        seen = set()
        self.assertEqual(probes.resolve_request(request, 'approval', 'parent', 'turn', seen), {'decision': 'accept'})
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            probes.resolve_request(request, 'approval', 'parent', 'turn', seen)
        with self.assertRaisesRegex(ValueError, 'stale'):
            probes.resolve_request(request, 'approval', 'parent', 'different', set())
        injection = copy.deepcopy(request)
        injection['params']['command'] += '; touch /work/foreign'
        with self.assertRaises(ValueError):
            probes.resolve_request(injection, 'approval', 'parent', 'turn', set())

    def test_only_project_task_root_is_excluded_from_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('.tmp/task', 'module/.tmp/protected'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('record')
            self.assertEqual(set(controller.inventory(root, root_exclude=('.tmp',))), {'module/.tmp/protected'})

    @unittest.skipUnless(os.name == 'posix', 'Relay executes in Linux; Windows pending duplicated-socket reads differ')
    def test_disarm_interrupts_stalled_connection_close_stream(self):
        release = threading.Event()
        class Stalled(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.end_headers()  # HTTP/1.0 detaches HTTPConnection.sock.
                release.wait(5)
            def log_message(self, *args):
                pass
        upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Stalled)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as directory:
            state = relay.Relay(directory, 'fixed', 'xhigh', 'trial', 'fixture')
            control = Path(directory, 'control.json')
            control.write_text(json.dumps({'trial': 'trial', 'expires': time.time() + 5}))
            server = relay.Server(('127.0.0.1', 0), state)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.object(relay.http.client, 'HTTPSConnection', side_effect=lambda *a, **k: http.client.HTTPConnection(*upstream.server_address, timeout=3)):
                    client = http.client.HTTPConnection(*server.server_address, timeout=3)
                    client.request('POST', '/v1/responses', json.dumps(self.request))
                    response = client.getresponse()
                    self.assertEqual(response.status, 200)
                    done = threading.Event()
                    def drain():
                        try:
                            response.read()
                        finally:
                            done.set()
                    threading.Thread(target=drain, daemon=True).start()
                    control.write_text(json.dumps({'trial': 'trial', 'expires': 0}))
                    self.assertTrue(done.wait(2), 'disarm must close the detached active socket')
                    client.close()
            finally:
                release.set()
                state.stop.set()
                server.shutdown(); server.server_close()
                upstream.shutdown(); upstream.server_close()

    def test_effective_permission_drift_rejected(self):
        config = {'model': 'fixed', 'effort': 'xhigh'}
        state = {'model': 'fixed', 'modelProvider': 'evaluation', 'reasoningEffort': 'xhigh', 'cwd': '/work/codex',
                 'approvalPolicy': 'on-request', 'approvalsReviewer': 'user', 'sandbox': copy.deepcopy(controller.NATIVE_SANDBOX),
                 'runtimeWorkspaceRoots': ['/work/codex'], 'instructionSources': []}
        controller.check_effective(state, config)
        for key, value in [('networkAccess', True), ('writableRoots', ['/outside']), ('excludeTmpdirEnvVar', True), ('excludeSlashTmp', True)]:
            changed = copy.deepcopy(state)
            changed['sandbox'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                controller.check_effective(changed, config)
        with self.assertRaises(ValueError):
            controller.check_effective({**state, 'runtimeWorkspaceRoots': ['/outside']}, config)

    def test_near_expired_trial_does_not_launch_or_rearm(self):
        manifest = {'status': 'probe-checkpoint', 'session_id': 'exact', 'probe_deadline': time.time() + 0.1,
                    'turns': [{'kind': 'question', 'status': 'completed'}]}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture'}), \
             patch.object(controller, 'Connection') as launch, patch.object(controller, 'relay_control') as arm:
            with self.assertRaisesRegex(ValueError, 'budget'):
                controller.probe(Path(directory), manifest, resume_session='exact')
            launch.assert_not_called()
            arm.assert_not_called()

    def test_deadline_enforcer_stops_exact_resources_during_stall(self):
        manifest = {'resources': {'worker': 'owned-worker', 'relay': 'owned-relay'}}
        state = {'fired': False}
        with tempfile.TemporaryDirectory() as directory, patch.object(controller.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as execute:
            timer = controller.deadline_watchdog(manifest, time.monotonic() + 2.05, Path(directory) / 'watchdog.json', state)
            timer.join(1)
            self.assertTrue(state['fired'])
            self.assertEqual(execute.call_args.args[0], ['docker', 'kill', 'owned-worker', 'owned-relay'])
            self.assertLessEqual(execute.call_args.kwargs['timeout'], 2)


if __name__ == '__main__':
    unittest.main()
