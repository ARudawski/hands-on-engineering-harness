"""Candidate provenance checks use local Git/APM only, never a model or account."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apm_support import isolated_apm_env, require_apm_version
from evaluation import signed_in, signed_in_native as native
from evaluation import signed_in_candidate as candidate


class CandidatePreparation(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='h12-candidate-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.env = isolated_apm_env(self.root/'state')
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT='0')
        self.repo = self.root/'repo'
        self.repo.mkdir()
        self.run_command(['git', '-c', 'init.templateDir=', 'init', '-q'], cwd=self.repo)
        (self.repo/'apm.yml').write_text('name: candidate\nversion: 0.0.0\ntargets: [codex]\ndependencies: {apm: []}\n')
        self.write_assets('inspect', ['reviewer'], 'Original candidate')
        self.first = self.commit()

    def run_command(self, command, *, cwd, env=None, timeout=30):
        result = subprocess.run(command, cwd=cwd, env=env or self.env, timeout=timeout,
                                capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('local_fixture_command_failed')
        return result.stdout

    def write_assets(self, skill, roles, body):
        skills = self.repo/'.apm/skills'/skill
        skills.mkdir(parents=True, exist_ok=True)
        (skills/'SKILL.md').write_text(f'---\nname: {skill}\ndescription: Inspect task\n---\n{body}\n')
        agents = self.repo/'.apm/agents'
        agents.mkdir(parents=True, exist_ok=True)
        for role in roles:
            (agents/f'{role}.agent.md').write_text(f'---\nname: {role}\ndescription: Assess task\n---\n{body}\n')
        instructions = self.repo/'.apm/instructions'
        instructions.mkdir(parents=True, exist_ok=True)
        (instructions/'task.instructions.md').write_text('---\napplyTo: "**"\n---\n'+body+'\n')

    def commit(self):
        self.run_command(['git', 'add', '.'], cwd=self.repo)
        self.run_command(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                  '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Temporary fixture'], cwd=self.repo)
        return self.run_command(['git', 'rev-parse', 'HEAD'], cwd=self.repo).strip()

    def test_full_commit_export_ignores_dirty_worktree_and_binds_identity(self):
        (self.repo/'apm.yml').write_text('DIRTY WORKTREE')
        revision = candidate.resolve_candidate(self.run_command, self.repo, 'HEAD', self.env)
        exported = candidate.export_candidate(self.run_command, self.repo, revision, self.root/'source', self.env)
        self.assertEqual(exported['revision'], self.first)
        self.assertIn('.apm/skills/inspect/SKILL.md', exported['source_files'])
        self.assertTrue((self.root/'source/apm.yml').read_text().startswith('name: candidate'))
        with self.assertRaises((ValueError, RuntimeError)):
            candidate.export_candidate(self.run_command, self.repo, '0'*40, self.root/'missing', self.env)

    def test_request_freezes_candidate_and_leaves_legacy_requests_unchanged(self):
        store = signed_in.RequestStore(self.root/'requests')
        origin, request = str(uuid4()), str(uuid4())
        result = store.submit(origin, request, 'native-foundation', 120,
                              candidate_revision=self.first, candidate_ref='feature/example')
        self.assertEqual(result['revision'], self.first)
        self.assertEqual(result['candidate_ref'], 'feature/example')
        again = store.submit(origin, request, 'native-foundation', 120,
                             candidate_revision=self.first, candidate_ref='feature/example')
        self.assertEqual(result['attempt_id'], again['attempt_id'])
        for revision in [None, '1'*40]:
            with self.assertRaises(ValueError):
                store.submit(origin, request, 'native-foundation', 120, candidate_revision=revision)
        legacy = store.submit(origin, str(uuid4()), 'native-foundation', 120)
        self.assertEqual(legacy['revision'], signed_in.REVISION)
        self.assertNotIn('candidate_revision', legacy)
        with self.assertRaises(ValueError):
            store.submit(origin, str(uuid4()), 'native-foundation', 120, candidate_revision='HEAD')

    def test_candidate_cannot_enter_scripted_diagnostics_or_change_native_binding(self):
        payload = {'request_id': str(uuid4()), 'case': 'native-foundation', 'seconds': 120,
                   'candidate_revision': self.first, 'model': 'gpt-6-luna', 'effort': 'low'}
        with patch.object(native, 'RequestStore') as factory:
            with self.assertRaises(ValueError):
                native.run_native(payload, mode='diagnose')
            with self.assertRaises(ValueError):
                native.run_native({**payload, 'effort': 'medium'}, mode='prepare')
            with self.assertRaises(ValueError):
                native.run_native({**payload, 'candidate_revision': None}, mode='prepare')
            factory.assert_not_called()
        store = signed_in.RequestStore(self.root/'requests')
        origin = str(uuid4())
        store.submit(origin, payload['request_id'], payload['case'], payload['seconds'],
                     candidate_revision=self.first)
        native.bind_mode(store, origin, payload['request_id'], 'prepare',
                         {'model': 'gpt-6-luna', 'effort': 'low'}, purpose='candidate-prepare')
        with self.assertRaises(ValueError):
            native.bind_mode(store, origin, payload['request_id'], 'prepare')

    def test_stock_apm_preserves_role_model_variation(self):
        role = self.repo/'.apm/agents/reviewer.agent.md'
        role.write_text(role.read_text().replace('description: Assess task',
                        'description: Assess task\nmodel: gpt-6.1-sol\nmodel_reasoning_effort: high'))
        revision = self.commit()
        apm = os.environ.get('APM_BIN') or shutil.which('apm')
        version = require_apm_version(apm, self.env, self.repo)
        exported = candidate.export_candidate(self.run_command, self.repo, revision, self.root/'varied', self.env)
        consumer = self.root/'varied-consumer'; consumer.mkdir()
        receipt = candidate.install_candidate(self.run_command, apm, consumer, exported, self.env,
                                              {'model':'gpt-6-luna','effort':'low'}, version)
        self.assertIn('reviewer', receipt['roles'])
        deployed = (consumer/'.codex/agents/reviewer.toml').read_text()
        self.assertIn('gpt-6.1-sol', deployed)
        self.assertIn('high', deployed)

    def test_stock_apm_accepts_changed_assets_and_rejects_mismatched_installation(self):
        apm = os.environ.get('APM_BIN') or shutil.which('apm')
        version = require_apm_version(apm, self.env, self.repo)
        for number in range(2):
            if number:
                (self.repo/'.apm/skills/inspect/SKILL.md').unlink()
                (self.repo/'.apm/agents/reviewer.agent.md').unlink()
                self.write_assets('investigate', ['specialist', 'second_opinion'], 'Changed candidate')
                self.write_assets('verify', [], 'Additional skill')
                self.commit()
            revision = candidate.resolve_candidate(self.run_command, self.repo, 'HEAD', self.env)
            exported = candidate.export_candidate(self.run_command, self.repo, revision, self.root/f'source-{number}', self.env)
            consumer = self.root/f'consumer-{number}'
            consumer.mkdir()
            receipt = candidate.install_candidate(self.run_command, apm, consumer, exported, self.env,
                {'model': 'gpt-6-luna', 'effort': 'low'}, version)
            self.assertEqual(set(receipt['roles']), {'reviewer'} if number == 0 else {'specialist', 'second_opinion'})
            self.assertEqual(receipt['revision'], revision)
            self.assertEqual(receipt['source_files'], receipt['materialized_files'])
            self.assertIn('AGENTS.md', receipt['files'])
            self.assertIn('apm.lock.yaml', receipt['files'])
            view=self.root/f'work-{number}'
            exposed=candidate.create_runtime_view(consumer,view,receipt)
            candidate.verify_runtime_view(consumer,view,receipt,exposed)
            self.assertFalse((view/'apm_modules').exists())
            self.assertFalse((view/'apm.yml').exists())
            self.assertEqual((view/'AGENTS.md').read_bytes(),(consumer/'AGENTS.md').read_bytes())
            config = consumer/'.codex/agents'/('reviewer.toml' if number == 0 else 'specialist.toml')
            original = config.read_bytes()
            for content in [original+b'permissions = "unsafe"\n', original.replace(b'candidate', b'forged')]:
                config.write_bytes(content)
                with self.assertRaises(RuntimeError):
                    candidate.verify_candidate(consumer, exported, {'model': 'gpt-6-luna', 'effort': 'low'})
            config.write_bytes(original)
            extra = consumer/'.codex/agents/foreign.toml'
            extra.write_text('name="foreign"\n')
            with self.assertRaises(RuntimeError):
                candidate.verify_candidate(consumer, exported, {'model': 'gpt-6-luna', 'effort': 'low'})
            extra.unlink()
            lock = consumer/'apm.lock.yaml'
            original_lock = lock.read_bytes()
            lock.write_text('dependencies: []\n')
            with self.assertRaises(RuntimeError):
                candidate.verify_candidate(consumer, exported, {'model': 'gpt-6-luna', 'effort': 'low'})
            lock.write_bytes(original_lock)
            materialized = consumer/'apm_modules/harness/apm.yml'
            materialized.write_text('MISMATCH')
            with self.assertRaises(RuntimeError):
                candidate.verify_candidate(consumer, exported, {'model': 'gpt-6-luna', 'effort': 'low'})


if __name__ == '__main__':
    unittest.main()
