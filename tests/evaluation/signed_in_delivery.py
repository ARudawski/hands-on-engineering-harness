"""Trusted connected controller for one candidate trial; never imported by a worker."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from uuid import uuid4

from evaluation.signed_in import RequestStore, identity, validate
from evaluation.signed_in_candidate import resolve_candidate


CODEX_SHA256 = '4b3286e35d7fe866c6b0eb3f07d7a4cdb5e96489576170dfd6b3a15aa1c67382'
SOURCE_REF = 'c40729ea5cf8e947481b130c59807273eda2f8e9'
DISABLED = ('apps', 'plugins', 'memories', 'goals', 'view_image', 'image_generation',
            'browser_use', 'computer_use', 'in_app_browser', 'shell_snapshot')
CONFIG_CHECKS = {'provider_matches', 'approval_policy_matches', 'human_approval_reviewer',
                 'profile_matches', 'only_consumer_guidance', 'workspace_matches', 'environment_matches'}


def text(value, limit=65536):
    if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > limit:
        raise ValueError('controller_reply_rejected')
    return value


class JsonChannel:
    """JSON lines on the original invoking connection; EOF never means approval."""
    def __init__(self, reader, writer):
        self.writer, self.incoming = writer, queue.Queue(maxsize=32)
        self.closed = threading.Event()
        self.output_failed = threading.Event()
        self.outgoing = queue.Queue(maxsize=1)
        try:
            descriptor = writer.fileno()
        except (OSError, ValueError, AttributeError):
            descriptor = None
        def write():
            while True:
                encoded, complete, failed = self.outgoing.get()
                try:
                    if descriptor is None:
                        writer.write(encoded.decode('ascii')); writer.flush()
                    else:
                        # No TextIO lock is held if a dead invoking pipe blocks.
                        while encoded:
                            written = os.write(descriptor, encoded)
                            if written <= 0: raise OSError()
                            encoded = encoded[written:]
                except (OSError, ValueError):
                    failed.set(); self.output_failed.set(); self.closed.set()
                finally:
                    complete.set()
        threading.Thread(target=write, daemon=True).start()
        def read():
            try:
                while True:
                    line = reader.readline(131073)
                    if not line or len(line) > 131072:
                        break
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        break
                    self.incoming.put_nowait(value)
            except (ValueError, OSError, queue.Full):
                pass
            finally:
                self.closed.set()
        threading.Thread(target=read, daemon=True).start()

    def emit(self, value, *, timeout=1):
        encoded = (json.dumps(value, ensure_ascii=True)+'\n').encode('ascii')
        if len(encoded) > 131072:
            raise ValueError('controller_output_limit')
        complete, failed = threading.Event(), threading.Event()
        try:
            if self.output_failed.is_set(): raise ConnectionError()
            self.outgoing.put_nowait((encoded, complete, failed))
        except queue.Full:
            self.output_failed.set(); self.closed.set()
            raise ConnectionError('controller_disconnected') from None
        if not complete.wait(max(0, min(1, timeout))) or failed.is_set():
            self.output_failed.set(); self.closed.set()
            raise ConnectionError('controller_disconnected') from None

    def poll(self, seconds=.1):
        try:
            return self.incoming.get(timeout=seconds)
        except queue.Empty:
            if self.closed.is_set():
                raise ConnectionError('controller_disconnected')
            return None


class Delivery:
    """Trusted per-request channel/identity, not a caller-supplied admission flag."""
    def __init__(self, store, origin, request, channel):
        self.store, self.origin, self.request, self.channel = store, origin, request, channel
        self.wait_seconds = 0.0
        self.checkpoints = []

    def matches(self, payload):
        with self.store.request(self.origin, self.request) as state:
            return (state.get('delivery_payload') == payload and state['admission_open']
                    and state.get('delivery_claimed') is True)

    def check_connected(self):
        value = self.channel.poll(0)
        if value is not None:
            if value == {'origin': self.origin, 'request_id': self.request, 'action': 'cancel'}:
                raise InterruptedError('operator_cancelled')
            raise ValueError('controller_reply_rejected')

    def checkpoint(self, kind, body, *, owner=None, thread=None, turn=None):
        token = {'origin': self.origin, 'request_id': self.request, 'checkpoint': str(uuid4()),
                 'kind': kind, 'thread_id': thread, 'turn_id': turn}
        self.channel.emit({**token, 'body': body}, timeout=min(1, owner.remaining()) if owner else 1)
        started = time.monotonic()
        try:
            while True:
                if owner:
                    owner.remaining()
                elif time.monotonic()-started > 60:
                    raise TimeoutError('controller_reply_timeout')
                reply = self.channel.poll()
                if reply is None:
                    continue
                if reply == {'origin': self.origin, 'request_id': self.request, 'action': 'cancel'}:
                    raise InterruptedError('operator_cancelled')
                if (set(reply) != set(token) | {'response'}
                        or any(reply.get(k) != v for k, v in token.items())):
                    raise ValueError('controller_reply_rejected')
                # No token can be reused, including a rejected response.
                self.checkpoints.append(token['checkpoint'])
                return reply['response']
        finally:
            if owner:
                self.wait_seconds += time.monotonic()-started

    def admit(self, result, codex, options, consumer, home):
        """Bind reviewed source mechanisms to this actual root before case release."""
        from evaluation.signed_in_worker import CHECKS
        from native_support import digest
        from evaluation.signed_in_candidate import verify_candidate
        consumer, home = Path(consumer), Path(home)
        if digest(Path(codex)) != CODEX_SHA256:
            raise RuntimeError('candidate_executable_unassessed')
        if (home/'config.toml').exists() or (consumer/'.codex/config.toml').exists():
            raise RuntimeError('candidate_configuration_unsupported')
        required = {'windows.sandbox': 'mxc', 'default_permissions': 'har12-native',
                    'permissions.har12-native.network.enabled': False, 'model_provider': 'openai',
                    'cli_auth_credentials_store': 'file', 'shell_environment_policy.inherit': 'none',
                    'allow_login_shell': False, 'web_search': 'disabled',
                    'features.skip_host_skill_discovery': True,
                    'features.multi_agent_v2.non_code_mode_only': False,
                    'features.multi_agent_v2.tool_namespace': 'collaboration'}
        required.update({'features.'+name: False for name in DISABLED})
        if any(type(options.get(k)) is not type(v) or options.get(k) != v for k, v in required.items()):
            raise RuntimeError('candidate_authority_changed')
        policy = options.get('permissions.har12-native.filesystem', {})
        if (policy.get(':root') != 'deny' or policy.get(str(home)) != 'deny'
                or policy.get(':workspace_roots') != {'.': 'read', '.tmp': 'write'}):
            raise RuntimeError('candidate_authority_changed')
        if (result.get('command_gate', {}).keys() != CHECKS
                or not all(v is True for v in result['command_gate'].values())
                or any(result.get('effective_configuration', {}).get(k) is not True for k in CONFIG_CHECKS)
                or result.get('isolation_mcp_empty') is not True or result.get('auth_mode') != 'chatgpt'):
            raise RuntimeError('candidate_boundary_unverified')
        # Re-derive the install from the frozen export; no caller-installed catalogue is trusted.
        verify_candidate(consumer, result['installation'], {'model': 'gpt-6-luna', 'effort': 'low'})
        with self.store.request(self.origin, self.request) as state:
            if (not state['admission_open'] or state.get('native_root') != result.get('root_thread_id')
                    or state.get('native_purpose') != 'candidate-observe'
                    or state.get('delivery_payload', {}).get('candidate_revision') != result.get('revision')):
                raise RuntimeError('candidate_boundary_unverified')
            proof = {'root': state['native_root'], 'revision': state['revision'],
                     'executable_sha256': CODEX_SHA256, 'source_ref': SOURCE_REF,
                     'policy_sha256': result['policy_sha256'],
                     'installation_sha256': hashlib.sha256(json.dumps(result['installation']['files'], sort_keys=True).encode()).hexdigest()}
            state['candidate_admission'] = proof
        result['candidate_admission'] = proof
        result['boundary_passed'] = True

    def native_decision(self, observer, value):
        params, method = value['params'], value['method']
        supported = ('item/tool/requestUserInput', 'item/commandExecution/requestApproval',
                     'item/fileChange/requestApproval', 'item/permissions/requestApproval')
        if method not in supported:
            raise RuntimeError('candidate_decision_unsupported')
        response = self.checkpoint('native_decision', {'method': method, 'params': params,
            'permission_expansion_allowed': False}, owner=observer.owner,
            thread=params['threadId'], turn=params['turnId'])
        if not isinstance(response, dict):
            raise ValueError('controller_reply_rejected')
        if method == 'item/tool/requestUserInput':
            if response.keys() != {'answers'} or not isinstance(response['answers'], dict):
                raise ValueError('controller_reply_rejected')
            questions = params.get('questions', [])
            if (not questions or any(q.get('isSecret') is True for q in questions)
                    or response['answers'].keys() != {q['id'] for q in questions}):
                raise ValueError('controller_reply_rejected')
            for answer in response['answers'].values():
                if (not isinstance(answer, dict) or answer.keys() != {'answers'}
                        or not isinstance(answer['answers'], list) or not 1 <= len(answer['answers']) <= 16):
                    raise ValueError('controller_reply_rejected')
                for label in answer['answers']:
                    text(label, 4096)
        elif method == 'item/permissions/requestApproval':
            if response != {'permissions': {}, 'scope': 'turn'}:
                raise ValueError('permission_expansion_outside_trial')
        elif response not in ({'decision': 'decline'}, {'decision': 'cancel'}):
            # Accept can relax the OS boundary; only the fixed task grant is authorized.
            raise ValueError('permission_expansion_outside_trial')
        self.store.get(self.origin, self.request)  # Tick immediately before the one wire response.
        self.check_connected()
        observer.connection.respond(value, response)

    def completed_turn(self, observer, turn):
        report = observer.snapshot('awaiting_operator')
        response = self.checkpoint('candidate_output', report, owner=observer.owner,
                                   thread=observer.root, turn=turn)
        if response == {'action': 'finish'}:
            return None
        if response == {'action': 'cancel'}:
            raise InterruptedError('operator_cancelled')
        if not isinstance(response, dict) or response.keys() != {'action', 'text'} or response['action'] != 'continue':
            raise ValueError('controller_reply_rejected')
        followup = text(response['text'])
        with self.store.request(self.origin, self.request) as state:
            if not state['admission_open'] or state.get('candidate_turn_intent'):
                raise ValueError('controller_reply_rejected')
            state['candidate_turn_intent'] = {'root': observer.root, 'checkpoint_turn': turn}
        return followup


def run_command(command, *, cwd, env, timeout=15):
    result = subprocess.run(command, cwd=cwd, env=env, timeout=timeout, capture_output=True,
                            text=True, encoding='utf-8')
    if result.returncode or len(result.stdout) > 65536:
        raise ValueError('candidate_resolution_failed')
    return result.stdout


def deliver(payload, channel, *, root, origin, native_runner=None, resolver=resolve_candidate, clock=None):
    """Reserve once, resolve outside the shared lock, then retain the first report."""
    allowed = {'request_id', 'case', 'seconds', 'profile_id', 'candidate_ref', 'candidate_revision'}
    if (not isinstance(payload, dict) or set(payload)-allowed
            or not {'request_id', 'case', 'seconds', 'profile_id'} <= payload.keys()
            or ('candidate_ref' in payload) == ('candidate_revision' in payload)):
        raise ValueError('Invalid candidate request')
    validate(origin, payload['request_id'], payload['case'], payload['seconds'])
    identity(payload['profile_id'])
    if payload['seconds'] > 900:
        raise ValueError('Unsupported candidate budget')
    selector = payload.get('candidate_ref', payload.get('candidate_revision'))
    text(selector, 256)
    if 'candidate_revision' in payload:
        from evaluation.signed_in import candidate_selection
        candidate_selection(payload['candidate_revision'])
    store = RequestStore(Path(root)/'.tmp/evaluation-signed-in', clock=clock)
    # Reserve the selector/owner only. Never run a subprocess under this shared lock.
    with store.transaction() as db:
        row = db.execute('SELECT origin,state FROM requests WHERE request_id=?', (payload['request_id'],)).fetchone()
        if row:
            state = json.loads(row[1])
            if row[0] != origin:
                raise PermissionError('Request belongs to another origin')
            if state.get('delivery_input') != payload:
                raise ValueError('Request inputs changed')
            if 'delivery_receipt' in state:
                return state['delivery_receipt']
            store.tick(state)
            db.execute('UPDATE requests SET state=? WHERE request_id=?', (json.dumps(state),payload['request_id']))
            return {**store.view(state), 'root_thread_id': state.get('native_root'),
                    'delivery_status': 'incomplete_result_unavailable' if state['first_failure'] else 'already_issued'}
        wall, mono = store.clock()
        state = {'origin': origin, 'request_id': payload['request_id'], 'attempt_id': str(uuid4()),
                 'trial_id': str(uuid4()), 'case': payload['case'], 'revision': None,
                 'seconds': payload['seconds'], 'deadline': wall+payload['seconds'],
                 'monotonic_deadline': mono+payload['seconds'], 'last_wall': wall, 'last_monotonic': mono,
                 'status': 'resolving', 'admission_open': True, 'launch_claimed': False,
                 'first_failure': None, 'cleanup': 'not_started', 'cleanup_failure': None, 'events': [],
                 'delivery_input': dict(payload), 'delivery_claimed': True}
        db.execute('INSERT INTO requests VALUES(?,?,?)', (payload['request_id'], origin, json.dumps(state)))
    session = Delivery(store, origin, payload['request_id'], channel)
    if native_runner is None:
        from evaluation.signed_in_native import run_native
        native_runner = run_native
    result, verdict = {}, {'verdict': 'unassessed', 'reason': 'No attributable completed assessment.'}
    failure = None
    native_called = False
    try:
        session.check_connected()
        def resolve_run(command, *, cwd, env):
            left = min(wall+payload['seconds']-store.clock()[0], mono+payload['seconds']-store.clock()[1])-10
            if left <= 0:
                raise TimeoutError('deadline_exhausted')
            return run_command(command, cwd=cwd, env=env, timeout=min(15,left))
        revision = resolver(resolve_run, Path(root), selector, {**os.environ, 'GIT_NO_LAZY_FETCH':'1'})
        from evaluation.signed_in import candidate_selection
        selected = candidate_selection(revision, selector if 'candidate_ref' in payload else None)
        native_payload = {'request_id': payload['request_id'], 'case': payload['case'], 'seconds': payload['seconds'],
                          'profile_id': payload['profile_id'], 'candidate_revision': revision,
                          'model': 'gpt-6-luna', 'effort': 'low'}
        if 'candidate_ref' in payload:
            native_payload['candidate_ref'] = selector
        with store.request(origin, payload['request_id']) as current:
            if not current['admission_open']:
                raise TimeoutError('deadline_exhausted')
            current.update(revision=revision, **selected, delivery_payload=native_payload, status='accepted')
        if not store.get(origin, payload['request_id'])['admission_open']:
            raise TimeoutError('deadline_exhausted')
        session.check_connected()
        native_called = True
        result = native_runner(native_payload, mode='diagnose', candidate_run=True, delivery=session)
    except Exception as error:
        # Native run owns cleanup in finally. A pre-owner exception has no candidate to stop.
        failure = {'Unsupported deployment or bound': 'deployment_unavailable',
                   'candidate_resolution_failed': 'candidate_resolution_failed',
                   'profile_rejected': 'profile_unavailable',
                   'candidate_admission_unverified': 'candidate_admission_unverified',
                   'profile_binding_changed': 'profile_binding_changed'}.get(str(error), 'candidate_launch_incomplete')
        if isinstance(error, ConnectionError): failure = 'controller_disconnected'
        if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)): failure = 'deadline_exhausted'
        if isinstance(error, InterruptedError): failure = 'interrupted'
        if not native_called:
            result = {'cleanup_verified': True, 'status': 'rejected_before_launch', 'error_code': failure}
        store.stop(origin, payload['request_id'], 'missing_evidence')
    observation = result.get('candidate_observation', {})
    messages = observation.get('agent_messages', [])
    deliverable = [m for m in messages if m.get('thread_id') == result.get('root_thread_id')]
    try:
        if (result.get('cleanup_verified') is True and observation.get('execution_end') == 'completed'
                and not result.get('source_drift') and not result.get('candidate_input_drift') and not result.get('error_code')
                and observation.get('safety') != 'invalid' and deliverable):
            response = session.checkpoint('assessment', {'case_revision': 'native-foundation-v2',
                'deliverable': deliverable, 'rubric': 'Pass: identifies the incorrect sum with code or a correct example. '
                'Fail: completed assessment misses the defect or omits support. Otherwise unassessed.'})
            if (not isinstance(response, dict) or response.keys() != {'verdict', 'reason'}
                    or response['verdict'] not in ('pass', 'fail', 'unassessed')):
                raise ValueError('controller_reply_rejected')
            verdict = {'verdict': response['verdict'], 'reason': text(response['reason'], 4096)}
    except (ValueError, ConnectionError, TimeoutError, InterruptedError):
        verdict = {'verdict': 'unassessed', 'reason': 'Trusted assessment unavailable on the original connection.'}
        failure = 'assessment_unavailable'
    with store.request(origin, payload['request_id']) as state:
        report = {'origin': origin, 'request_id': payload['request_id'], 'attempt_id': state['attempt_id'],
                  'candidate_revision': state['revision'], 'case': state['case'], 'case_revision': 'native-foundation-v2',
                  'budget_seconds': state['seconds'], 'root_thread_id': result.get('root_thread_id'),
                  'execution_end': observation.get('execution_end', result.get('error_code', failure or 'prelaunch_rejected')),
                  'elapsed_seconds': result.get('elapsed_seconds', round(max(0, state['seconds']-(state['deadline']-store.clock()[0])),3)),
                  'identifiable_wait_seconds': round(session.wait_seconds, 3),
                  'wait_coverage': 'connected controller checkpoints; other waits unknown',
                  'requested_root_default': {'model': 'gpt-6-luna', 'effort': 'low'},
                  'participants': observation.get('participants', []), 'subagent_coverage': observation.get('subagent_coverage', 'unknown'),
                  'evidence': str(store.path.parent/state['attempt_id']/'receipt.json'),
                  'deliverable': deliverable, 'assessment': verdict,
                  'cleanup_verified': result.get('cleanup_verified', False),
                  'limitations': observation.get('infrastructure_limitations', [])+[failure] if failure else observation.get('infrastructure_limitations', []),
                  'admission': result.get('candidate_admission'), 'native_status': result.get('status', 'incomplete'),
                  'acceptance': 'pending_live_reconciliation'}
        if result.get('error_code'):
            report['limitations'].append(result['error_code'])
        if result.get('cleanup_verified') is not True:
            report['limitations'].append('cleanup_unverified')
        state['delivery_receipt'] = report
    return report
