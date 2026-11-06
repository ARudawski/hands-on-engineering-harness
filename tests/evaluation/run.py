"""Opt-in local native feasibility controller. Preparation never runs a model."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import socket
import sys
import tempfile
import threading
import time
from uuid import uuid4
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_support import collect_native_evidence, digest, inventory, run_turn
from native import Connection, public_event, remaining, sandbox_gate
from probes import PROBES, run_turn as probe_turn

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
UTILITY_BASE = '99c823abd4f0fc9cc58eda47ca775de64415fd35'
LIMITS = {'turns': 8, 'turn_seconds': 1200, 'trial_seconds': 7200, 'cancel_seconds': 10}
PROFILE_URL = 'https://raw.githubusercontent.com/moby/profiles/seccomp/v0.2.4/seccomp/default.json'
PROFILE_HASH = '785b2429264afba4d594320337cb17f144f3c7d51585f9805eef72e28f4f9334'


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix('.new')
    tmp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def command(args, stdin='', timeout=300, check=True, deadline=None):
    p = (subprocess.run(args, input=stdin, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
                        timeout=remaining(deadline, timeout)) if deadline is not None else run_turn(args, stdin, ROOT, timeout))
    if len(p.stdout) + len(p.stderr) > 4 * 1024 * 1024:
        raise RuntimeError('Subprocess output budget exceeded')
    if check and p.returncode:
        raise RuntimeError(f'{args[0]} exited {p.returncode}: {p.stderr[-1500:]} {p.stdout[-1500:]}')
    return p


def docker(*args, stdin='', timeout=300, check=True, deadline=None):
    return command(['docker', *args], stdin, timeout, check, deadline)


def controller_inputs():
    paths = [Path('tests/apm_support.py'), Path('tests/native_support.py')]
    paths += [p.relative_to(ROOT) for p in HERE.iterdir() if p.is_file()]
    return {p.as_posix(): digest(ROOT / p) for p in paths}


def validate_config(config):
    required = {'comparison_id', 'case_id', 'variant', 'baseline', 'candidate', 'model', 'effort', 'image_id', 'limits', 'codex_version', 'apm_version', 'fixture_revision'}
    if config.keys() != required:
        raise ValueError('Configuration fields are missing or unsupported')
    for name in ('baseline', 'candidate'):
        if not re.fullmatch('[0-9a-f]{40}', config[name]):
            raise ValueError('Full immutable repository SHAs required')
    if config['variant'] not in ('baseline', 'candidate') or config['limits'] != LIMITS:
        raise ValueError('Unsupported variant or unfrozen probe limits')
    if config['codex_version'] != '0.166.0-alpha.6' or config['apm_version'] != '0.35.0':
        raise ValueError('Unsupported client/APM version')
    if not re.fullmatch('sha256:[0-9a-f]{64}', config['image_id']):
        raise ValueError('Exact image ID required')
    for name in ('comparison_id', 'case_id', 'model', 'effort', 'fixture_revision'):
        if not isinstance(config[name], str) or not config[name].strip():
            raise ValueError('Empty fixed input: ' + name)
    if config['effort'] != 'xhigh':
        raise ValueError('Unsupported probe reasoning configuration')


def source_files(revision):
    names = command(['git', 'ls-tree', '-r', '--name-only', revision]).stdout.splitlines()
    return {p: hashlib.sha256(subprocess.check_output(['git', 'show', f'{revision}:{p}'], cwd=ROOT, timeout=15)).hexdigest() for p in names}


def engine_identity():
    data = json.loads(docker('version', '--format', '{{json .Server}}').stdout)
    return {k: data[k] for k in ('Version', 'GitCommit', 'KernelVersion', 'Os', 'Arch')}


def namespace_profile(path):
    with urllib.request.urlopen(PROFILE_URL, timeout=20) as response:
        source = response.read(1024 * 1024)
    if hashlib.sha256(source).hexdigest() != PROFILE_HASH:
        raise ValueError('Engine-pinned default seccomp source changed')
    profile = json.loads(source)
    additions = [{'names': ['clone'], 'action': 'SCMP_ACT_ALLOW', 'args': [
        {'index': 0, 'value': 0x10000000, 'valueTwo': 0x10000000, 'op': 'SCMP_CMP_MASKED_EQ'}], 'includes': {'arches': ['amd64']}}]
    additions += [{'names': ['unshare'], 'action': 'SCMP_ACT_ALLOW', 'args': [
        {'index': 0, 'value': flags, 'op': 'SCMP_CMP_EQ'}], 'includes': {'arches': ['amd64']}}
        for flags in (0x10000000, 0x20000, 0x40000000)]
    additions += [{'names': ['mount', 'umount2', 'pivot_root'], 'action': 'SCMP_ACT_ALLOW', 'includes': {'arches': ['amd64']}}]
    profile['syscalls'] += additions
    write_json(path, profile)
    if digest(path) != '47d44d3ec906bdcfef91e81271c7503fe33e367a1343774cfa0adf6f5d0db388':
        raise ValueError('Generated seccomp profile differs from reviewed candidate')
    return {'url': PROFILE_URL, 'base_sha256': PROFILE_HASH, 'sha256': digest(path), 'additions': additions}


def load(out, validate_current=True):
    out = Path(out).resolve()
    manifest = json.loads((out / 'manifest.json').read_text())
    if manifest['output_dir'] != str(out) or validate_current and manifest['controller_inputs'] != controller_inputs():
        raise ValueError('Output identity or controller/utility inputs changed')
    validate_config(manifest['config'])
    if validate_current:
        frozen = out / 'inputs.json'
        if digest(frozen) != manifest['frozen_inputs_sha256']:
            raise ValueError('Frozen input fingerprint changed')
        expected = json.loads(frozen.read_text())
        if (expected['config'] != manifest['config'] or expected['engine'] != engine_identity()
                or expected['resources'] != manifest['resources'] or expected['seccomp'] != manifest['seccomp']):
            raise ValueError('Prepared configuration or engine changed')
    return out, manifest


def owned(manifest, role, deadline=None):
    identity = manifest['resources'][role]
    data = json.loads(docker('inspect', identity, deadline=deadline).stdout)[0]
    if data['Id'] != identity or data['Config']['Labels'].get('har5.trial') != manifest['trial_id'] or data['Config']['Labels'].get('har5.role') != role:
        raise ValueError('Resource identity/ownership mismatch')
    return data


def safe_inspect(data):
    return {k: data[k] for k in ('Id', 'Image', 'Mounts', 'NetworkSettings', 'HostConfig')} | {
        'user': data['Config']['User'], 'labels': data['Config']['Labels'],
    }


def execute_worker(manifest, operation, data, role='worker', timeout=300, deadline=None):
    owned(manifest, role, deadline)
    p = docker('exec', '-i', manifest['resources'][role], 'python', '/opt/evaluation/worker.py', operation,
               stdin=json.dumps(data), timeout=timeout, deadline=deadline)
    return json.loads(p.stdout)


def prepare(out, config):
    validate_config(config)
    out = Path(out).resolve()
    if ROOT.is_relative_to(out) or out.is_relative_to(ROOT) and not out.is_relative_to(ROOT / '.tmp'):
        raise ValueError('Evidence must stay outside published source')
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('Fresh preparation requires an empty output directory')
    manifest = {'output_dir': str(out), 'config': config, 'utility_base': UTILITY_BASE,
                'controller_inputs': controller_inputs(), 'trial_id': 'har5-' + uuid4().hex[:16],
                'attempt_id': str(uuid4()), 'resources': {}, 'status': 'preparing', 'turns': []}
    persist = lambda: write_json(out / 'manifest.json', manifest)
    persist()
    try:
        engine = engine_identity()
        if engine['Version'] != '29.9.2' or engine['Arch'] != 'amd64' or engine['Os'] != 'linux':
            raise ValueError('This feasibility deployment requires Linux amd64 Engine 29.9.2')
        manifest['engine'] = engine
        manifest['seccomp'] = namespace_profile(out / 'seccomp.json')
        if json.loads(docker('image', 'inspect', config['image_id']).stdout)[0]['Id'] != config['image_id']:
            raise ValueError('Worker image changed')
        trial = manifest['trial_id']
        net = docker('network', 'create', '--internal', '--label', 'har5.trial=' + trial, trial).stdout.strip()
        manifest['resources']['network'] = net
        persist()
        for role in ('work', 'home', 'relay-state', 'previous-work', 'previous-home'):
            volume = docker('volume', 'create', '--label', 'har5.trial=' + trial, trial + '-' + role).stdout.strip()
            if json.loads(docker('volume', 'inspect', volume).stdout)[0]['Labels'].get('har5.trial') != trial:
                raise ValueError('Existing/foreign volume cannot be adopted')
            manifest['resources'][role] = volume
            persist()
        common = ['--label', 'har5.trial=' + trial, '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                  '--pids-limit', '256', '--memory', '2g', '--cpus', '2', '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m']
        volumes = ['--mount', f'type=volume,source={manifest["resources"]["work"]},target=/work',
                   '--mount', f'type=volume,source={manifest["resources"]["home"]},target=/home/agent']
        prep = docker('create', '--name', trial + '-prepare', '--label', 'har5.role=prepare', *common, *volumes, config['image_id']).stdout.strip()
        manifest['resources']['prepare'] = prep
        persist()
        docker('start', prep)
        actual_helpers = json.loads(docker('exec', prep, 'python', '-c',
            "import hashlib,json,pathlib; print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in pathlib.Path('/opt/evaluation').glob('*.py')}))").stdout)
        for filename in ('worker.py', 'relay.py', 'apm_support.py', 'native_support.py'):
            path = HERE / filename if filename in ('worker.py', 'relay.py') else ROOT / 'tests' / filename
            if actual_helpers.get(filename) != digest(path):
                raise ValueError('Worker image helper input drift: ' + filename)
        revision = config[config['variant']]
        manifest['installation'] = execute_worker(manifest, 'install', {'revision': revision, 'source_files': source_files(revision)}, 'prepare', 900)
        if manifest['installation']['fixture_revision'] != config['fixture_revision']:
            raise ValueError('Actual image fixture revision differs from declared input')
        persist()
        docker('stop', '--time', '1', prep)
        worker = docker('create', '--name', trial + '-worker', '--label', 'har5.role=worker', *common, *volumes,
                        '--security-opt', 'seccomp=' + str(out / 'seccomp.json'),
                        '--network', net, '--dns', '127.0.0.1', config['image_id'], 'python', '-c',
                        'import time; time.sleep(7200)').stdout.strip()
        manifest['resources']['worker'] = worker
        persist()
        docker('start', worker)
        # The trusted relay is a separate namespace, with no worker-visible control path.
        relay = docker('create', '--name', trial + '-relay', '--label', 'har5.role=relay', *common,
                       '--env', 'OPENAI_API_KEY', '--env', 'EVALUATION_MODEL=' + config['model'],
                       '--env', 'EVALUATION_EFFORT=' + config['effort'], '--env', 'EVALUATION_TRIAL=' + trial,
                       '--mount', f'type=volume,source={manifest["resources"]["relay-state"]},target=/state',
                       config['image_id'], 'python', '/opt/evaluation/relay.py').stdout.strip()
        manifest['resources']['relay'] = relay
        persist()
        docker('network', 'connect', '--alias', 'model-relay', net, relay)
        docker('start', relay)
        # A real separate worker supplies planted prior-state and network canaries.
        canary = docker('create', '--name', trial + '-previous-fixture', '--label', 'har5.role=canary', *common,
                        '--mount', f'type=volume,source={manifest["resources"]["previous-work"]},target=/work',
                        '--mount', f'type=volume,source={manifest["resources"]["previous-home"]},target=/home/agent',
                        config['image_id']).stdout.strip()
        manifest['resources']['canary'] = canary
        persist()
        docker('start', canary)
        marker = uuid4().hex
        docker('exec', '-i', canary, 'python', '-c',
               "import pathlib,sys; text=sys.stdin.read(); paths=['/work/solution','/home/agent/.codex/sessions/previous','/home/agent/.cache/previous']; [(pathlib.Path(p).parent.mkdir(parents=True,exist_ok=True),pathlib.Path(p).write_text(text)) for p in paths]", stdin=marker)
        docker('exec', '-d', canary, 'python', '-m', 'http.server', '8081', '--directory', '/work')
        manifest['canary_sha256'] = hashlib.sha256(marker.encode()).hexdigest()
        manifest['canary_deployment'] = safe_inspect(owned(manifest, 'canary'))
        manifest['deployment'] = {role: safe_inspect(owned(manifest, role)) for role in ('worker', 'relay')}
        write_json(out / 'inputs.json', {'config': config, 'engine': engine, 'controller_inputs': manifest['controller_inputs'],
                                        'seccomp': manifest['seccomp'], 'resources': manifest['resources']})
        manifest['frozen_inputs_sha256'] = digest(out / 'inputs.json')
        manifest['status'] = 'prepared'
        persist()
        return manifest
    except BaseException as error:
        manifest['status'], manifest['error'] = 'preparation-incomplete', str(error)
        persist()
        raise


def preflight(out, manifest):
    if manifest['status'] != 'prepared':
        raise ValueError('Preflight requires an intact prepared worker')
    for role in ('worker', 'relay'):
        if safe_inspect(owned(manifest, role)) != manifest['deployment'][role]:
            raise ValueError('Deployment changed')
    before = execute_worker(manifest, 'inventory', {})
    if any(before[t] != manifest['installation'][t]['files'] for t in ('codex', 'claude')):
        raise ValueError('Materialized/deployed installation changed')
    runtime = execute_worker(manifest, 'runtime-state', {})
    if any(runtime[k] != manifest['installation'][k] for k in ('runtime_config_sha256', 'fixture_hashes')):
        raise ValueError('Runtime trust or fixed probe fixture changed')
    worker = manifest['deployment']['worker']
    if worker['user'] != '10001:10001' or worker['HostConfig']['Privileged'] or not worker['HostConfig']['ReadonlyRootfs']:
        raise ValueError('Unsupported worker privilege boundary')
    if any(m['Type'] != 'volume' for m in worker['Mounts']) or set(worker['NetworkSettings']['Networks']) != {manifest['trial_id']}:
        raise ValueError('Unexpected worker route/mount')
    forbidden = [['1.1.1.1', 443], ['169.254.169.254', 80], ['host.docker.internal', 80], ['host.docker.internal', 2375]]
    canary = owned(manifest, 'canary')
    canary_ip = canary['NetworkSettings']['Networks']['bridge']['IPAddress']
    # A trusted preparation worker on the ordinary bridge must reach the canary.
    docker('start', manifest['resources']['prepare'])
    try:
        control = docker('exec', manifest['resources']['prepare'], 'python', '-c',
            "import urllib.request,hashlib,socket,json; data=urllib.request.urlopen('http://" + canary_ip + ":8081/solution',timeout=3).read(); print(json.dumps({'canary':hashlib.sha256(data).hexdigest(),'dns':socket.getaddrinfo('example.com',443)[0][4][0]}))")
        controls = json.loads(control.stdout)
        if controls['canary'] != manifest['canary_sha256'] or not controls['dns']:
            raise ValueError('External canary/DNS positive controls failed')
        manifest['positive_controls'] = controls
    finally:
        docker('stop', '--time', '1', manifest['resources']['prepare'])
    forbidden.append([canary_ip, 8081])
    gateway = worker['NetworkSettings']['Networks'][manifest['trial_id']]['Gateway']
    if gateway:
        forbidden += [[gateway, p] for p in (80, 2375, 2376)]
    host_canary = '/run/desktop/mnt/host/' + str(out / 'protected-canary').replace('\\', '/').replace('C:', 'c')
    prior_paths = [m['Source'] + suffix for m in canary['Mounts'] for suffix in (
        ['/solution'] if m['Destination'] == '/work' else ['/.codex/sessions/previous', '/.cache/previous'])]
    inputs = {'trial': manifest['trial_id'], 'forbidden_reads': [host_canary, *prior_paths,
              '/home/agent/.codex/auth.json'], 'forbidden_network': forbidden, 'dns_canary': 'example.com'}
    canary = out / 'protected-canary'
    canary.write_text(uuid4().hex)
    canary_hash = digest(canary)
    manifest['preflight'] = execute_worker(manifest, 'preflight', inputs, timeout=60)
    manifest['relay_checks'] = execute_worker(manifest, 'relay-checks', {**inputs, 'model': manifest['config']['model'], 'effort': manifest['config']['effort']})
    manifest['relay_meter'] = json.loads(docker('exec', manifest['resources']['relay'], 'cat', '/state/meter.json').stdout)
    if manifest['relay_meter']['accepted'] != 0 or manifest['relay_meter']['requests'] != 14 or manifest['relay_meter']['denied'] != 12:
        raise ValueError('Relay denial/accounting evidence mismatch')
    if digest(canary) != canary_hash or not all(manifest['preflight'].values()) or not all(manifest['relay_checks'].values()):
        raise ValueError('Containment preflight failed')
    manifest['preflight_inputs'] = inputs
    manifest['status'] = 'local-preflight-passed-native-sandbox-pending'
    write_json(out / 'manifest.json', manifest)
    return manifest


def check_runtime_state(manifest, deadline=None):
    current = execute_worker(manifest, 'runtime-state', {}, deadline=deadline)
    if any(current[k] != manifest['installation'][k] for k in ('runtime_config_sha256', 'fixture_hashes')):
        raise ValueError('Runtime trust/configuration or fixed fixture changed')
    installed = execute_worker(manifest, 'inventory', {}, deadline=deadline)
    for target in ('codex', 'claude'):
        if installed[target] != manifest['installation'][target]['files']:
            raise ValueError('Immutable full installation changed')
    for role in ('worker', 'relay'):
        if safe_inspect(owned(manifest, role, deadline)) != manifest['deployment'][role]:
            raise ValueError('Worker/relay deployment changed')


def relay_control(manifest, expires, deadline=None):
    owned(manifest, 'relay', deadline)
    docker('exec', '-i', manifest['resources']['relay'], 'python', '-c',
           "import pathlib,sys; p=pathlib.Path('/state/control.new'); p.write_text(sys.stdin.read()); p.replace('/state/control.json')",
           stdin=json.dumps({'trial': manifest['trial_id'], 'expires': expires}), timeout=3, deadline=deadline)


def heartbeat(manifest, deadline=None):
    p = docker('exec', manifest['resources']['worker'], 'python', '-c',
        "from pathlib import Path; p=Path('/work/codex/.tmp/native-foundation/heartbeat'); print(p.read_text() if p.exists() else '')", timeout=3, deadline=deadline)
    return p.stdout.strip() or None


def collect_session(manifest, out, number, deadline=None):
    # Raw native history is read only in a controller-owned temporary directory;
    # the retained export uses the same own-action/no-reasoning collector as smoke.
    with tempfile.TemporaryDirectory(prefix='native-extract-', dir=out) as directory:
        root = Path(directory).resolve()
        if not root.is_relative_to(out.resolve()):
            raise ValueError('Unexpected temporary evidence path')
        docker('cp', manifest['resources']['worker'] + ':/home/agent/.codex/sessions', str(root / 'sessions'), deadline=deadline)
        files = list((root / 'sessions').rglob('*'))
        if len(files) > 1024 or any(p.is_symlink() for p in files) or sum(p.stat().st_size for p in files if p.is_file()) > 32 * 1024 * 1024:
            raise ValueError('Native evidence inventory/size boundary exceeded')
        matches = list((root / 'sessions').rglob('*' + manifest['session_id'] + '.jsonl'))
        if len(matches) != 1:
            raise ValueError('Exact native parent evidence missing/ambiguous')
        records = collect_native_evidence(manifest['session_id'], root / 'sessions', matches[0])
        # Paths identify the original worker logs, not the temporary extraction.
        for record in records:
            record['path'] = '/home/agent/.codex/sessions/' + Path(record['path']).relative_to(root / 'sessions').as_posix()
        write_json(out / f'turn-{number}.native.json', public_event(records))
        return records


NATIVE_SANDBOX = {'type': 'workspaceWrite', 'writableRoots': [], 'networkAccess': False,
                  'excludeTmpdirEnvVar': False, 'excludeSlashTmp': False}


def check_effective(state, config):
    expected = {'model': config['model'], 'modelProvider': 'evaluation', 'reasoningEffort': config['effort'],
                'approvalPolicy': 'on-request', 'approvalsReviewer': 'user', 'cwd': '/work/codex',
                'sandbox': NATIVE_SANDBOX, 'runtimeWorkspaceRoots': ['/work/codex']}
    if any(state.get(k) != v for k, v in expected.items()):
        raise ValueError('Effective native settings/permissions differ from frozen inputs')
    return {k: state[k] for k in (*expected, 'instructionSources')}


def deadline_watchdog(manifest, deadline, path, state):
    def enforce():
        state['fired'] = True
        identities = [manifest['resources'][role] for role in ('worker', 'relay')]
        try:
            result = subprocess.run(['docker', 'kill', *identities], capture_output=True, text=True,
                                    timeout=remaining(deadline, 2))
            state['termination_exit'] = result.returncode
        except (OSError, subprocess.SubprocessError, TimeoutError) as error:
            state['termination_error'] = type(error).__name__
            state['pending_ids'] = identities
        write_json(path, state)
    timer = threading.Timer(max(0, deadline - time.monotonic() - 2), enforce)
    timer.daemon = True
    timer.start()
    return timer


def report(out, manifest):
    summary = {k: manifest.get(k) for k in ('trial_id', 'attempt_id', 'status', 'session_id', 'session_tree_id', 'utility_base', 'native_error', 'retired')}
    summary['inputs'] = {k: manifest['config'][k] for k in ('comparison_id', 'case_id', 'variant', 'baseline', 'candidate', 'model', 'effort', 'image_id', 'limits')}
    summary['reasoning_context'] = 'all_turns'
    summary['engine'] = manifest.get('engine')
    summary['source_inventory_counts'] = {t: len(manifest.get('installation', {}).get(t, {}).get('source_files', {})) for t in ('codex', 'claude')}
    summary['native_gate'] = manifest.get('native_sandbox', {}).get('passed', False)
    summary['relay_meter'] = manifest.get('relay_meter')
    summary['turns'] = [{k: turn.get(k) for k in ('number', 'kind', 'status', 'thread_id', 'turn_id', 'resumed', 'cancellation_seconds', 'termination_method')} | {
        'response_count': len(turn.get('responses', [])), 'reviewer_roles': [c.get('agentRole') for c in turn.get('child_metadata', [])]
    } for turn in manifest.get('turns', [])]
    summary['assessment'] = 'Native evidence requires external assessment; no complete evaluator or Claude behavior is certified.'
    summary['collector_inputs'] = controller_inputs()
    summary['execution_inputs'] = manifest['controller_inputs']
    write_json(out / 'report.json', summary)
    lines = ['# Native feasibility evidence', '', f"Status: `{summary['status']}`", '', summary['assessment'], '',
             '| Probe | Native status | Correlated replies | Reviewer roles |', '| --- | --- | --- | --- |']
    lines += [f"| {t['kind']} | {t['status']} | {t['response_count']} | {', '.join(r for r in t['reviewer_roles'] if r)} |" for t in summary['turns']]
    if summary['native_error']:
        lines += ['', 'Incomplete: ' + summary['native_error']]
    (out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return manifest


def retire(out, manifest):
    """Explicit exact-ID teardown; retain data, remove credential carriers only."""
    frozen = out / 'inputs.json'
    if not frozen.exists() or digest(frozen) != manifest.get('frozen_inputs_sha256') or json.loads(frozen.read_text())['resources'] != manifest['resources']:
        raise ValueError('Retirement needs intact recorded resource identities')
    ledger_path = out / 'retirement.json'
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {'trial_id': manifest['trial_id'], 'actions': {}}
    for role in ('worker', 'prepare', 'canary', 'relay'):
        if ledger['actions'].get(role, {}).get('completed'):
            continue
        identity = manifest['resources'][role]
        inspected = docker('inspect', identity, timeout=3, check=False)
        if inspected.returncode:
            present = docker('container', 'ls', '-a', '--no-trunc', '--filter', 'id=' + identity, '--format', '{{.ID}}', timeout=3)
            if present.stdout.strip():
                raise ValueError('Retirement ownership readback unavailable')
            ledger['actions'][role] = {'id': identity, 'completed': True, 'readback': 'exact resource absent'}
            write_json(ledger_path, ledger)
            continue
        data = owned(manifest, role)
        identity = data['Id']
        ledger['actions'][role] = {'id': identity, 'action': 'stop-and-remove-credential-carrier' if role == 'relay' else 'stop', 'completed': False}
        write_json(ledger_path, ledger)
        if role == 'relay' and data['State']['Running']:
            meter = docker('exec', identity, 'cat', '/state/meter.json', timeout=3)
            write_json(out / 'retired-meter.json', json.loads(meter.stdout))
        docker('stop', '--time', '0', identity, timeout=3)
        if role == 'relay':
            docker('rm', identity, timeout=3)
        ledger['actions'][role]['completed'] = True
        write_json(ledger_path, ledger)
    manifest['retired'] = True
    write_json(out / 'manifest.json', manifest)
    return manifest


def probe(out, manifest, resume_session=None, stop_after=None):
    if manifest.get('retired'):
        raise ValueError('Retired trials require a fresh trial, not resume')
    if resume_session is None:
        if manifest['status'] != 'native-sandbox-passed' or manifest['turns']:
            raise ValueError('Fresh probes require all gates and no prior launched attempt')
        manifest['probe_deadline'] = time.time() + LIMITS['trial_seconds']
    elif (manifest['status'] != 'probe-checkpoint' or resume_session != manifest.get('session_id')
          or not manifest['turns'] or any(t['status'] != 'completed' for t in manifest['turns'])):
        raise ValueError('Resume requires exact session ID and a verified completed checkpoint')
    if not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('Explicit controller model credential unavailable')
    if [t['kind'] for t in manifest['turns']] != [p[0] for p in PROBES[:len(manifest['turns'])]]:
        raise ValueError('Probe checkpoint order/identity changed')
    try:
        execution_deadline = time.monotonic() + max(0, manifest['probe_deadline'] - time.time())
        for number, (kind, prompt) in list(enumerate(PROBES, 1))[len(manifest['turns']):]:
            if number > LIMITS['turns'] or remaining(execution_deadline, LIMITS['trial_seconds']) < 10:
                raise ValueError('Frozen trial budget exhausted')
            turn_deadline = min(execution_deadline, time.monotonic() + LIMITS['turn_seconds'])
            check_runtime_state(manifest, turn_deadline)
            turn = {'number': number, 'kind': kind, 'status': 'launching'}
            manifest['turns'].append(turn)
            manifest['status'] = 'native-incomplete'
            write_json(out / 'manifest.json', manifest)
            watchdog_state = {'fired': False, 'turn': number}
            timer = deadline_watchdog(manifest, turn_deadline, out / f'turn-{number}-watchdog.json', watchdog_state)
            connection = None
            try:
                connection = Connection(manifest['resources']['worker'], manifest['config']['model'], manifest['config']['effort'],
                                        out / f'turn-{number}.jsonl', deadline=turn_deadline)
                def tighten_deadline(value):
                    nonlocal timer
                    connection.deadline = min(connection.deadline, value)
                    timer.cancel()
                    timer = deadline_watchdog(manifest, connection.deadline, out / f'turn-{number}-watchdog.json', watchdog_state)
                params = {'cwd': '/work/codex', 'model': manifest['config']['model'], 'modelProvider': 'evaluation',
                          'approvalPolicy': 'on-request', 'approvalsReviewer': 'user', 'sandbox': 'workspace-write',
                          'runtimeWorkspaceRoots': ['/work/codex']}
                if manifest.get('session_id'):
                    params['threadId'], params['excludeTurns'] = manifest['session_id'], True
                    state = connection.call('thread/resume', params)
                    if state['thread']['id'] != manifest['session_id']:
                        raise ValueError('Explicit native resume identity mismatch')
                    turn['resumed'] = True
                else:
                    params['allowProviderModelFallback'] = False
                    state = connection.call('thread/start', params)
                    manifest['session_id'] = state['thread']['id']
                    manifest['session_tree_id'] = state['thread']['sessionId']
                if state['thread']['sessionId'] != manifest['session_tree_id']:
                    raise ValueError('Native session-tree identity changed')
                turn['effective'] = check_effective(state, manifest['config'])
                write_json(out / 'manifest.json', manifest)
                relay_control(manifest, time.time() + remaining(turn_deadline, LIMITS['turn_seconds']), turn_deadline)
                observed = probe_turn(connection, manifest['session_id'], kind, prompt, manifest['config']['model'], manifest['config']['effort'],
                                      lambda: heartbeat(manifest, connection.deadline), lambda: relay_control(manifest, 0, connection.deadline),
                                      turn_deadline, tighten_deadline, turn)
                turn.update(observed)
                turn['children'] = sorted(set(turn['children']))
                turn['child_metadata'] = [connection.call('thread/read', {'threadId': identity, 'includeTurns': False})['thread'] for identity in turn['children']]
                if kind in ('plan-reviewer', 'code-reviewer') and not any(child.get('agentRole') == kind for child in turn['child_metadata']):
                    raise ValueError('Actual installed named reviewer role was not observed')
            finally:
                cleanup_deadline = min(turn_deadline, time.monotonic() + 10,
                                       connection.deadline if connection else turn_deadline)
                if connection:
                    connection.deadline = cleanup_deadline
                timer.cancel()
                timer = deadline_watchdog(manifest, cleanup_deadline, out / f'turn-{number}-cleanup-watchdog.json', watchdog_state)
                disarm_ok = False
                cleanup_ok = False
                try:
                    relay_control(manifest, 0, cleanup_deadline)
                    disarm_ok = True
                finally:
                    try:
                        if connection:
                            connection.close()
                        cleanup_ok = True
                    finally:
                        timer.cancel()
                        if not (cleanup_ok and disarm_ok) and not watchdog_state['fired']:
                            fallback_deadline = min(cleanup_deadline, time.monotonic() + 2)
                            fallback = deadline_watchdog(manifest, fallback_deadline,
                                                         out / f'turn-{number}-cleanup-fallback.json', watchdog_state)
                            fallback.join(max(0, fallback_deadline - time.monotonic()))
            if watchdog_state['fired']:
                raise RuntimeError('Absolute deadline enforced; worker/relay stopped or require readback')
            check_runtime_state(manifest, turn_deadline)
            records = collect_session(manifest, out, number, turn_deadline)
            if kind in ('plan-reviewer', 'code-reviewer'):
                children = {r['id']: r for r in records}
                expected_children = [c['id'] for c in turn['child_metadata'] if c.get('agentRole') == kind]
                if not all(identity in children and children[identity]['tool_records'] for identity in expected_children):
                    raise ValueError('Native reviewer own context/action evidence is missing')
            manifest['relay_meter'] = json.loads(docker('exec', manifest['resources']['relay'], 'cat', '/state/meter.json', deadline=turn_deadline).stdout)
            remaining(turn_deadline, 1)
            manifest['status'] = 'native-evidence-pending-assessment' if number == len(PROBES) else 'probe-checkpoint'
            write_json(out / 'manifest.json', manifest)
            if stop_after == kind:
                return manifest
        manifest['status'] = 'native-evidence-pending-assessment'
        return manifest
    except BaseException as error:
        manifest['status'], manifest['native_error'] = 'native-blocked', str(error)
        raise
    finally:
        write_json(out / 'manifest.json', manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'preflight', 'sandbox-gate', 'probe', 'resume', 'report', 'retire'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--session-id', help='Exact recorded parent session; required by resume')
    parser.add_argument('--stop-after', choices=[p[0] for p in PROBES], help='Retain a completed native checkpoint')
    args = parser.parse_args()
    if args.operation == 'prepare':
        if not args.config:
            parser.error('prepare requires explicit --config')
        result = prepare(args.output, json.loads(args.config.read_text()))
    else:
        out, manifest = load(args.output, args.operation not in ('report', 'retire'))
        if args.config and json.loads(args.config.read_text()) != manifest['config']:
            raise ValueError('Continuation configuration differs from frozen inputs')
        if args.operation == 'preflight':
            result = preflight(out, manifest)
        elif args.operation == 'sandbox-gate':
            if manifest['status'] != 'local-preflight-passed-native-sandbox-pending':
                raise ValueError('Native sandbox gate requires passed local preflight')
            for role in ('worker', 'relay'):
                if safe_inspect(owned(manifest, role)) != manifest['deployment'][role]:
                    raise ValueError('Deployment changed before native execution')
            try:
                manifest['native_sandbox'] = sandbox_gate(manifest['resources']['worker'], manifest['config']['model'],
                                                          manifest['config']['effort'], out / 'sandbox.jsonl', manifest['preflight_inputs'])
            except BaseException as error:
                manifest['status'], manifest['native_error'] = 'native-sandbox-blocked', str(error)
                write_json(out / 'manifest.json', manifest)
                raise
            manifest['status'] = 'native-sandbox-passed' if manifest['native_sandbox']['passed'] else 'native-sandbox-blocked'
            write_json(out / 'manifest.json', manifest)
            if manifest['status'] == 'native-sandbox-blocked':
                raise RuntimeError('Native sandbox command failed; model execution remains blocked')
            result = manifest
        elif args.operation in ('probe', 'resume'):
            if args.operation == 'resume' and not args.session_id:
                parser.error('resume requires explicit --session-id')
            result = probe(out, manifest, args.session_id if args.operation == 'resume' else None, args.stop_after)
        elif args.operation == 'retire':
            result = retire(out, manifest)
        else:
            result = report(out, manifest)
    print(json.dumps({k: result[k] for k in ('trial_id', 'attempt_id', 'status')}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Evaluation incomplete: ' + str(error), file=sys.stderr)
        sys.exit(1)
