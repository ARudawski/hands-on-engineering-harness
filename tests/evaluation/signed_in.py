"""Trusted, model-free request boundary for the future signed-in evaluator.

Only the invoking controller uses this module/database. Never mount it into an
evaluated worker. S1 deliberately has no native launcher or feasibility verdict.
"""

from contextlib import closing, contextmanager
import json
import os
import re
from pathlib import Path
import sqlite3
import sys
import time
from uuid import UUID, uuid4


ROOT = Path(__file__).resolve().parents[2]
REVISION = '99c823abd4f0fc9cc58eda47ca775de64415fd35'
REASONS = {'completed', 'controller_disconnected', 'deployment_unavailable', 'deadline_exhausted', 'clock_changed',
           'interrupted', 'cleanup_failed', 'missing_evidence', 'protected_disclosure',
           'evidence_limit', 'reviewer_route_unverified', 'workspace_requirements_unavailable'}
KINDS = {'preparation', 'launch', 'resume', 'question', 'permission',
         'workflow_pause', 'review', 'cleanup', 'error'}
EVENT_STATES = {'started', 'completed', 'blocked', 'failed', 'interrupted'}


def identity(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Invalid identity')
    return value


def validate(origin, request, case, seconds):
    identity(origin)
    identity(request)
    if case != 'native-foundation' or type(seconds) is not int or not 10 < seconds <= 7200:
        raise ValueError('Invalid evaluation request')


def candidate_selection(revision=None, ref=None):
    if revision is None and ref is None:
        return {}
    if (not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision)
            or ref is not None and (not isinstance(ref, str) or not 0 < len(ref) <= 256
                                    or any(ord(c) < 32 for c in ref))):
        raise ValueError('Invalid candidate selection')
    return {'candidate_revision': revision, 'candidate_ref': ref}


def safe_event(event, allowed_threads):
    """Project onto fixed enums and verified IDs; retain no arbitrary text."""
    if (not isinstance(event, dict) or not isinstance(event.get('kind'), str)
            or not isinstance(event.get('status'), str)
            or event['kind'] not in KINDS or event['status'] not in EVENT_STATES):
        return None
    safe = {'kind': event['kind'], 'status': event['status']}
    if 'thread_id' in event:
        if not isinstance(event['thread_id'], str) or event['thread_id'] not in allowed_threads:
            return None
        safe['thread_id'] = identity(event['thread_id'])
    if 'code' in event:
        if not isinstance(event['code'], str) or event['code'] not in REASONS:
            return None
        safe['code'] = event['code']
    return safe


