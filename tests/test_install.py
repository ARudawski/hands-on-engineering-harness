"""Stock APM delivery checks. Run: python -m unittest discover -s tests -v."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

import yaml


SOURCE = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def test_fresh_consumer_install(self):
        apm = os.environ.get("APM_BIN") or shutil.which("apm")
        self.assertIsNotNone(apm, "Install apm-cli==0.35.0 or set APM_BIN")
        # Export package inputs, not checkout metadata, environments or task notes.
        with tempfile.TemporaryDirectory(prefix="harness-install-") as directory:
            root = Path(directory)
            package, consumer = root / "package", root / "consumer"
            package.mkdir()
            consumer.mkdir()
            shutil.copytree(SOURCE / ".apm", package / ".apm")
            shutil.copy2(SOURCE / "apm.yml", package / "apm.yml")
            manifest = {
                "name": "consumer",
                "version": "0.0.0",
                "targets": ["codex", "claude"],
                "dependencies": {"apm": [{"path": str(package), "alias": "harness"}]},
            }
            (consumer / "apm.yml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
            untouched = consumer / "consumer-settings.json"
            untouched.write_text('{"keep": true}\n', encoding="utf-8")
            env = {**os.environ, "APM_HOME": str(root / "apm-home")}

            def run(*arguments):
                result = subprocess.run(
                    [apm, *arguments], cwd=consumer, env=env,
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=120,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result

            installed = run("install", "--only", "apm")
            run("compile", "--target", "codex")
            for source in (SOURCE / ".apm/skills").iterdir():
                with self.subTest(skill=source.name):
                    for target in (".agents", ".claude"):
                        actual = consumer / target / "skills" / source.name / "SKILL.md"
                        self.assertEqual(actual.read_bytes(), (source / "SKILL.md").read_bytes())

            native = tomllib.loads(
                (consumer / ".codex/agents/plan-reviewer.toml").read_text(encoding="utf-8")
            )
            agent_source = (SOURCE / ".apm/agents/plan-reviewer.agent.md").read_text(encoding="utf-8")
            _, header, body = agent_source.split("---", 2)
            metadata = yaml.safe_load(header)
            self.assertEqual(native["name"], metadata["name"])
            self.assertEqual(native["description"], metadata["description"])
            self.assertEqual(native["developer_instructions"], body.strip())
            self.assertNotIn("model", native)
            self.assertNotIn("model_reasoning_effort", native)
            self.assertNotIn("tools", native)
            self.assertIn("'tools'", installed.stdout + installed.stderr)

            claude_agent = consumer / ".claude/agents/plan-reviewer.md"
            self.assertEqual(claude_agent.read_bytes(), agent_source.encode("utf-8"))
            rules = (consumer / ".claude/rules/harness.md").read_text(encoding="utf-8")
            _, _, instruction = (SOURCE / ".apm/instructions/harness.instructions.md").read_text(encoding="utf-8").split("---", 2)
            self.assertIn(instruction.strip(), rules)
            self.assertIn(instruction.strip(), (consumer / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads(untouched.read_text(encoding="utf-8")), {"keep": True})
            self.assertFalse((consumer / ".codex/config.toml").exists())
            self.assertFalse((consumer / ".mcp.json").exists())


if __name__ == "__main__":
    unittest.main()
