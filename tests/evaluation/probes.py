"""Small native-interface probes, not the evaluator's private grading rules.

The public tasks deliberately exercise protocol capabilities. No full delivery,
hidden functional expectations or general unattended approval engine lives here.
"""

import json
import shlex
import time


PROBES = [
    ('question', 'Use the native request_user_input tool once. Ask exactly "Which label should the public probe use?" with question id har5_choice and choices Alpha and Beta. Wait for the answer, then stop. This is only a native transport probe; do not read or change project files.'),
    ('approval', 'The preceding transport probe is finished. Use the native command tool to request permission for exactly this benign command, with sandbox_permissions=require_escalated and no prefix_rule: python -c "print(\'HAR5_APPROVED\')". It prints a public marker only. Wait for native approval, execute that exact command once, then stop. Do not bypass approval or run other commands.'),
    ('workflow', '$deliver-task Fix the off-by-one result in .tmp/native-foundation/after.py against .tmp/native-foundation/contract.md. This is a bounded interface probe: perform stage 1 normally and stop at its human approval gate. No later stage or implementation is approved.'),
    ('plan-reviewer', 'Cancel the preceding stage-only transport task without approving later delivery stages. For this separate read-only native capability probe, dispatch the installed native plan-reviewer to assess the exact scope/plan in .tmp/native-foundation/contract.md and plan.md. Supply actual guidance and scope contents plus those files. No substitute role, implementation, project checks, commits or publication. Wait for its assessment and stop.'),
    ('code-reviewer', '$review-code Independently assess the known before/after comparison in .tmp/native-foundation/before.py and after.py against .tmp/native-foundation/contract.md. Use the installed native code-reviewer, with actual applicable guidance and comparison contents. No fixes, project checks, commits or publication. Return its findings and stop.'),
    ('cancellation', 'For this final native cancellation probe, run the command `python /opt/evaluation/worker.py heartbeat`. It starts a bounded descendant writing a public heartbeat. Wait for it; the controller will interrupt this turn. Do not kill it yourself, alter the script, spawn reviewers or start other tasks.'),
]


def approval_command(command):
    if not isinstance(command, str):
        return False
    parts = shlex.split(command)
    if len(parts) == 3 and parts[0] in ('/bin/bash', 'bash', '/bin/sh', 'sh') and parts[1] in ('-lc', '-c'):
        parts = shlex.split(parts[2])
    return parts == ['python', '-c', "print('HAR5_APPROVED')"]


def resolve_request(value, kind, thread, turn, seen):
    params = value.get('params', {})
    identity = (params.get('threadId'), params.get('turnId'), value.get('id'))
    if identity[:2] != (thread, turn) or identity in seen:
        raise ValueError('Wrong, stale or duplicate native request')
    if kind == 'question' and value['method'] == 'item/tool/requestUserInput':
        questions = params.get('questions', [])
        if len(questions) != 1 or questions[0].get('id') != 'har5_choice' or questions[0].get('question') != 'Which label should the public probe use?':
            raise ValueError('Unmatched probe question')
        labels = [o['label'] for o in questions[0].get('options', [])]
        if sorted(label.removesuffix(' (Recommended)') for label in labels) != ['Alpha', 'Beta']:
            raise ValueError('Unmatched probe choices')
        answer = next(label for label in labels if label.removesuffix(' (Recommended)') == 'Alpha')
        response = {'answers': {'har5_choice': {'answers': [answer]}}}
    elif kind == 'approval' and value['method'] == 'item/commandExecution/requestApproval' and approval_command(params.get('command')):
        if params.get('cwd') != '/work/codex':
            raise ValueError('Native approval cwd mismatch')
        response = {'decision': 'accept'}
    else:
        raise ValueError('Unmatched native request blocks the probe')
    seen.add(identity)
    return response


