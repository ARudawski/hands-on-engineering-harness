"""Bounded stdio app-server connection. No generic approval auto-responder."""

import json
from pathlib import Path
import queue
import subprocess
import threading
import time


def public_event(value):
    if isinstance(value, list):
        return [clean for v in value if (clean := public_event(v)) is not None]
    if isinstance(value, dict):
        if 'reasoning' in str(value.get('type', '')).lower() or 'reasoning' in str(value.get('method', '')).lower():
            return None
        return {k: clean for k, v in value.items() if k != 'encrypted_content' and (clean := public_event(v)) is not None}
    return value


class Connection:
    def __init__(self, worker, model, effort, evidence, legacy=False):
        self.events, self.pending, self.sequence, self.output_bytes = [], queue.Queue(maxsize=4096), 0, 0
        self.worker = worker
        self.evidence = Path(evidence)
        self.errors = self.evidence.with_suffix('.stderr.log').open('x', encoding='utf-8')
        config = {'model': model, 'model_reasoning_effort': effort, 'model_provider': 'evaluation',
                  'model_providers.evaluation.name': 'Trial model relay',
                  'model_providers.evaluation.base_url': 'http://model-relay:8080/v1',
                  'model_providers.evaluation.env_key': 'EVALUATION_MODEL_TOKEN',
                  'model_providers.evaluation.wire_api': 'responses',
                  'model_providers.evaluation.requires_openai_auth': False,
                  'model_providers.evaluation.supports_websockets': False,
                  'approval_policy': 'on-request', 'sandbox_mode': 'workspace-write',
                  'web_search': 'disabled', 'features.apps': False}
        if legacy:
            config['features.use_legacy_landlock'] = True
        args = ['docker', 'exec', '--workdir', '/work/codex', '-i', worker, 'codex', 'app-server', '--stdio']
        for name, value in config.items():
            args += ['-c', name + '=' + json.dumps(value)]
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
                                        text=True, encoding='utf-8', bufsize=1)
        threading.Thread(target=self.read, daemon=True).start()
        try:
            self.call('initialize', {'clientInfo': {'name': 'harness_evaluation', 'title': 'Harness feasibility', 'version': '1'},
                                     'capabilities': {'experimentalApi': True}}, 30)
            self.send({'method': 'initialized'})
        except BaseException:
            self.close()
            raise

    def read(self):
        try:
            for line in self.process.stdout:
                self.output_bytes += len(line.encode('utf-8'))
                if len(line) > 1024 * 1024 or self.output_bytes > 16 * 1024 * 1024:
                    self.pending.put({'protocol_error': 'native output budget exceeded'})
                    return
                try:
                    self.pending.put(json.loads(line))
                except ValueError:
                    self.pending.put({'protocol_error': 'non-JSON app-server output'})
        finally:
            self.pending.put({'protocol_error': 'app-server ended'})

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def receive(self, timeout):
        try:
            value = self.pending.get(timeout=max(0.01, timeout))
        except queue.Empty:
            raise TimeoutError('Native request/event deadline exhausted') from None
        if 'protocol_error' in value:
            raise RuntimeError(value['protocol_error'])
        safe = public_event(value)
        if safe is not None:
            self.events.append(safe)
            with self.evidence.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(safe) + '\n')
        return value

    def call(self, method, params, timeout=30):
        self.sequence += 1
        identity = self.sequence
        self.send({'id': identity, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError('Native request deadline exhausted')
            value = self.receive(deadline - time.monotonic())
            if value.get('id') == identity and 'method' not in value:
                if 'error' in value:
                    raise RuntimeError('Native RPC rejected: ' + json.dumps(value['error']))
                return value['result']
            if 'method' in value and 'id' in value:
                raise RuntimeError('Unmatched native request blocks operation')

    def close(self):
        deadline = time.monotonic() + 10
        def budget(maximum):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Absolute native cleanup deadline exhausted')
            return min(maximum, remaining)
        try:
            try:
                self.process.stdin.close()
                try:
                    self.process.wait(timeout=budget(3))
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=budget(1))
                check = subprocess.run(['docker', 'exec', self.worker, 'python', '-c',
                    "import pathlib,os,json; print(json.dumps([p.name for p in pathlib.Path('/proc').iterdir() if p.name.isdigit() and int(p.name) not in (1,os.getpid()) and (p/'cmdline').read_bytes()]))"],
                    capture_output=True, text=True, timeout=budget(2))
                clean = check.returncode == 0 and not json.loads(check.stdout)
            except (OSError, ValueError, subprocess.SubprocessError, TimeoutError):
                clean = False
            if not clean:
                subprocess.run(['docker', 'stop', '--time', '0', self.worker], capture_output=True, timeout=budget(2), check=True)
                raise RuntimeError('Native cleanup left remote processes; owned worker stopped')
        finally:
            self.errors.close()


def sandbox_gate(worker, model, effort, evidence, inputs, legacy=False):
    connection = Connection(worker, model, effort, evidence, legacy)
    try:
        probe = {**inputs, 'forbidden_writes': ['/work/claude/native-forbidden'], 'child': True}
        result = connection.call('command/exec', {'command': ['python', '/opt/evaluation/worker.py', 'preflight', json.dumps(probe)],
            'cwd': '/work/codex', 'timeoutMs': 60000, 'outputBytesCap': 32768,
            'sandboxPolicy': {'type': 'workspaceWrite', 'writableRoots': ['/work/codex'], 'networkAccess': False}}, 70)
        passed = result['exitCode'] == 0 and all(json.loads(result['stdout']).values())
        return {'result': result, 'passed': passed, 'legacy_landlock': legacy}
    finally:
        connection.close()
