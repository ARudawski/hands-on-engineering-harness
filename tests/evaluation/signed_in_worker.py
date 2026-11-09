"""Public synthetic bootstrap operations; copy into a fresh read-only consumer."""
from pathlib import Path
import base64
import hashlib
import json
import socket
import subprocess
import sys
import time

CHECKS = {'task_write', 'protected_reads', 'protected_writes', 'local_network', 'external_network', 'dns', 'child'}
CASE_READS = {'case-contract':'contract.md', 'case-before':'before.py', 'case-after':'after.py', 'case-plan':'plan.md'}


def fixture_snapshot(base):
    directory=base/'.tmp/native-foundation'
    try:
        hashes={name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in CASE_READS.values()}
        allowed=set(CASE_READS.values())|{'spec.md','index.md'}
        extra=any(p.name not in allowed or p.parent!=directory for p in directory.rglob('*') if p.is_file())
        record=directory/'spec.md'
        attrs=record.lstat() if record.exists() else None
        record_present=attrs is not None and not getattr(attrs,'st_file_attributes',0)&0x400 and not record.is_symlink() and 0<attrs.st_size<=65536
        return {'hashes':hashes,'extra_files':extra,'record_present':record_present}
    except OSError:
        return {'hashes':{},'extra_files':True,'record_present':False}


def inspect_reads(data, base):
    result = {'task_read':False, 'protected_reads':True}
    try:
        result['task_read'] = bool((base/'h12-public/contract.md').read_text(encoding='utf-8'))
    except OSError:
        pass
    for target in data['protected']:
        try:
            Path(target).read_bytes()
            result['protected_reads'] = False
        except OSError:
            pass
    return result


def probe(data, base, child=False, positive=False):
    checks = {}
    if not positive:
        try:
            path = base/'.tmp'/('child-write' if child else 'task-write')
            path.write_text('PUBLIC_ALLOWED', encoding='ascii')
            checks['task_write'] = path.read_text(encoding='ascii') == 'PUBLIC_ALLOWED'
        except OSError:
            checks['task_write'] = False
        for operation in ('reads', 'writes'):
            checks['protected_'+operation] = True
            for target in data['protected']:
                try:
                    path = Path(target)
                    path.read_bytes() if operation == 'reads' else path.write_text('UNEXPECTED_WRITE')
                    checks['protected_'+operation] = False
                except OSError:
                    pass
    for name, host, port in [('local_network', '127.0.0.1', data['port']), ('external_network', '1.1.1.1', 443)]:
        try:
            with socket.create_connection((host, port), timeout=1):
                checks[name] = positive
        except OSError:
            checks[name] = not positive
    try:
        socket.getaddrinfo('example.com', 443)
        checks['dns'] = positive
    except OSError:
        checks['dns'] = not positive
    if not child and not positive:
        try:
            run = subprocess.run([sys.executable, '-I', '-B', __file__, 'child'],
                                 capture_output=True, text=True, timeout=10)
            own = json.loads(run.stdout)
            checks['child'] = (run.returncode == 0 and own.keys() == checks.keys()
                               and all(v is True for v in own.values()))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            checks['child'] = False
    return checks


def main():
    base = Path(__file__).resolve().parent
    data = json.loads((base/'h12-inputs.json').read_text(encoding='utf-8'))
    mode = sys.argv[1] if len(sys.argv) in (2,3) else ''
    if mode == 'fixture-prepare' and len(sys.argv)==3:
        if len(sys.argv[2])>65536:return 1
        files=json.loads(base64.b64decode(sys.argv[2],validate=True))
        if not isinstance(files,dict) or files.keys()!=set(CASE_READS.values()) or not all(isinstance(v,str) and len(v)<=8192 for v in files.values()):
            return 1
        directory=base/'.tmp/native-foundation';directory.mkdir()
        for name,text in files.items():(directory/name).write_text(text,encoding='utf-8',newline='\n')
        print(json.dumps(fixture_snapshot(base)));return 0
    if mode == 'fixture-hashes' and len(sys.argv)==2:
        print(json.dumps(fixture_snapshot(base)));return 0
    if mode in CASE_READS:
        sys.stdout.write((base/'.tmp/native-foundation'/CASE_READS[mode]).read_text(encoding='utf-8'))
        return 0
    if mode == 'inspect':
        result = inspect_reads(data, base)
        print(json.dumps(result))
        return 0 if all(result.values()) else 1
    if mode in ('preflight', 'child', 'positive'):
        result = probe(data, base, mode == 'child', mode == 'positive')
        print(json.dumps(result))
        return 0 if all(result.values()) else 1
    if mode == 'tick':
        until = time.monotonic()+30
        counter = 0
        while time.monotonic() < until:
            counter += 1
            (base/'.tmp/heartbeat').write_text(str(counter), encoding='ascii')
            time.sleep(.2)
        return 0
    if mode == 'heartbeat':
        process = subprocess.Popen([sys.executable, '-I', '-B', __file__, 'tick'])
        (base/'.tmp/heartbeat-pid').write_text(str(process.pid), encoding='ascii')
        return process.wait(timeout=35)
    if mode in ('contract.md', 'plan.md', 'before.txt', 'after.txt'):
        print((base/'h12-public'/mode).read_text(encoding='utf-8'))
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
