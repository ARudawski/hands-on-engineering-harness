"""Trusted fixed HAR-12 checkpoints and opt-in native wire probe.

No public CLI invokes this adapter. Prepared intents and scripted stdio checks
do not establish native delivery, full isolation or evaluated-case acceptance.
"""

from copy import deepcopy
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re

from evaluation.probes import resolve_request
from evaluation.signed_in import identity
from evaluation.signed_in_native import command_matches
from evaluation.signed_in_profiles import checkpoint_binding


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def marker_command(python_executable):
    """Only a trusted absolute Python path and the fixed public marker."""
    if (not isinstance(python_executable, str) or not 0 < len(python_executable) <= 512
            or not (os.path.isabs(python_executable) or ntpath.isabs(python_executable))
            or any(c in python_executable for c in "'\"`$\r\n")):
        raise ValueError('interaction_rejected')
    return "& '" + python_executable + "' -I -B -c \"print('HAR5_APPROVED')\""


def manifest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('interaction_rejected')
    return value


def opaque(value):
    if not isinstance(value, str) or not 0 < len(value) <= 128:
        raise ValueError('interaction_rejected')
    return digest(value)


def request_key(value):
    if not (type(value) is int and 0 <= value <= 2**53 or isinstance(value, str) and 0 < len(value) <= 128):
        raise ValueError('interaction_rejected')
    return digest(value)


