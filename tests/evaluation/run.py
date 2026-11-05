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
import time
from uuid import uuid4
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_support import digest, inventory, run_turn
from native import sandbox_gate

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


def command(args, stdin='', timeout=300, check=True):
    p = run_turn(args, stdin, ROOT, timeout)
    if len(p.stdout) + len(p.stderr) > 4 * 1024 * 1024:
        raise RuntimeError('Subprocess output budget exceeded')
    if check and p.returncode:
        raise RuntimeError(f'{args[0]} exited {p.returncode}: {p.stderr[-1500:]} {p.stdout[-1500:]}')
    return p


def docker(*args, stdin='', timeout=300, check=True):
    return command(['docker', *args], stdin, timeout, check)


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


def owned(manifest, role):
    identity = manifest['resources'][role]
    data = json.loads(docker('inspect', identity).stdout)[0]
    if data['Id'] != identity or data['Config']['Labels'].get('har5.trial') != manifest['trial_id'] or data['Config']['Labels'].get('har5.role') != role:
        raise ValueError('Resource identity/ownership mismatch')
    return data


def safe_inspect(data):
    return {k: data[k] for k in ('Id', 'Image', 'Mounts', 'NetworkSettings', 'HostConfig')} | {
        'user': data['Config']['User'], 'labels': data['Config']['Labels'],
    }


def execute_worker(manifest, operation, data, role='worker', timeout=300):
    owned(manifest, role)
    p = docker('exec', '-i', manifest['resources'][role], 'python', '/opt/evaluation/worker.py', operation,
               stdin=json.dumps(data), timeout=timeout)
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
        persist()
        docker('stop', '--time', '1', prep)
        worker = docker('create', '--name', trial + '-worker', '--label', 'har5.role=worker', *common, *volumes,
                        '--security-opt', 'seccomp=' + str(out / 'seccomp.json'),
                        '--network', net, '--dns', '127.0.0.1', config['image_id']).stdout.strip()
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'preflight', 'sandbox-gate', 'report'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    if args.operation == 'prepare':
        if not args.config:
            parser.error('prepare requires explicit --config')
        result = prepare(args.output, json.loads(args.config.read_text()))
    else:
        out, manifest = load(args.output, args.operation != 'report')
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
        else:
            result = manifest
    print(json.dumps({k: result[k] for k in ('trial_id', 'attempt_id', 'status')}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Evaluation incomplete: ' + str(error), file=sys.stderr)
        sys.exit(1)
