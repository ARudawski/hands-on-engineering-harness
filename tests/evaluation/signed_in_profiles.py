"""Trusted profile metadata, never a credential reader or a login mechanism."""
import hashlib
import json
from pathlib import Path
import re

from evaluation.signed_in import identity


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_reference(ref):
    if (not isinstance(ref, dict) or ref.keys() != {'profile_id', 'reference_sha256'}
            or not isinstance(ref['reference_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', ref['reference_sha256'])):
        raise ValueError('profile_rejected')
    identity(ref['profile_id'])


def profile_home(value, root):
    home = Path(value)
    base = Path(root).resolve().parents[1] / '.tmp'
    if (not home.is_absolute() or home.resolve() != home or home.parent.parent != base
            or not re.fullmatch('h12-n-[0-9a-f]{8}', home.parent.name)
            or not home.name.startswith('auth-profile-') or not home.is_dir()):
        raise ValueError('profile_rejected')
    identity(home.name.removeprefix('auth-profile-'))
    for name in ('.env', 'config.toml', 'AGENTS.md', 'requirements.toml'):
        path = home / name
        if path.exists() or path.is_symlink():
            raise ValueError('profile_rejected')
    auth = home / 'auth.json'
    if auth.is_symlink() or auth.resolve() != auth or not auth.is_file():
        raise ValueError('profile_rejected')
    stat = home.stat()
    if stat.st_ino <= 0:
        raise ValueError('profile_rejected')
    return home, [stat.st_dev, stat.st_ino]


def profile_table(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS profiles '
                       '(profile_id TEXT PRIMARY KEY, origin TEXT NOT NULL, state TEXT NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS profile_handoffs '
                       '(profile_id TEXT NOT NULL, origin TEXT NOT NULL, state TEXT NOT NULL, '
                       'PRIMARY KEY (profile_id, origin))')


def authorize_profile_handoff(store, source_origin, target_origin, expected, *, root):
    """Trusted controller only: grant explicitly authorized reuse, retaining ownership.

    Never exposed in native stdin. An existing setup and exact source reference
    are required; this neither registers a home nor transfers credentials.
    """
    try:
        identity(source_origin)
        identity(target_origin)
        validate_reference(expected)
        _, actual = resolve_profile(store, source_origin, expected['profile_id'], root=root)
        if actual != expected or source_origin == target_origin:
            raise ValueError()
        grant = {'origin': target_origin, 'source_origin': source_origin, 'source_reference': expected}
        with store.transaction() as connection:
            profile_table(connection)
            owner = connection.execute('SELECT origin,state FROM profiles WHERE profile_id=?',
                                       (expected['profile_id'],)).fetchone()
            if not owner or owner[0] != source_origin or checksum(json.loads(owner[1])) != expected['reference_sha256']:
                raise ValueError()
            row = connection.execute('SELECT state FROM profile_handoffs WHERE profile_id=? AND origin=?',
                                     (expected['profile_id'], target_origin)).fetchone()
            if row and json.loads(row[0]) != grant:
                raise ValueError()
            if not row:
                connection.execute('INSERT INTO profile_handoffs VALUES (?,?,?)',
                                   (expected['profile_id'], target_origin, json.dumps(grant)))
        return {'profile_id': expected['profile_id'], 'reference_sha256': checksum(grant)}
    except (ValueError, RuntimeError, TypeError, KeyError, AttributeError, OSError):
        raise ValueError('profile_rejected') from None


def register_profile(store, origin, setup, setup_sha256, *, root):
    """Only the trusted invoking controller registers completed setup evidence.

    No stdin path registration exists. These facts are references to previously
    verified setup, not independent account/isolation proof. Normal token refresh
    may replace auth.json: inspect its presence/type, never its contents/hash.
    """
    try:
        identity(origin)
        profile_id = identity(setup['operation_id'])
        if (setup.get('status') != 'authenticated_only' or setup.get('account_type') != 'chatgpt'
                or setup.get('cleanup_verified') is not True or setup.get('credentials_copied') is not False
                or any(type(setup.get(k)) is not int or setup[k] != 0 for k in ('model_turns', 'evaluated_requests'))
                or not isinstance(setup_sha256, str) or not re.fullmatch('[0-9a-f]{64}', setup_sha256)):
            raise ValueError()
        cleanup = setup['job_cleanup']
        if (cleanup.get('job_empty') is not True or cleanup.get('within_budget') is not True
                or cleanup.get('closure_failed') is not False or cleanup.get('termination_failed') is not False):
            raise ValueError()
        home, directory_id = profile_home(setup['home'], root)
        state = {'profile_id': profile_id, 'origin': origin, 'home': str(home),
                 'directory_id': directory_id, 'setup_sha256': setup_sha256}
        with store.transaction() as connection:
            profile_table(connection)
            row = connection.execute('SELECT origin,state FROM profiles WHERE profile_id=?', (profile_id,)).fetchone()
            if row:
                if row[0] != origin or json.loads(row[1]) != state:
                    raise ValueError()
            else:
                connection.execute('INSERT INTO profiles VALUES (?,?,?)', (profile_id, origin, json.dumps(state)))
        return {'profile_id': profile_id, 'reference_sha256': checksum(state)}
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        raise ValueError('profile_rejected') from None


def resolve_profile(store, origin, profile_id, *, root):
    try:
        identity(origin)
        identity(profile_id)
        with store.transaction() as connection:
            profile_table(connection)
            row = connection.execute('SELECT origin,state FROM profiles WHERE profile_id=?', (profile_id,)).fetchone()
            grant_row = connection.execute('SELECT state FROM profile_handoffs WHERE profile_id=? AND origin=?',
                                           (profile_id, origin)).fetchone() if row and row[0] != origin else None
        if not row:
            raise ValueError()
        state = json.loads(row[1])
        if (state.keys() != {'profile_id', 'origin', 'home', 'directory_id', 'setup_sha256'}
                or state['profile_id'] != profile_id or state['origin'] != row[0]
                or not re.fullmatch('[0-9a-f]{64}', state['setup_sha256'])):
            raise ValueError()
        home, directory_id = profile_home(state['home'], root)
        if directory_id != state['directory_id']:
            raise ValueError()
        reference_state = state
        if row[0] != origin:
            expected_grant = {'origin': origin, 'source_origin': row[0],
                              'source_reference': {'profile_id': profile_id, 'reference_sha256': checksum(state)}}
            if not grant_row or json.loads(grant_row[0]) != expected_grant:
                raise ValueError()
            reference_state = expected_grant
        return home, {'profile_id': profile_id, 'reference_sha256': checksum(reference_state)}
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        raise RuntimeError('profile_binding_changed') from None


def require_binding(store, origin, request_id, expected, *, root, require_launch=False, root_thread=None):
    validate_reference(expected)
    _, actual = resolve_profile(store, origin, expected['profile_id'], root=root)
    rejected = False
    with store.request(origin, request_id) as state:
        if (not state['admission_open'] or actual != expected or state.get('native_profile') != expected
                or require_launch and (state.get('native_mode') != 'diagnose' or not state['launch_claimed']
                    or not root_thread or root_thread != state.get('native_root'))):
            rejected = True
    if rejected:
        raise RuntimeError('profile_binding_changed')


def bind_root(store, origin, request_id, root_uuid, profile):
    identity(root_uuid)
    rejected = False
    with store.request(origin, request_id) as state:
        if (not state['admission_open'] or 'native_mode' not in state or state.get('native_profile') != profile
                or state.get('native_root', root_uuid) != root_uuid):
            rejected = True
        else:
            state['native_root'] = root_uuid
    if rejected:
        raise RuntimeError('profile_binding_changed')


def checkpoint_binding(state, checkpoint):
    """Tie offline intents to the actual native request, without enabling wire IO."""
    if 'native_mode' not in state:
        if any(k in state for k in ('native_profile', 'native_root')) or 'native_profile' in checkpoint:
            raise ValueError('profile_rejected')
        return  # Independent fabricated-event protocol fixtures have no native context.
    profile = state.get('native_profile')
    validate_reference(profile)
    if (checkpoint['binding']['root'] != state.get('native_root')
            or checkpoint.get('native_profile', profile) != profile):
        raise ValueError('profile_rejected')
    checkpoint['native_profile'] = dict(profile)