class RequestStore:
    """Serialized controller state; origin comes from the trusted caller channel.

    SQLite uniqueness/transactions prevent duplicate deliveries and concurrent
    launch claims. Its directory is controller-owned, outside all trial roots.
    allowed_threads is supplied only by the controller after lineage validation.
    """

    def __init__(self, directory, clock=None):
        self.path = Path(directory) / 'requests.sqlite3'
        self.clock = clock or (lambda: (time.time(), time.monotonic()))

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=1)) as connection, connection:
            connection.execute('CREATE TABLE IF NOT EXISTS requests '
                               '(request_id TEXT PRIMARY KEY, origin TEXT NOT NULL, state TEXT NOT NULL)')
            connection.execute('BEGIN IMMEDIATE')
            yield connection

    @staticmethod
    def stop_state(state, reason):
        state['admission_open'] = False
        if reason == 'completed' and state['first_failure'] is None:
            state['status'] = 'completed'
            return
        if state['first_failure'] is None:
            state['first_failure'] = reason
        state['status'] = ('invalid' if reason == 'protected_disclosure' or state['status'] == 'invalid' else
                           'incomplete' if state['launch_claimed'] else 'rejected_before_launch')

    def tick(self, state):
        if not state['admission_open']:
            return  # Retrieval cannot age a finalized trial into a new outcome.
        wall, monotonic = self.clock()
        if wall < state['last_wall'] or monotonic < state['last_monotonic']:
            self.stop_state(state, 'clock_changed')
        elif min(state['deadline'] - wall, state['monotonic_deadline'] - monotonic) <= 10:
            self.stop_state(state, 'deadline_exhausted')
        state['last_wall'], state['last_monotonic'] = wall, monotonic

    @staticmethod
    def view(state):
        # No internal JSON/event/error supplied by a worker reaches this view.
        keys = ('request_id', 'origin', 'attempt_id', 'trial_id', 'case', 'revision',
                'seconds', 'deadline', 'status', 'admission_open', 'first_failure',
                'cleanup', 'cleanup_failure', 'events')
        return {**{key: state[key] for key in keys},
                **{key: state[key] for key in ('candidate_revision', 'candidate_ref') if key in state}, 'model': None,
                'reviewer_findings': [], 'checks': {f'H12-AC-{n:02}': 'skipped' for n in range(1, 8)},
                'evidence': '.tmp/evaluation-signed-in/requests.sqlite3#' + state['request_id']}

    @contextmanager
    def request(self, origin, request):
        identity(origin)
        identity(request)
        with self.transaction() as connection:
            row = connection.execute('SELECT origin, state FROM requests WHERE request_id=?', (request,)).fetchone()
            if row is None:
                raise KeyError('Unknown request')
            if row[0] != origin:
                raise PermissionError('Request belongs to another origin')
            state = json.loads(row[1])
            self.tick(state)
            yield state
            connection.execute('UPDATE requests SET state=? WHERE request_id=?', (json.dumps(state), request))

    def submit(self, origin, request, case, seconds, *, candidate_revision=None, candidate_ref=None):
        validate(origin, request, case, seconds)
        candidate = candidate_selection(candidate_revision, candidate_ref)
        with self.transaction() as connection:
            row = connection.execute('SELECT origin, state FROM requests WHERE request_id=?', (request,)).fetchone()
            if row:
                if row[0] != origin:
                    raise PermissionError('Request belongs to another origin')
                state = json.loads(row[1])
                if 'delivery_input' in state:
                    raise ValueError('Request inputs changed')
                if ((state['case'], state['seconds']) != (case, seconds)
                        or {k: state[k] for k in ('candidate_revision', 'candidate_ref') if k in state} != candidate):
                    raise ValueError('Request inputs changed')
                self.tick(state)
                connection.execute('UPDATE requests SET state=? WHERE request_id=?', (json.dumps(state), request))
            else:
                wall, monotonic = self.clock()
                state = {'origin': origin, 'request_id': request, 'attempt_id': str(uuid4()),
                         'trial_id': str(uuid4()), 'case': case,
                         'revision': candidate.get('candidate_revision', REVISION), **candidate,
                         'seconds': seconds, 'deadline': wall + seconds,
                         'monotonic_deadline': monotonic + seconds, 'last_wall': wall,
                         'last_monotonic': monotonic, 'status': 'accepted',
                         'admission_open': True, 'launch_claimed': False, 'first_failure': None,
                         'cleanup': 'not_started', 'cleanup_failure': None, 'events': []}
                connection.execute('INSERT INTO requests VALUES (?, ?, ?)', (request, origin, json.dumps(state)))
            return self.view(state)

    def get(self, origin, request):
        with self.request(origin, request) as state:
            return self.view(state)

    def claim_launch(self, origin, request):
        """One-time admission claim only; no process or model is launched here."""
        with self.request(origin, request) as state:
            if not state['admission_open'] or state['launch_claimed']:
                return False
            state['launch_claimed'] = True
            state['status'] = 'launch_pending'
            return True

    def stop(self, origin, request, reason):
        if reason not in REASONS:
            raise ValueError('Unsupported failure')
        with self.request(origin, request) as state:
            self.stop_state(state, reason)
            return self.view(state)

    def cleanup(self, origin, request, succeeded):
        if type(succeeded) is not bool:
            raise ValueError('Invalid cleanup outcome')
        with self.request(origin, request) as state:
            if state['admission_open']:
                raise ValueError('Close admission before cleanup')
            if state['cleanup'] != 'not_started':
                return self.view(state)
            state['cleanup'] = 'completed' if succeeded else 'failed'
            if not succeeded:
                state['cleanup_failure'] = 'cleanup_failed'
            return self.view(state)

    def record(self, origin, request, event, *, allowed_threads=()):
        safe = safe_event(event, allowed_threads)
        with self.request(origin, request) as state:
            if safe is None:
                return False
            if len(state['events']) >= 128:
                self.stop_state(state, 'evidence_limit')
                return False
            state['events'].append(safe)
            return True


def main():
    """One trusted stdin request; return JSON only, never raw input/exception text."""
    channel = None
    try:
        if len(sys.argv) != 1:
            raise ValueError('No arguments supported')
        raw = ''
        while True:
            line = sys.stdin.readline(4097-len(raw))
            raw += line
            if len(raw) > 4096 or not line:
                raise ValueError('Invalid or oversized request')
            try:
                payload = json.loads(raw)
                break
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict) and ('candidate_ref' in payload or 'candidate_revision' in payload):
            sys.path.insert(0, str(ROOT/'tests'))
            from evaluation.signed_in_delivery import JsonChannel, deliver
            channel = JsonChannel(sys.stdin, sys.stdout)
            result = deliver(payload, channel, root=ROOT, origin=os.environ.get('CODEX_THREAD_ID'))
            channel.emit({'kind': 'result', 'body': result})
            return
        # Legacy callers supply one JSON object through EOF, including pretty
        # JSON. Preserve rejection of trailing non-whitespace or excess bytes.
        raw += sys.stdin.read(4097-len(raw))
        if len(raw) > 4096:
            raise ValueError('Request too large')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.keys() != {'request_id', 'case', 'seconds'}:
            raise ValueError('Invalid request fields')
        origin = os.environ.get('CODEX_THREAD_ID')
        validate(origin, payload['request_id'], payload['case'], payload['seconds'])
        store = RequestStore(ROOT / '.tmp/evaluation-signed-in')
        store.submit(origin, payload['request_id'], payload['case'], payload['seconds'])
        result = store.stop(origin, payload['request_id'], 'deployment_unavailable')
        print(json.dumps(result))
        return 0
    except Exception:
        # Exceptions may carry native credentials or arbitrary input later on.
        if channel is None:
            print(json.dumps({'error': 'request_rejected'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