class Interactions:
    """One small persisted checkpoint within an already-issued RequestStore.

    The manifest is a trusted caller's hash of real source/install/fixture,
    runtime/model/policy/workspace and lineage evidence. Matching hashes are
    integrity guards only, never proof of those runtime facts or isolation.
    """

    def __init__(self, store, origin, request_id):
        self.store, self.origin, self.request_id = store, origin, request_id

    def _change(self, action):
        failed, result = False, None
        with self.store.request(self.origin, self.request_id) as state:
            # Commit tick's closure even when the attempted transition fails.
            if not state['admission_open'] or not state['launch_claimed']:
                failed = True
            else:
                checkpoint = deepcopy(state.get('native_interaction', {}))
                try:
                    result = action(checkpoint)
                    checkpoint_binding(state, checkpoint)
                except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                    failed = True
                else:
                    state['native_interaction'] = checkpoint
        if failed:
            raise ValueError('interaction_rejected')
        return result

    def bind(self, root_uuid, manifest_sha256, *, cwd, python_executable, environment_id=None):
        def change(cp):
            if not isinstance(cwd, str) or not 0 < len(cwd) <= 512 or not (os.path.isabs(cwd) or ntpath.isabs(cwd)):
                raise ValueError()
            binding = {'root': identity(root_uuid), 'manifest': manifest(manifest_sha256),
                       'cwd': digest(cwd), 'command': digest(marker_command(python_executable)),
                       'environment': opaque(environment_id) if environment_id is not None else None}
            if cp:
                if cp['binding'] != binding:
                    raise ValueError()
            else:
                cp.update(binding=binding, phase='ready', turns=[], callback_ids=[])
            return cp['phase']
        return self._change(change)

    def begin(self, kind, turn_uuid):
        def change(cp):
            expected = {'question': 'ready', 'permission': 'resumed', 'workflow': 'permission_done'}
            turn = identity(turn_uuid)
            if kind not in expected or cp['phase'] not in (expected[kind], kind+'_starting') or turn in cp['turns']:
                raise ValueError()
            cp.update(phase=kind + '_active', turn=turn, callback=None, item=None,
                      resolved=False, execution=False)
            cp['turns'].append(turn)
            return cp['phase']
        return self._change(change)

    def prepare_turn(self, kind):
        def change(cp):
            expected = {'question': 'ready', 'permission': 'resumed', 'workflow': 'permission_done'}
            if kind not in expected or cp['phase'] != expected[kind]:
                raise ValueError()
            cp['phase'] = kind+'_starting'
        return self._change(change)

    def reply(self, value, *, cwd=None, python_executable=None):
        def change(cp):
            params = value['params']
            if (not isinstance(params, dict) or 'result' in value or 'error' in value
                    or params.get('threadId') != cp['binding']['root'] or params.get('turnId') != cp['turn']):
                raise ValueError()
            callback = digest([cp.get('callback_epoch', 0), request_key(value['id'])])
            item = opaque(params['itemId'])
            if callback in cp['callback_ids']:
                raise ValueError()
            if cp['phase'] == 'question_active':
                questions = params['questions']
                if (params.get('isBlocking') is not True or not isinstance(questions, list) or len(questions) != 1
                        or not isinstance(questions[0].get('header'), str)
                        or type(questions[0].get('isOther', False)) is not bool
                        or questions[0].get('isSecret', False) is not False):
                    raise ValueError()
                # The native UI may add free text; this reply selects only the fixed offered label.
                response = resolve_request(value, 'question', cp['binding']['root'], cp['turn'], set())
                phase = 'question_waiting'
            elif cp['phase'] == 'permission_active':
                expected = marker_command(python_executable)
                if (value['method'] != 'item/commandExecution/requestApproval'
                        or digest(cwd) != cp['binding']['cwd'] or params.get('cwd') != cwd
                        or digest(expected) != cp['binding']['command']
                        or not command_matches(params.get('command'), expected)
                        or type(params.get('startedAtMs')) is not int or not 0 <= params['startedAtMs'] < 2**63
                        or params.get('kind', 'command') != 'command'
                        or params.get('environmentId') is not None and (
                            opaque(params['environmentId']) != cp['binding'].get('environment'))
                        or any(params.get(k) is not None for k in ('additionalPermissions', 'networkApprovalContext',
                            'approvalId'))
                        or params.get('availableDecisions') is not None and (
                            not isinstance(params['availableDecisions'], list)
                            or not 0 < len(params['availableDecisions']) <= 8
                            or 'accept' not in params['availableDecisions'])):
                    raise ValueError()
                cp['issued_command'] = digest(params['command'])
                # Offered policy changes are separate decisions; accept only this command.
                response, phase = {'decision': 'accept'}, 'permission_waiting'
            else:
                raise ValueError()
            cp.update(phase=phase, callback=callback, item=item)
            cp['callback_ids'].append(callback)
            return {'id': value['id'], 'result': response}
        return self._change(change)

    def resolved(self, value):
        def change(cp):
            params = value['params']
            if ('id' in value or value['method'] != 'serverRequest/resolved'
                    or cp['phase'] not in ('question_waiting', 'permission_waiting') or cp['resolved']
                    or params.get('threadId') != cp['binding']['root']
                    or digest([cp.get('callback_epoch', 0), request_key(params['requestId'])]) != cp['callback']):
                raise ValueError()
            cp['resolved'] = True
            return True
        return self._change(change)

    def completed(self, value):
        def change(cp):
            params = value['params']
            if 'id' in value or params.get('threadId') != cp['binding']['root']:
                raise ValueError()
            if value['method'] == 'item/completed':
                item = params['item']
                if (cp['phase'] != 'permission_waiting' or cp['execution'] or params.get('turnId') != cp['turn']
                        or opaque(item['id']) != cp['item'] or item.get('type') != 'commandExecution'
                        or digest(item.get('command')) != cp['issued_command'] or item.get('status') != 'completed'
                        or type(item.get('exitCode')) is not int or item['exitCode'] != 0
                        or not isinstance(item.get('aggregatedOutput'), str) or len(item['aggregatedOutput']) > 64
                        or item['aggregatedOutput'].strip() != 'HAR5_APPROVED'):
                    raise ValueError()
                cp['execution'] = True
            elif value['method'] == 'turn/completed':
                turn = params['turn']
                if turn.get('id') != cp['turn'] or turn.get('status') != 'completed' or turn.get('error') is not None:
                    raise ValueError()
                if cp['phase'] == 'question_waiting' and cp['resolved']:
                    cp.update(phase='question_checkpoint', checkpoint_turn=cp['turn'])
                elif cp['phase'] == 'permission_waiting' and cp['resolved'] and cp['execution']:
                    cp['phase'] = 'permission_done'
                elif cp['phase'] == 'workflow_active':
                    cp['phase'] = 'workflow_held_unassessed'
                else:
                    raise ValueError()
            else:
                raise ValueError()
            return cp['phase']
        return self._change(change)

    def prepare_resume(self, root_uuid, checkpoint_turn_uuid, manifest_sha256):
        def change(cp):
            if (cp['phase'] != 'question_checkpoint' or root_uuid != cp['binding']['root']
                    or checkpoint_turn_uuid != cp['checkpoint_turn']
                    or manifest(manifest_sha256) != cp['binding']['manifest']):
                raise ValueError()
            cp['phase'] = 'resume_prepared'
            return {'threadId': cp['binding']['root']}
        return self._change(change)

    def prepare_history_read(self, root_uuid, rpc_id):
        def change(cp):
            if (cp['phase'] != 'resume_prepared' or root_uuid != cp['binding']['root']
                    or 'resume_history_read' in cp or type(rpc_id) is not int or rpc_id <= 0):
                raise ValueError()
            cp['resume_history_read'] = {'root': root_uuid, 'rpc_id': rpc_id}
            return {'threadId': root_uuid, 'sortDirection': 'asc',
                    'itemsView': 'notLoaded', 'limit': len(cp['turns'])+1}
        return self._change(change)

    def confirm_resume(self, response, manifest_sha256, *, history_page=None, history_request_id=None):
        def change(cp):
            thread = response['thread']
            if history_page is None:
                if ('resume_history_read' in cp or history_request_id is not None
                        or any(response.get(k) is not None for k in ('turnsBackwardsCursor', 'itemsBackwardsCursor', 'initialTurnsPage'))):
                    raise ValueError()
                turns = thread['turns']
            else:
                if (cp.get('resume_history_read') != {'root': cp['binding']['root'], 'rpc_id': history_request_id}
                        or type(history_request_id) is not int or history_page.get('nextCursor') is not None):
                    raise ValueError()
                turns = history_page['data']
            if (not isinstance(turns, list) or not turns
                    or len({t['id'] for t in turns}) != len(turns)
                    or [t['id'] for t in turns] != cp['turns']
                    or any(t.get('status') != 'completed' or t.get('error') is not None for t in turns)):
                raise ValueError()
            last = turns[-1]
            if (cp['phase'] != 'resume_prepared' or manifest(manifest_sha256) != cp['binding']['manifest']
                    or response.get('error') is not None or thread.get('forkedFromId') is not None
                    or thread.get('id') != cp['binding']['root'] or last.get('id') != cp['checkpoint_turn']
                    or last.get('status') != 'completed' or last.get('error') is not None):
                raise ValueError()
            cp['phase'] = 'resumed'
            cp['callback_epoch'] = cp.get('callback_epoch', 0)+1
            return cp['phase']
        return self._change(change)


