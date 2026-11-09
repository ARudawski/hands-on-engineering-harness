"""Model-free installation of one immutable local harness candidate through APM."""
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tomllib

import yaml
from apm_cli.utils.content_hash import compute_file_hash
from apm_cli.utils.yaml_io import load_yaml, load_yaml_str

from evaluation.signed_in import candidate_selection
from native_support import digest, inventory


def resolve_candidate(run, repository, ref, env):
    """Resolve once in the trusted caller, never execute a ref as shell text."""
    if not isinstance(ref, str) or not ref or '\0' in ref:
        raise ValueError('Invalid candidate reference')
    revision = run(['git', 'rev-parse', '--verify', '--end-of-options', ref+'^{commit}'],
                   cwd=repository, env=env).strip()
    candidate_selection(revision)
    return revision


def export_candidate(run, repository, revision, destination, env):
    candidate_selection(revision)
    if resolve_candidate(run, repository, revision, env) != revision:
        raise RuntimeError('candidate_source_changed')
    tree = run(['git', 'ls-tree', '-rz', '--full-tree', revision], cwd=repository, env=env)
    blobs, names = {}, set()
    for row in tree.rstrip('\0').split('\0'):
        meta, name = row.split('\t', 1)
        mode, kind, oid = meta.split()
        path = PurePosixPath(name)
        if (mode not in ('100644', '100755') or kind != 'blob' or path.is_absolute()
                or path.as_posix() != name or any(p in ('.', '..') or ':' in p for p in path.parts)
                or '\\' in name or name.casefold() in names):
            raise RuntimeError('candidate_format_unsupported')
        blobs[name] = oid
        names.add(name.casefold())
    destination = Path(destination)
    destination.mkdir()
    archive = destination.with_suffix('.tar')
    if archive.exists():
        raise RuntimeError('candidate_source_changed')
    run(['git', 'archive', '--format=tar', '--output='+str(archive), revision], cwd=repository, env=env)
    with tarfile.open(archive) as package:
        members = package.getmembers()
        if (any(not m.isdir() and not m.isfile() for m in members)
                or {m.name for m in members if m.isfile()} != blobs.keys()):
            raise RuntimeError('candidate_format_unsupported')
        package.extractall(destination, filter='data')
    for name, oid in blobs.items():
        content = (destination/name).read_bytes()
        if hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest() != oid:
            raise RuntimeError('candidate_source_changed')
    return {'revision': revision,
            'tree': run(['git', 'rev-parse', revision+'^{tree}'], cwd=repository, env=env).strip(),
            'source': str(destination), 'source_files': inventory(destination)}


def frontmatter(path):
    text = path.read_text(encoding='utf-8')
    match = re.match(r'\A---\s*\n(.*?)\n---\s*\n?', text, re.S)
    if not match:
        return {}, text.strip()
    metadata = load_yaml_str(match[1])
    if not isinstance(metadata, dict) or any(not isinstance(k, str) for k in metadata):
        raise RuntimeError('candidate_format_unsupported')
    return metadata, text[match.end():].strip()


