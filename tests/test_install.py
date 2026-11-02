"""Stock APM delivery checks. Run: python -m unittest discover -s tests -v."""

from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import yaml

from apm_support import isolated_apm_env, require_apm_version


SOURCE = Path(__file__).resolve().parents[1]
SKILLS = {"clarify-scope", "write-spec", "plan-slices", "plan-feature", "deliver-task", "implement-slice", "review-code"}
AGENTS = ("plan-reviewer", "code-reviewer")


class InstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.apm = os.environ.get("APM_BIN") or shutil.which("apm")
        if cls.apm and Path(cls.apm).is_file():
            cls.apm = str(Path(cls.apm).resolve())
        directory = tempfile.TemporaryDirectory(prefix="harness-apm-version-")
        cls.addClassCleanup(directory.cleanup)
        version = require_apm_version(cls.apm, isolated_apm_env(directory.name), SOURCE)
        print(f"Stock APM version: {version}", file=sys.stderr)

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="harness-install-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.apm_env = isolated_apm_env(self.root / "state")
        self.package = self.root / "package"
        self.package.mkdir()
        # Export package inputs, not checkout metadata, environments or task notes.
        shutil.copytree(SOURCE / ".apm", self.package / ".apm")
        shutil.copy2(SOURCE / "apm.yml", self.package / "apm.yml")
        self.consumer = self.create_consumer("consumer")

    def create_consumer(self, name):
        consumer = self.root / name
        consumer.mkdir()
        manifest = {
            "name": "consumer", "version": "0.0.0", "targets": ["codex", "claude"],
            "dependencies": {"apm": [{"path": str(self.package), "alias": "harness"}]},
        }
        (consumer / "apm.yml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        return consumer

    def run_apm(self, *arguments, consumer=None, expected_code=0):
        result = subprocess.run(
            [self.apm, *arguments], cwd=consumer or self.consumer,
            env=self.apm_env,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        return result

    def test_install_repeat_update(self):
        self.assertEqual({p.parent.name for p in (SOURCE / ".apm/skills").glob("*/SKILL.md")}, SKILLS)
        consumer = self.consumer
        unrelated = {
            "consumer-settings.json": '{"keep": true}\n',
            ".codex/config.toml": 'approval_policy = "untrusted"\n',
            ".claude/settings.json": '{"permissions": {"deny": ["Edit"]}}\n',
            ".mcp.json": '{"mcpServers": {}}\n',
            ".codex/agents/local.toml": 'name = "local"\ndescription = "Consumer reviewer"\ndeveloper_instructions = "Inspect only"\n',
            ".claude/agents/local.md": "---\nname: local\ndescription: Consumer reviewer\n---\nInspect only.\n",
            ".claude/rules/local.md": "# Consumer rule\n",
        }
        for target in (".agents", ".claude"):
            unrelated[f"{target}/skills/local/SKILL.md"] = "---\nname: local\ndescription: Consumer skill\n---\nInspect local data.\n"
        for path, content in unrelated.items():
            file = consumer / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content.encode("utf-8"))

        installed = self.run_apm("install", "--only", "apm")
        self.run_apm("compile", "--target", "codex")
        for source in (SOURCE / ".apm/skills").rglob("*"):
            if source.is_file():
                for target in (".agents", ".claude"):
                    actual = consumer / target / "skills" / source.relative_to(SOURCE / ".apm/skills")
                    self.assertEqual(actual.read_bytes(), source.read_bytes())
        self.assertEqual({p.name for p in (SOURCE / ".apm/agents").glob("*.agent.md")}, {f"{name}.agent.md" for name in AGENTS})
        for name in AGENTS:
            agent_source = (SOURCE / f".apm/agents/{name}.agent.md").read_text(encoding="utf-8")
            _, header, body = agent_source.split("---", 2)
            metadata = yaml.safe_load(header)
            native = tomllib.loads((consumer / f".codex/agents/{name}.toml").read_text(encoding="utf-8"))
            self.assertEqual(native["name"], metadata["name"])
            self.assertEqual(native["description"], metadata["description"])
            self.assertEqual(native["developer_instructions"], body.strip())
            for key in ("model", "model_reasoning_effort", "tools"):
                self.assertNotIn(key, native)
            self.assertEqual((consumer / f".claude/agents/{name}.md").read_bytes(), agent_source.encode("utf-8"))
        self.assertIn("'tools'", installed.stdout + installed.stderr)
        _, _, instruction = (SOURCE / ".apm/instructions/harness.instructions.md").read_text(encoding="utf-8").split("---", 2)
        for path in (".claude/rules/harness.md", "AGENTS.md"):
            self.assertIn(instruction.strip(), (consumer / path).read_text(encoding="utf-8"))

        native_paths = [*(p for target in (".agents", ".claude") for p in (consumer / target / "skills").rglob("*") if p.is_file()),
                        *(consumer / f".codex/agents/{name}.toml" for name in AGENTS),
                        *(consumer / f".claude/agents/{name}.md" for name in AGENTS),
                        consumer / ".claude/rules/harness.md"]
        before = {path: path.read_bytes() for path in native_paths}
        self.run_apm("install", "--only", "apm")
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

        # Generated root guidance is regenerated; local text belongs outside it.
        with (consumer / "AGENTS.md").open("a", encoding="utf-8") as file:
            file.write("\nConsumer edit sentinel.\n")
        self.run_apm("compile", "--target", "codex")
        self.assertNotIn("Consumer edit sentinel", (consumer / "AGENTS.md").read_text(encoding="utf-8"))

        skills = [consumer / target / "skills/clarify-scope/SKILL.md" for target in (".agents", ".claude")]
        replaced = [*(consumer / f".codex/agents/{name}.toml" for name in AGENTS),
                    *(consumer / f".claude/agents/{name}.md" for name in AGENTS), consumer / ".claude/rules/harness.md"]
        for path in skills + replaced:
            with path.open("a", encoding="utf-8") as file:
                file.write("\n# Consumer edit sentinel\n")
        for path in ("skills/write-spec/SKILL.md", *(f"agents/{name}.agent.md" for name in AGENTS), "instructions/harness.instructions.md"):
            with (self.package / ".apm" / path).open("a", encoding="utf-8") as file:
                file.write("\nPackage update sentinel.\n")
        updated = self.run_apm("install", "--only", "apm")
        self.assertIn("modified since deployment", updated.stdout + updated.stderr)
        for path in skills:
            self.assertIn("Consumer edit sentinel", path.read_text(encoding="utf-8"))
        for path in replaced:
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("Consumer edit sentinel", content)
            self.assertIn("Package update sentinel", content)
        for target in (".agents", ".claude"):
            self.assertIn("Package update sentinel", (consumer / target / "skills/write-spec/SKILL.md").read_text(encoding="utf-8"))
        self.run_apm("compile", "--target", "codex")
        self.assertIn("Package update sentinel", (consumer / "AGENTS.md").read_text(encoding="utf-8"))
        for path, content in unrelated.items():
            self.assertEqual((consumer / path).read_bytes(), content.encode("utf-8"))

    def test_unmanaged_collisions(self):
        cases = {
            "skills": {f"{target}/skills/clarify-scope/SKILL.md": "# Consumer skill\n" for target in (".agents", ".claude")},
            "agents-and-rule": {
                **{f".codex/agents/{name}.toml": f'name = "{name}"\ndescription = "Consumer reviewer"\ndeveloper_instructions = "Inspect only"\n' for name in AGENTS},
                **{f".claude/agents/{name}.md": f"---\nname: {name}\ndescription: Consumer reviewer\n---\nInspect only.\n" for name in AGENTS},
                ".claude/rules/harness.md": "# Consumer rule\n",
            },
        }
        for name, collisions in cases.items():
            with self.subTest(case=name):
                consumer = self.create_consumer(name)
                for path, content in collisions.items():
                    file = consumer / path
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(content.encode("utf-8"))
                result = self.run_apm("install", "--only", "apm", consumer=consumer, expected_code=1 if name == "skills" else 0)
                self.assertIn("unmanaged" if name == "skills" else "files skipped", result.stdout + result.stderr)
                for path, content in collisions.items():
                    if path == ".claude/rules/harness.md":
                        self.assertNotEqual((consumer / path).read_bytes(), content.encode("utf-8"))
                    else:
                        self.assertEqual((consumer / path).read_bytes(), content.encode("utf-8"))

    def test_existing_root_guidance(self):
        root_guidance = self.consumer / "AGENTS.md"
        prefix, suffix = "# Consumer root guidance\n", "\nConsumer closing note.\n"
        root_guidance.write_bytes(prefix.encode("utf-8"))
        nested = self.consumer / "src/AGENTS.md"
        nested.parent.mkdir()
        nested.write_bytes(b"# Consumer module guidance\n")
        self.run_apm("install", "--only", "apm")
        protected = self.run_apm("compile", "--target", "codex")
        self.assertIn("Protected AGENTS.md", protected.stdout + protected.stderr)
        self.assertEqual(root_guidance.read_bytes(), prefix.encode("utf-8"))
        self.assertFalse((self.consumer / ".codex/config.toml").exists())
        self.assertFalse((self.consumer / ".mcp.json").exists())

        manifest_path = self.consumer / "apm.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["compilation"] = {"agents_md": {"mode": "managed_section"}}
        manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
        root_guidance.write_bytes((prefix + "<!-- apm:start -->\nOld generated content.\n<!-- apm:end -->" + suffix).encode("utf-8"))
        for _ in range(2):
            self.run_apm("compile", "--target", "codex")
            result = root_guidance.read_text(encoding="utf-8")
            self.assertTrue(result.startswith(prefix + "<!-- apm:start -->"))
            self.assertTrue(result.endswith("<!-- apm:end -->" + suffix))
            self.assertEqual(result.count("<!-- apm:start -->"), 1)
            self.assertIn("Hands-on Engineering Harness", result)
            self.assertNotIn("Old generated content", result)
            self.assertEqual(nested.read_bytes(), b"# Consumer module guidance\n")


class FixtureTests(unittest.TestCase):
    def test_local_protocol_and_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="harness-tools-") as directory:
            root = Path(directory)
            state, log, ledger = root / "state.json", root / "calls.jsonl", root / "consumer/.tmp/task/publication.md"
            ledger.parent.mkdir(parents=True)
            state.write_text(json.dumps({"destination": {"team": "FX-TEAM", "project": "FX-PROJECT"},
                                         "canonical_spec": {"id": "SPEC-1", "revision": "C1"}, "issues": []}), encoding="utf-8")
            process = subprocess.Popen([sys.executable, str(SOURCE / "tests/fixtures/linear.py"),
                                        "--state", str(state), "--log", str(log), "--ledger", str(ledger)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8")
            try:
                def call(method, params=None):
                    process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, ensure_ascii=False) + "\n")
                    process.stdin.flush()
                    response = json.loads(process.stdout.readline())
                    self.assertEqual(response["id"], 1)
                    return response["result"]

                self.assertIn("tools", call("initialize")["capabilities"])
                self.assertEqual({t["name"] for t in call("tools/list")["tools"]}, {"inspect_workspace", "save_work_item"})
                data = {"team": "FX-TEAM", "project": "FX-PROJECT", "title": "Parent Grüße 漢字", "description": "Approved payload"}
                parent = call("tools/call", {"name": "save_work_item", "arguments": data})["structuredContent"]
                self.assertEqual(parent["title"], data["title"])
                ledger.write_text("Parent created: " + parent["id"], encoding="utf-8")
                child = call("tools/call", {"name": "save_work_item", "arguments": {**data, "title": "Child", "parentId": parent["id"], "blockedBy": [parent["id"]]}})["structuredContent"]
                self.assertEqual(child["parentId"], parent["id"])
                self.assertEqual(child["blockedBy"], [parent["id"]])
                final = call("tools/call", {"name": "inspect_workspace", "arguments": {}})["structuredContent"]
                self.assertEqual(len(final["issues"]), 2)
                denied = call("tools/call", {"name": "save_work_item", "arguments": {**data, "team": "OTHER"}})
                self.assertTrue(denied["isError"])
                readonly = json.loads(state.read_text(encoding="utf-8"))
                readonly["_fixture"] = {"read_only": True}
                state.write_text(json.dumps(readonly), encoding="utf-8")
                self.assertEqual([t["name"] for t in call("tools/list")["tools"]], ["inspect_workspace"])
                self.assertTrue(call("tools/call", {"name": "save_work_item", "arguments": data})["isError"])
                entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
                self.assertIsNone(entries[0]["ledger_before"])
                self.assertIn(parent["id"], entries[1]["ledger_before"])
                self.assertEqual(len(json.loads(state.read_text(encoding="utf-8"))["issues"]), 2)
            finally:
                process.stdin.close()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()
            self.assertEqual(process.returncode, 0)

    def test_uncertain_create_and_changed_readback(self):
        invoke = runpy.run_path(str(SOURCE / "tests/fixtures/linear.py"))["invoke"]
        with tempfile.TemporaryDirectory(prefix="harness-faults-") as directory:
            state = Path(directory) / "state.json"
            state.write_text(json.dumps({"destination": {"team": "T", "project": "P"}, "issues": [],
                                         "_fixture": {"error_on_create": 1, "mismatch_on_create": 2}}), encoding="utf-8")
            data = {"team": "T", "project": "P", "title": "Approved", "description": "Exact payload"}
            with self.assertRaises(OSError):
                invoke("save_work_item", data, state)
            recovered = invoke("inspect_workspace", {}, state)
            self.assertNotIn("_fixture", recovered)
            self.assertEqual(recovered["issues"][0]["id"], "FX-1")
            self.assertEqual(recovered["issues"][0]["description"], data["description"])
            created = invoke("save_work_item", {**data, "parentId": "FX-1"}, state)
            self.assertEqual(created["description"], data["description"])
            readback = invoke("inspect_workspace", {"id": created["id"]}, state)["issues"][0]
            self.assertNotEqual(readback["description"], created["description"])
            self.assertEqual(len(invoke("inspect_workspace", {}, state)["issues"]), 2)
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["_fixture"], {})


