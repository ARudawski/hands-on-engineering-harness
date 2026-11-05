"""Public, unprivileged worker operations; authoritative checks stay outside."""

import hashlib
import ctypes
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tomllib

from apm_support import isolated_apm_env, require_apm_version
from native_support import digest, inventory


def install(inputs):
    Path('/home/agent/.codex').mkdir(exist_ok=True)
    env = isolated_apm_env('/home/agent/apm-state')
    require_apm_version('/usr/local/bin/apm', env, '/work')
    result = {}
    for target in ('codex', 'claude'):
        consumer = Path('/work') / target
        consumer.mkdir()
        commands = [['apm', 'install', 'ARudawski/hands-on-engineering-harness#' + inputs['revision'], '--target', target]]
        if target == 'codex':
            commands.append(['apm', 'compile', '--target', 'codex'])
        logs = []
        for command in commands:
            p = subprocess.run(command, cwd=consumer, env=env, capture_output=True, text=True, timeout=300)
            logs.append({'command': command, 'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
            if p.returncode:
                raise RuntimeError(json.dumps(logs))
        source = consumer / 'apm_modules/ARudawski/hands-on-engineering-harness'
        source_files = inventory(source)
        if any(source_files.get(p) != h for p, h in inputs['source_files'].items()):
            raise RuntimeError('Full materialized repository differs from pinned source inventory')
        if not source_files:
            raise RuntimeError('Empty materialization')
        skill_root = '.agents' if target == 'codex' else '.claude'
        skills = list((source / '.apm/skills').rglob('SKILL.md'))
        if len(skills) != 7:
            raise RuntimeError('Expected seven installed skills')
        for p in (source / '.apm/skills').rglob('*'):
            if p.is_file() and digest(consumer / skill_root / 'skills' / p.relative_to(source / '.apm/skills')) != digest(p):
                raise RuntimeError('Deployed skill/reference mismatch')
        for name in ('plan-reviewer', 'code-reviewer'):
            definition = source / f'.apm/agents/{name}.agent.md'
            if target == 'codex':
                native = tomllib.loads((consumer / f'.codex/agents/{name}.toml').read_text())
                if native['name'] != name or native['developer_instructions'] != definition.read_text().split('---', 2)[2].strip():
                    raise RuntimeError('Native reviewer mismatch')
            elif (consumer / f'.claude/agents/{name}.md').read_bytes() != definition.read_bytes():
                raise RuntimeError('Claude reviewer mismatch')
        guidance = (source / '.apm/instructions/harness.instructions.md').read_text().split('---', 2)[2].strip()
        if guidance not in (consumer / ('AGENTS.md' if target == 'codex' else '.claude/rules/harness.md')).read_text():
            raise RuntimeError('Guidance missing')
        result[target] = {'commands': logs, 'files': inventory(consumer), 'source_files': source_files}
    result['versions'] = {name: subprocess.check_output(command, text=True, timeout=15).strip() for name, command in {
        'codex': ['codex', '--version'], 'python': ['python', '--version'], 'git': ['git', '--version'], 'apm': ['apm', '--version'],
    }.items()}
    return result


def preflight(inputs):
    checks = {}
    path = Path('/work/codex/.tmp/positive-control')
    path.parent.mkdir(exist_ok=True)
    path.write_text(inputs['trial'])
    checks['legitimate_write'] = path.read_text() == inputs['trial']
    for value in inputs['forbidden_reads']:
        try:
            Path(value).read_bytes()
            checks['read:' + value] = False
        except (OSError, ValueError):
            checks['read:' + value] = True
    for value in ['/etc/har5-forbidden', '/opt/evaluation/har5-forbidden', *inputs.get('forbidden_writes', [])]:
        try:
            Path(value).write_text('unauthorized')
            checks['write:' + value] = False
        except OSError:
            checks['write:' + value] = True
    for host, port in inputs['forbidden_network']:
        try:
            with socket.create_connection((host, port), timeout=1):
                checks[f'network:{host}:{port}'] = False
        except OSError:
            checks[f'network:{host}:{port}'] = True
    try:
        socket.getaddrinfo(inputs['dns_canary'], 443)
        checks['external_dns'] = False
    except OSError:
        checks['external_dns'] = True
    for path in ['/var/run/docker.sock', '/run/docker.sock']:
        checks['control:' + path] = not Path(path).exists()
    checks['unprivileged'] = os.getuid() == 10001
    checks['credential_absent'] = not os.environ.get('OPENAI_API_KEY') and not (Path.home() / '.codex/auth.json').exists()
    checks['no_global_context'] = not Path('/home/agent/.codex/memories_v2').exists()
    mount_point = Path('/tmp/har5-mount-control')
    mount_point.mkdir(exist_ok=True)
    libc = ctypes.CDLL(None, use_errno=True)
    checks['outer_mount_denied'] = libc.mount(b'tmpfs', str(mount_point).encode(), b'tmpfs', 0, None) == -1
    if not checks['outer_mount_denied']:
        libc.umount2(str(mount_point).encode(), 0)
    try:
        with open('/proc/1/ns/mnt') as namespace:
            checks['setns_denied'] = libc.setns(namespace.fileno(), 0) == -1
    except OSError:
        checks['setns_denied'] = True
    link = Path('/work/codex/.tmp/protected-link')
    if not link.is_symlink():
        link.symlink_to(inputs['forbidden_reads'][0])
    if os.readlink(link) != inputs['forbidden_reads'][0]:
        raise ValueError('Protected link probe target changed')
    try:
        link.read_bytes()
        checks['link_read_denied'] = False
    except OSError:
        checks['link_read_denied'] = True
    if inputs.get('child', True):
        child = subprocess.run([sys.executable, __file__, 'preflight'], input=json.dumps({**inputs, 'child': False}), capture_output=True, text=True, timeout=30)
        checks['child'] = child.returncode == 0 and all(json.loads(child.stdout).values())
    return checks


def relay_checks(inputs):
    base = {'model': inputs['model'], 'reasoning': {'effort': inputs['effort']}, 'store': False, 'stream': True, 'input': []}
    cases = {'closed': (base, 'admission closed'), 'stored': ({**base, 'store': True}, 'only non-stored streaming responses'),
             'hosted': ({**base, 'tools': [{'type': 'web_search'}]}, 'hosted/unsupported tools'),
             'previous': ({**base, 'previous_response_id': 'unrelated'}, 'unsupported request fields'),
             'model': ({**base, 'model': 'foreign'}, 'model/reasoning drift'),
             'files': ({**base, 'input': [{'type': 'item_reference', 'id': 'unrelated'}]}, 'stored/media input reference')}
    checks = {}
    for name, (value, reason) in cases.items():
        conn = http.client.HTTPConnection('model-relay', 8080, timeout=3)
        conn.request('POST', '/v1/responses', json.dumps(value), {'Content-Type': 'application/json'})
        r = conn.getresponse()
        checks[name] = r.status == 403 and json.loads(r.read()).get('error') == reason
        conn.close()
    conn = http.client.HTTPConnection('model-relay', 8080, timeout=3)
    conn.request('GET', '/health')
    response = conn.getresponse()
    checks['legitimate_route'] = response.status == 200 and json.loads(response.read())['trial'] == inputs['trial']
    conn.close()
    if inputs.get('child', True):
        child = subprocess.run([sys.executable, __file__, 'relay-checks', json.dumps({**inputs, 'child': False})],
                               capture_output=True, text=True, timeout=30)
        checks['child'] = child.returncode == 0 and all(json.loads(child.stdout).values())
    return checks


if __name__ == '__main__':
    command = sys.argv[1]
    values = json.loads(sys.argv[2]) if len(sys.argv) > 2 else json.load(sys.stdin)
    operations = {'install': install, 'preflight': preflight, 'relay-checks': relay_checks,
                  'inventory': lambda _: {t: inventory(Path('/work') / t) for t in ('codex', 'claude')}}
    result = operations[command](values)
    print(json.dumps(result))
    if command in {'preflight', 'relay-checks'} and not all(result.values()):
        sys.exit(1)