class NativeInteractions:
    """One explicitly attached, fixed probe; never a general approval engine.

    The trusted caller must separately establish full S2 admission. This adapter
    checks integrity and attribution; it cannot turn partial gates into proof.
    """

    def __init__(self, connection, *, python_executable):
        from evaluation.signed_in_native import NativeConnection
        if (not isinstance(connection, NativeConnection) or connection.interaction is not None
                or connection.mode != 'diagnose' or connection.profile is None):
            raise ValueError('interaction_rejected')
        self.connection = connection
        self.python = python_executable
        marker_command(self.python)
        self.startup = deepcopy(connection.startup)
        self.info = self._configuration(connection.started)
        self.root, self.cwd = self.info['thread']['id'], self.info['cwd']
        owner = connection.owner
        self.owner = owner
        self.controller = Interactions(owner.store, owner.origin, owner.request_id)
        self.callbacks, self.seen = {}, set()
        self.callback_observations = []
        self.broken = False
        self.manifest = self._fingerprint()
        with owner.lock:
            self._guard()
            environments = self.info['thread']['environments']
            environment_id = environments[0]['environmentId'] if environments else None
            if self.controller.bind(self.root, self.manifest, cwd=self.cwd, python_executable=self.python,
                    environment_id=environment_id) != 'ready':
                raise ValueError('interaction_rejected')
            connection.interaction = self

    def _configuration(self, value):
        try:
            keys = ('model', 'modelProvider', 'reasoningEffort', 'cwd', 'runtimeWorkspaceRoots',
                'approvalPolicy', 'approvalsReviewer', 'activePermissionProfile', 'sandbox', 'instructionSources')
            result = {k: deepcopy(value[k]) for k in keys}
            thread = value['thread']
            result['thread'] = {k: deepcopy(thread[k]) for k in ('id', 'sessionId', 'cwd',
                'modelProvider', 'source', 'cliVersion', 'ephemeral')}
            result['thread'].update({k: deepcopy(thread.get(k)) for k in
                ('forkedFromId', 'parentThreadId', 'agentRole', 'model', 'reasoningEffort', 'threadSource')})
            consumer = str(self.startup[1])
            environments = thread.get('environments')
            if environments is not None:
                if not isinstance(environments, list) or len(environments) != 1:
                    raise ValueError()
                environment = environments[0]
                opaque(environment['environmentId'])
                if environment['cwd'] != consumer or environment['runtimeWorkspaceRoots'] != [consumer]:
                    raise ValueError()
                environments = [{k: deepcopy(environment[k]) for k in
                    ('environmentId', 'cwd', 'runtimeWorkspaceRoots')}]
            result['thread']['environments'] = environments
            if (result['model'] != 'gpt-6-luna' or result['reasoningEffort'] != 'low'
                    or result['modelProvider'] != 'openai' or result['cwd'] != consumer
                    or result['runtimeWorkspaceRoots'] != [consumer]
                    or result['approvalPolicy'] != 'on-request' or result['approvalsReviewer'] != 'user'
                    or result['activePermissionProfile']['id'] != 'har12-native'
                    or not isinstance(result['sandbox'], dict) or not result['sandbox']
                    or result['instructionSources'] != [str(self.startup[1]/'AGENTS.md')]
                    or identity(thread['id']) != thread['sessionId'] or thread['cwd'] != consumer
                    or thread['modelProvider'] != 'openai' or not thread['source'] or not thread['cliVersion']
                    or thread.get('model') not in (None, 'gpt-6-luna')
                    or thread.get('reasoningEffort') not in (None, 'low')
                    or thread['ephemeral'] is not False
                    or any(thread.get(k) is not None for k in ('forkedFromId', 'parentThreadId', 'agentRole'))):
                raise ValueError()
            result['thread']['model'] = result['model']
            result['thread']['reasoningEffort'] = result['reasoningEffort']
            return result
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError('interaction_rejected') from None

    def _fingerprint(self):
        from native_support import digest as file_digest, inventory
        source = Path(__file__).resolve().parent
        names = ('signed_in.py', 'signed_in_native.py', 'signed_in_process.py',
                 'signed_in_profiles.py', 'signed_in_worker.py', 'signed_in_interactions.py', 'probes.py')
        try:
            files = {n: file_digest(source/n) for n in names}
            files['native_support.py'] = file_digest(source.parent/'native_support.py')
            return digest({'source': files, 'consumer': inventory(self.startup[1], root_exclude=('.git', '.tmp')),
                'startup': [self.startup[0], str(self.startup[1]), self.startup[2]],
                'info': self.info, 'profile': self.connection.profile, 'python': self.python})
        except (OSError, RuntimeError, ValueError):
            raise ValueError('interaction_rejected') from None

    def _guard(self):
        from evaluation.signed_in_native import ROOT
        from evaluation.signed_in_profiles import require_binding
        connection, owner = self.connection, self.connection.owner
        owner.remaining()
        if (self.broken or owner is not self.owner or connection.startup != self.startup or connection.mode != 'diagnose'
                or self._fingerprint() != self.manifest):
            raise ValueError('interaction_rejected')
        require_binding(owner.store, owner.origin, owner.request_id, connection.profile,
            root=ROOT, require_launch=True, root_thread=self.root)
        with owner.store.request(owner.origin, owner.request_id) as state:
            if state.get('native_selection') != {'model': 'gpt-6-luna', 'effort': 'low'}:
                raise ValueError('interaction_rejected')

    def capture(self, value):
        # Called only by this connection's bounded native receiver, before queueing.
        try:
            with self.connection.owner.lock:
                self._guard()
                key = request_key(value['id'])
                if (key in self.seen or len(self.seen) >= 2
                        or value['method'] not in ('item/tool/requestUserInput', 'item/commandExecution/requestApproval')
                        or value['params']['threadId'] != self.root):
                    raise ValueError()
                self.seen.add(key)
                self.callbacks[key] = digest(value)
                params = value['params']
                environments = self.info['thread']['environments']
                environment_id = environments[0]['environmentId'] if environments else None
                self.callback_observations.append({
                    'kind': 'question' if value['method'] == 'item/tool/requestUserInput' else 'command',
                    'environment_matches': params.get('environmentId') in (None, environment_id),
                    'command_matches': command_matches(params.get('command'), marker_command(self.python)),
                    'cwd_matches': params.get('cwd') == self.cwd,
                    'command_kind': params.get('kind', 'command') == 'command',
                    'started_at_integer': type(params.get('startedAtMs')) is int,
                    'approval_id_present': params.get('approvalId') is not None,
                    'additional_permissions_present': params.get('additionalPermissions') is not None,
                    'network_context_present': params.get('networkApprovalContext') is not None,
                    'policy_amendment_present': any(params.get(k) is not None for k in
                        ('proposedExecpolicyAmendment', 'proposedNetworkPolicyAmendments'))})
        except (ValueError, TypeError, KeyError):
            self.broken = True
            raise ValueError('interaction_rejected') from None

    def start(self, kind):
        from evaluation.probes import PROBES
        prompts = dict(PROBES)
        if kind == 'permission':
            prompt = ('Request native approval once for the following exact PowerShell command with '
                'sandbox_permissions=require_escalated and no prefix_rule, in the current cwd. '
                'Wait, execute it once after approval, then stop; no other commands.\n\n```powershell\n'
                + marker_command(self.python)+'\n```')
        elif kind in ('question', 'workflow'):
            prompt = prompts[kind]
        else:
            raise ValueError('interaction_rejected')
        with self.connection.owner.lock:
            self._guard()
            self.controller.prepare_turn(kind)
        try:
            started = self.connection.call('turn/start', {'threadId': self.root,
                'input': [{'type': 'text', 'text': prompt}], 'collaborationMode': {
                    'mode': 'plan' if kind == 'question' else 'default', 'settings': {
                        'model': 'gpt-6-luna', 'reasoning_effort': 'low', 'developer_instructions': None}}})
            with self.connection.owner.lock:
                self._guard()
                self.controller.begin(kind, started['turn']['id'])
            return started['turn']['id']
        except BaseException:
            self.broken = True
            raise

    def reply(self, value):
        with self.connection.owner.lock:
            self._guard()
            key = request_key(value.get('id'))
            if self.callbacks.get(key) != digest(value):
                raise ValueError('interaction_rejected')
            reply = self.controller.reply(value, cwd=self.cwd, python_executable=self.python)
            del self.callbacks[key]
        try:
            self.connection._write(reply)
        except Exception:
            self.broken = True
            raise RuntimeError('native_interaction_failed') from None

    def event(self):
        with self.connection.owner.lock:
            self._guard()
        value = self.connection.event()
        try:
            params, method = value.get('params', {}), value.get('method')
            if params.get('threadId', self.root) != self.root:
                raise ValueError('interaction_rejected')
            if params.get('item', {}).get('type') == 'subAgentActivity':
                raise RuntimeError('unexpected_child_dispatch')
            if 'id' in value and method:
                self.reply(value)
            else:
                with self.connection.owner.lock:
                    self._guard()
                    if method == 'serverRequest/resolved':
                        return self.controller.resolved(value)
                    if method == 'turn/completed' or (method == 'item/completed'
                            and params.get('item', {}).get('type') == 'commandExecution'):
                        return self.controller.completed(value)
        except BaseException:
            self.broken = True
            raise

    def resume(self):
        from evaluation.signed_in_native import NativeConnection
        old, owner = self.connection, self.connection.owner
        with owner.lock:
            self._guard()
            with owner.store.request(owner.origin, owner.request_id) as state:
                checkpoint = deepcopy(state['native_interaction'])
            params = self.controller.prepare_resume(self.root, checkpoint.get('checkpoint_turn'), self.manifest)
        try:
            if self.callbacks:
                raise ValueError('interaction_rejected')
            old.process.stdin.close()
            old.process.wait(timeout=owner.remaining())
            old.interaction = None
            with owner.lock:
                self._guard()
            self.connection = NativeConnection(owner, *self.startup, mode='diagnose', profile=old.profile)
            new = self.connection
            new.call('initialize', {'clientInfo': {'name': 'har12_native_windows', 'version': '1'},
                'capabilities': {'experimentalApi': True}})
            new.send({'method': 'initialized'})
            with owner.lock:
                self._guard()
                new.sequence += 1
                request_id = new.sequence
                new.request_methods[request_id]='thread/resume'
            new._write({'id': request_id, 'method': 'thread/resume',
                        'params': {**params, 'excludeTurns': True}})
            response = new.wait(request_id)
            with owner.lock:
                self._guard()
                if self._configuration(response) != self.info:
                    raise ValueError('interaction_rejected')
                needs_history = (not response['thread'].get('turns') or any(response.get(k) is not None
                    for k in ('turnsBackwardsCursor', 'itemsBackwardsCursor', 'initialTurnsPage')))
                if needs_history:
                    new.sequence += 1
                    history_id = new.sequence
                    new.request_methods[history_id]='thread/turns/list'
                    history_params = self.controller.prepare_history_read(self.root, history_id)
            if needs_history:
                new._write({'id': history_id, 'method': 'thread/turns/list', 'params': history_params})
                page = new.wait(history_id)
                with owner.lock:
                    self._guard()
                    self.controller.confirm_resume(response, self.manifest,
                        history_page=page, history_request_id=history_id)
                self.resume_history_source = 'thread/turns/list'
                self.resume_history_request_id = history_id
            else:
                with owner.lock:
                    self.controller.confirm_resume(response, self.manifest)
                self.resume_history_source = 'inline'
            with owner.lock:
                self.seen.clear()  # Native server request numbers restart on the new connection.
                new.interaction = self
        except (ValueError, KeyError):
            self.broken = True
            raise ValueError('interaction_rejected') from None
        except Exception:
            self.broken = True
            raise RuntimeError('native_interaction_failed') from None