def run_turn(connection, thread, kind, prompt, model, effort, heartbeat, disarm, deadline, on_cancel, record=None):
    mode = 'plan' if kind == 'question' else 'default'
    started = connection.call('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': prompt}],
        'collaborationMode': {'mode': mode, 'settings': {'model': model, 'reasoning_effort': effort, 'developer_instructions': None}}})
    turn = started['turn']['id']
    observed = record if record is not None else {}
    observed.update({'kind': kind, 'thread_id': thread, 'turn_id': turn, 'responses': [], 'children': [], 'status': 'incomplete'})
    seen, interrupted_at = set(), None
    while time.monotonic() < deadline:
        if kind == 'cancellation' and interrupted_at is None and heartbeat() is not None:
            interrupted_at = time.monotonic()
            deadline = min(deadline, interrupted_at + 10)
            on_cancel(deadline)
            connection.sequence += 1
            connection.send({'id': connection.sequence, 'method': 'turn/interrupt', 'params': {'threadId': thread, 'turnId': turn}})
            disarm()
        try:
            value = connection.receive(min(0.5 if kind == 'cancellation' else 30, deadline - time.monotonic()))
        except TimeoutError:
            continue
        params, method = value.get('params', {}), value.get('method')
        if method and 'id' in value:
            response = resolve_request(value, kind, thread, turn, seen)
            connection.send({'id': value['id'], 'result': response})
            observed['responses'].append({'request_id': value['id'], 'method': method, 'thread_id': thread, 'turn_id': turn, 'response': response})
        item = params.get('item', {})
        if method == 'item/completed' and item.get('type') == 'collabAgentToolCall' and item.get('senderThreadId') == thread:
            observed['children'] += item.get('receiverThreadIds', [])
        if (method == 'item/completed' and params.get('threadId') == thread
                and item.get('type') == 'subAgentActivity' and item.get('kind') == 'started'
                and isinstance(item.get('agentThreadId'), str)):
            observed['children'].append(item['agentThreadId'])
        if method == 'turn/completed' and params.get('threadId') == thread and params.get('turn', {}).get('id') == turn:
            observed['status'] = params['turn']['status']
            if params['turn'].get('error'):
                observed['error'] = params['turn']['error']
            break
    else:
        raise TimeoutError('Native probe turn deadline exhausted')
    if observed['status'] == 'failed':
        raise RuntimeError('Native probe failed: ' + json.dumps(observed.get('error')))
    if kind in ('question', 'approval') and len(observed['responses']) != 1:
        raise ValueError('Required correlated native request was not observed once')
    for request in observed['responses']:
        if not any(e.get('method') == 'serverRequest/resolved' and e.get('params', {}).get('threadId') == thread
                   and e.get('params', {}).get('requestId') == request['request_id'] for e in connection.events):
            raise ValueError('Native request resolution correlation missing')
    if kind == 'approval' and not any(e.get('method') == 'item/completed' and
            e.get('params', {}).get('item', {}).get('type') == 'commandExecution' and
            approval_command(e['params']['item'].get('command')) and e['params']['item'].get('exitCode') == 0 and
            'HAR5_APPROVED' in e['params']['item'].get('aggregatedOutput', '') for e in connection.events):
        raise ValueError('Approved command actual execution evidence missing')
    if kind == 'cancellation':
        if interrupted_at is None or observed['status'] != 'interrupted':
            raise ValueError('Required active native cancellation was not observed')
        # Native interruption acknowledges the turn but can leave a shell's
        # descendant alive. Terminate the dedicated namespace's processes now,
        # within the same cancellation deadline, before external readback.
        connection.close()
        observed['termination_method'] = 'native-interrupt-and-owned-worker-process-cleanup'
        first = heartbeat()
        stable = 0
        while first is not None and stable < 2 and time.monotonic() - interrupted_at < 9:
            time.sleep(0.2)
            latest = heartbeat()
            stable = stable + 1 if latest == first else 0
            first = latest
        if first is None or stable < 2 or time.monotonic() - interrupted_at > 10:
            raise ValueError('Native cancellation did not stop the heartbeat descendant within budget')
        observed['cancellation_seconds'] = time.monotonic() - interrupted_at
    elif observed['status'] != 'completed':
        raise ValueError('Native probe turn did not complete')
    return observed
