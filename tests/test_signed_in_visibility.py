"""A full trusted installation must not become candidate-readable source."""
from pathlib import Path
import tempfile
import unittest

from evaluation import signed_in_candidate as candidate
from native_support import digest, inventory


class RuntimeView(unittest.TestCase):
    def test_only_deployed_assets_are_copied_and_both_sides_stay_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            full=Path(directory)/'install';full.mkdir()
            files={'AGENTS.md':'Installed instructions', '.agents/skills/read/SKILL.md':'Read the supplied task',
                   '.codex/agents/reviewer.toml':'name="reviewer"\n',
                   'apm_modules/harness/tests/answer.py':'The answer is off by one',
                   'apm.yml':'private installer manifest'}
            for name,body in files.items():
                p=full/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
            role={'config_file':str(full/'.codex/agents/reviewer.toml'),'description':'Review',
                  'sha256':digest(full/'.codex/agents/reviewer.toml')}
            installed={'files':inventory(full),'roles':{'reviewer':role}}
            view=Path(directory)/'work'
            result=candidate.create_runtime_view(full,view,installed)
            self.assertEqual(set(inventory(view)),{'AGENTS.md','.agents/skills/read/SKILL.md','.codex/agents/reviewer.toml'})
            self.assertFalse((view/'apm_modules').exists())
            self.assertEqual(result['roles']['reviewer']['config_file'],str(view/'.codex/agents/reviewer.toml'))
            self.assertEqual(installed['roles']['reviewer']['config_file'],role['config_file'])
            candidate.verify_runtime_view(full,view,installed,result)
            hidden=full/'apm_modules/harness/tests/answer.py';hidden.write_text('changed hidden source')
            with self.assertRaisesRegex(RuntimeError,'candidate_installation_changed'):
                candidate.verify_runtime_view(full,view,installed,result)
            hidden.write_text(files['apm_modules/harness/tests/answer.py'])
            (view/'AGENTS.md').write_text('changed deployed instructions')
            with self.assertRaisesRegex(RuntimeError,'candidate_installation_changed'):
                candidate.verify_runtime_view(full,view,installed,result)


if __name__=='__main__':unittest.main()
