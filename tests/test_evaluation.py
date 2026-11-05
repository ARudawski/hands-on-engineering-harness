"""Credential/model-free evaluation guards, included in ordinary package discovery."""

import copy
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import sys
import io
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


class EvaluationGuards(unittest.TestCase):
    def setUp(self):
        self.request = {'model': 'fixed', 'reasoning': {'effort': 'xhigh'}, 'store': False,
                        'stream': True, 'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'public probe'}]}]}

    def test_request_cannot_expand_authority(self):
        invalid = [{'previous_response_id': 'foreign'}, {'conversation': 'foreign'}, {'prompt': {'id': 'foreign'}},
                   {'tools': [{'type': 'web_search'}]}, {'tools': [{'type': 'namespace', 'tools': [{'type': 'mcp'}]}]},
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
        with patch.object(native.subprocess, 'run', side_effect=[subprocess.TimeoutExpired('readback', 2),
                          subprocess.CompletedProcess([], 0)]) as execute, self.assertRaisesRegex(RuntimeError, 'worker stopped'):
            connection.close()
        self.assertEqual(execute.call_args_list[1].args[0], ['docker', 'stop', '--time', '0', 'exact-owned-worker'])
        self.assertLessEqual(sum(call.kwargs['timeout'] for call in execute.call_args_list), 4)


if __name__ == '__main__':
    unittest.main()