class ApmSupportTests(unittest.TestCase):
    def test_isolated_user_state(self):
        prerequisite = "State-path checks require apm-cli==0.35.0 in this Python; run python -m pip install apm-cli==0.35.0."
        try:
            self.assertEqual(version("apm-cli"), "0.35.0", prerequisite)
        except PackageNotFoundError:
            self.fail(prerequisite)
        with tempfile.TemporaryDirectory(prefix="harness-isolation-") as directory:
            root = Path(directory)
            parent = root / "parent"
            (parent / ".apm").mkdir(parents=True)
            (parent / ".apm/config.json").write_text('{"install_target": "parent-sentinel"}', encoding="utf-8")
            (parent / "cache").mkdir()
            (parent / "cache/sentinel").write_text("keep", encoding="utf-8")
            before = {p.relative_to(parent): p.read_bytes() for p in parent.rglob("*") if p.is_file()}
            base = dict(os.environ)
            for key in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APM_HOME", "APPDATA", "LOCALAPPDATA",
                        "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "APM_CACHE_DIR", "APM_TEMP_DIR", "TMPDIR", "TMP", "TEMP"):
                base[key] = str(parent)
            base["APM_NO_CACHE"] = "1"
            original = base.copy()
            env = isolated_apm_env(root / "isolated", base)
            self.assertEqual(base, original)
            probe = """import json
from pathlib import Path
from apm_cli import config
from apm_cli.cache.paths import get_cache_root
from apm_cli.install.locking import acquire_lifecycle_lock
config.ensure_config_exists()
lock = acquire_lifecycle_lock(timeout=0)
held = lock.is_locked and Path(lock.lock_file).is_file()
lock.release()
print(json.dumps({'home': str(Path.home()), 'config': config.CONFIG_FILE,
                  'cache': str(get_cache_root()), 'lock': str(lock.lock_file),
                  'temp': config.get_apm_temp_dir(),
                  'lock_acquired': held,
                  'settings': config.get_config()}))
"""
            result = subprocess.run([sys.executable, "-c", probe], cwd=root, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            observed = json.loads(result.stdout)
            for key in ("home", "config", "cache", "lock", "temp"):
                self.assertTrue(Path(observed[key]).resolve().is_relative_to((root / "isolated").resolve()), observed)
                if key != "lock":
                    self.assertTrue(Path(observed[key]).exists(), observed)
            self.assertTrue(observed["lock_acquired"], observed)
            self.assertNotEqual(observed["settings"].get("install_target"), "parent-sentinel")
            after = {p.relative_to(parent): p.read_bytes() for p in parent.rglob("*") if p.is_file()}
            self.assertEqual(after, before)

    def test_version_response_validation(self):
        banner = "Agent Package Manager (APM) CLI version "
        for code, output, accepted in ((0, banner + "0.35.0\n", True), (0, banner + "0.36.0\n", False),
                                       (0, banner + "0.35.0rc1\n", False), (0, "Python 3.11.9\n", False),
                                       (1, banner + "0.35.0\n", False)):
            with self.subTest(code=code, output=output), patch("apm_support.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(["apm", "--version"], code, output, "")
                if accepted:
                    self.assertEqual(require_apm_version("apm", {}, SOURCE), "0.35.0")
                else:
                    with self.assertRaisesRegex(RuntimeError, "require 0.35.0.*APM_BIN"):
                        require_apm_version("apm", {}, SOURCE)
                self.assertEqual(run.call_args.args[0], ["apm", "--version"])
                self.assertEqual(run.call_count, 1)

    def test_unavailable_version_check(self):
        with tempfile.TemporaryDirectory(prefix="harness-version-failure-") as directory:
            env = isolated_apm_env(directory)
            with self.assertRaisesRegex(RuntimeError, "unavailable.*APM_BIN"):
                require_apm_version(None, env, directory)
            with self.assertRaisesRegex(RuntimeError, "Cannot check APM version.*APM_BIN"):
                require_apm_version(str(Path(directory) / "missing-apm"), env, directory)
            with patch("apm_support.subprocess.run", side_effect=subprocess.TimeoutExpired("apm --version", 120)):
                with self.assertRaisesRegex(RuntimeError, "Cannot check APM version.*APM_BIN"):
                    require_apm_version("apm", env, directory)


if __name__ == "__main__":
    unittest.main()