def verify_candidate(consumer, exported, selection):
    """Verify candidate-derived expectations, not an installed-only catalogue."""
    source = Path(exported['source'])
    materialized = consumer/'apm_modules/harness'
    if inventory(source) != exported['source_files'] or inventory(materialized) != exported['source_files']:
        raise RuntimeError('candidate_source_changed')
    expected_skills = {p.relative_to(source/'.apm/skills').as_posix(): digest(p)
                       for p in (source/'.apm/skills').rglob('*') if p.is_file()}
    if inventory(consumer/'.agents/skills') != expected_skills:
        raise RuntimeError('candidate_installation_changed')
    roles, role_paths = {}, set()
    for path in sorted((source/'.apm/agents').rglob('*.agent.md')):
        metadata, body = frontmatter(path)
        name = metadata.get('name', path.name.removesuffix('.agent.md'))
        if (not isinstance(name, str) or not re.fullmatch('[A-Za-z0-9_-]+', name)
                or name in roles or not isinstance(metadata.get('description', ''), str)):
            raise RuntimeError('candidate_format_unsupported')
        expected = {'name': name, 'description': metadata.get('description', ''), 'developer_instructions': body}
        for key, selected in [('model', 'model'), ('model_reasoning_effort', 'effort')]:
            if key in metadata:
                value = metadata[key]
                if (not isinstance(value, str) or not value.strip() or len(value) > 128
                        or any(ord(c) < 32 for c in value)
                        or key == 'model_reasoning_effort' and value not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')):
                    raise RuntimeError('candidate_profile_incompatible')
                expected[key] = metadata[key]
        deployed = consumer/'.codex/agents'/(path.name.removesuffix('.agent.md')+'.toml')
        if deployed in role_paths or tomllib.loads(deployed.read_text(encoding='utf-8')) != expected:
            raise RuntimeError('candidate_installation_changed')
        role_paths.add(deployed)
        roles[name] = {'config_file': str(deployed), 'description': expected['description'], 'sha256': digest(deployed),
                       'untranslated_metadata': sorted(set(metadata)-{'name','description','model','model_reasoning_effort'})}
    if {p for p in (consumer/'.codex/agents').rglob('*') if p.is_file()} != role_paths:
        raise RuntimeError('candidate_installation_changed')
    # Stock APM deploys roles as separate files. Process-local options register
    # those verified roles; an unexpected active config cannot add authority.
    configuration = consumer/'.codex/config.toml'
    if configuration.exists():
        raise RuntimeError('candidate_configuration_unsupported')
    guidance = (consumer/'AGENTS.md').read_text(encoding='utf-8')
    for instruction in (source/'.apm/instructions').rglob('*.instructions.md'):
        _, body = frontmatter(instruction)
        if body and body not in guidance:
            raise RuntimeError('candidate_installation_changed')
    manifest = load_yaml(consumer/'apm.yml')
    expected_manifest = consumer_manifest(source)
    if manifest != expected_manifest or not (consumer/'apm.lock.yaml').is_file():
        raise RuntimeError('candidate_installation_changed')
    lock = load_yaml(consumer/'apm.lock.yaml')
    dependencies = lock.get('dependencies') if isinstance(lock, dict) else None
    deployed = {'.agents/skills/'+p: compute_file_hash(consumer/'.agents/skills'/p) for p in expected_skills}
    deployed.update({p.relative_to(consumer).as_posix(): compute_file_hash(p) for p in role_paths})
    if (not isinstance(dependencies, list) or len(dependencies) != 1
            or not isinstance(dependencies[0], dict)
            or dependencies[0].get('source') != 'local' or dependencies[0].get('alias') != 'harness'
            or dependencies[0].get('local_path') != str(source)
            or dependencies[0].get('deployed_file_hashes', {}) != deployed):
        raise RuntimeError('candidate_installation_changed')
    return {**exported, 'materialized_files': inventory(materialized), 'roles': roles,
            'files': inventory(consumer, root_exclude=('.git', '.tmp')),
            'manifest_sha256': digest(consumer/'apm.yml'), 'lock_sha256': digest(consumer/'apm.lock.yaml'),
            'compiled_guidance_sha256': digest(consumer/'AGENTS.md'),
            'live_child_configuration_verified': False}


def consumer_manifest(source):
    return {'name': 'harness-evaluation', 'version': '0.0.0', 'targets': ['codex'],
            'dependencies': {'apm': [{'path': str(source), 'alias': 'harness'}]}}


def create_runtime_view(full, view, installed):
    """Expose deployed assets, never the complete installed package or its answers."""
    full, view = Path(full), Path(view)
    selected = {p:h for p,h in installed['files'].items()
                if p == 'AGENTS.md' or p.startswith(('.agents/skills/', '.codex/agents/'))}
    if 'AGENTS.md' not in selected:
        raise RuntimeError('candidate_installation_changed')
    view.mkdir()
    for name, expected in selected.items():
        source = full/name
        if (not source.resolve().is_relative_to(full.resolve()) or source.is_symlink()
                or digest(source) != expected):
            raise RuntimeError('candidate_installation_changed')
        target = view/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    roles = {}
    for name, role in installed['roles'].items():
        relative = Path(role['config_file']).relative_to(full).as_posix()
        if relative not in selected or not relative.startswith('.codex/agents/'):
            raise RuntimeError('candidate_installation_changed')
        roles[name] = {**role, 'config_file': str(view/relative)}
    result = {'installation_root': str(full), 'files': selected, 'roles': roles}
    verify_runtime_view(full, view, installed, result)
    return result


def verify_runtime_view(full, view, installed, exposed, *, case_available=False, bootstrap=False):
    full, view = Path(full), Path(view)
    expected = {p:h for p,h in installed['files'].items()
                if p == 'AGENTS.md' or p.startswith(('.agents/skills/', '.codex/agents/'))}
    excluded = ('.tmp',) + (('case',) if case_available else ())
    if bootstrap:
        excluded += ('h12-probe.py', 'h12-inputs.json', 'h12-public')
    if (exposed.get('installation_root') != str(full) or exposed.get('files') != expected
            or inventory(full, root_exclude=('.git', '.tmp')) != installed['files']
            or inventory(view, root_exclude=excluded) != expected):
        raise RuntimeError('candidate_installation_changed')
    roles = {name:{**role, 'config_file':str(view/Path(role['config_file']).relative_to(full))}
             for name,role in installed['roles'].items()}
    if exposed.get('roles') != roles or (view/'apm_modules').exists() or (view/'.codex/config.toml').exists():
        raise RuntimeError('candidate_installation_changed')


def install_candidate(run, apm, consumer, exported, env, selection, version):
    if version not in ('0.35.0', 'Agent Package Manager (APM) CLI version 0.35.0'):
        raise RuntimeError('candidate_apm_unsupported')
    source = Path(exported['source'])
    package = load_yaml(source/'apm.yml')
    if not isinstance(package, dict) or package.get('dependencies', {}).get('apm', []):
        raise RuntimeError('candidate_format_unsupported')
    (consumer/'apm.yml').write_text(yaml.safe_dump(consumer_manifest(source)), encoding='utf-8')
    run([apm, 'install', '--only', 'apm'], cwd=consumer, env=env, timeout=120)
    run([apm, 'compile', '--target', 'codex'], cwd=consumer, env=env, timeout=120)
    result = verify_candidate(consumer, exported, selection)
    result['apm_version'] = version
    return result
