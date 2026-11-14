"""Model-free driver safeguards. Run explicitly: python tests/smoke/check_driver.py."""

import json
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import run


class DriverGuards(unittest.TestCase):
    def test_event_noise_and_invalid_shapes(self):
        valid = '{"type":"thread.started","thread_id":"parent"}\n{"type":"turn.completed"}\n'
        events, notes, errors = run.parse_events('CLI warning\n' + valid)
        self.assertEqual([e["type"] for e in events], ["thread.started", "turn.completed"])
        self.assertEqual(notes, 1)
        self.assertEqual(errors, [])
        for bad in ('[]', 'null', '{"type":"item.completed","item":null}', '{"type":'):
            with self.subTest(bad=bad):
                events, _, errors = run.parse_events(bad + '\n' + valid)
                self.assertEqual(events[-1]["type"], "turn.completed")
                self.assertTrue(errors)

    def test_generated_bytecode_and_source_changes(self):
        before = {"export.py": "original"}
        after = {**before, "__pycache__/export.cpython-311.pyc": "derived"}
        changes = run.fixture_changes(before, after)
        self.assertEqual(changes["generated_bytecode"], {"__pycache__/export.cpython-311.pyc": "derived"})
        self.assertEqual(changes["added"], [])
        after.update({"export.py": "modified", "__pycache__/notes.txt": "not bytecode"})
        changes = run.fixture_changes(before, after)
        self.assertEqual(changes["modified"], ["export.py"])
        self.assertEqual(changes["added"], ["__pycache__/notes.txt"])

    def test_timeout_terminates_pipe_inheriting_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "tree.py"
            # A descendant retains stdout and writes a heartbeat until terminated.
            script.write_text("import pathlib, subprocess, sys, time\n"
                              "if len(sys.argv) == 1:\n"
                              " p = subprocess.Popen([sys.executable, __file__, 'child'])\n"
                              " pathlib.Path('pid').write_text(str(p.pid))\n"
                              " print('ready', flush=True)\n"
                              " time.sleep(60)\n"
                              "else:\n"
                              " deadline = time.monotonic() + 15\n"
                              " while time.monotonic() < deadline:\n"
                              "  pathlib.Path('heartbeat').write_text(str(time.time_ns()))\n"
                              "  time.sleep(0.05)\n", encoding="utf-8")
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                run.run_turn([sys.executable, str(script)], "", root, timeout=2)
            self.assertLess(time.monotonic() - started, 12)
            self.assertIn("ready", raised.exception.stdout)
            heartbeat = (root / "heartbeat").read_text(encoding="utf-8")
            time.sleep(0.2)
            self.assertEqual((root / "heartbeat").read_text(encoding="utf-8"), heartbeat)

    def test_native_input_and_git_ceiling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, "-X", "utf8", "-c", "import os,sys; print(sys.stdin.read()); print(os.environ['GIT_CEILING_DIRECTORIES'])"]
            result = run.run_turn(command, "Grüße 漢字", root, timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.splitlines(), ["Grüße 漢字", str(root.resolve().parent)])

    def test_execution_diagnostics_and_no_git_resume(self):
        for mode in ("noise-bytecode", "invalid-event", "source-change"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                out = Path(directory).resolve()
                consumer = out / "consumer"
                consumer.mkdir()
                source = consumer / "export.py"
                source.write_text("value = 1\n", encoding="utf-8")
                manifest = {"case": "clarify-scope", "output_dir": str(out), "inputs": run.inputs("clarify-scope"),
                            "runtime_installed": {}, "baseline": run.inventory(consumer), "turns": [], "session_id": None, "status": "prepared"}
                def model(command, *args):
                    self.assertIn("--skip-git-repo-check", command)
                    if mode == "source-change":
                        source.write_text("value = 2\n", encoding="utf-8")
                    (consumer / "__pycache__").mkdir(exist_ok=True)
                    (consumer / "__pycache__/export.pyc").write_bytes(b"derived")
                    noise = '[]\n' if mode == "invalid-event" else 'CLI warning\n'
                    return subprocess.CompletedProcess(command, 0, noise + '{"type":"thread.started","thread_id":"parent"}\n{"type":"turn.completed"}\n', "")
                with patch.object(run.shutil, "which", return_value="codex"), patch.object(run.subprocess, "check_output", return_value="fixture-version"), patch.object(run, "run_turn", side_effect=model) as launch:
                    run.execute(out, manifest)
                    self.assertTrue(manifest["turns"][0]["completed"])
                    self.assertTrue(manifest["turns"][0]["identity_ok"])
                    if mode == "noise-bytecode":
                        self.assertEqual(manifest["status"], "pending-assessment")
                        self.assertTrue(manifest["fixture_changes"]["generated_bytecode"])
                        self.assertFalse((out / "turn-1.native.json").exists())
                        run.validate_resume("clarify-scope", out, manifest)
                        run.execute(out, manifest, "Product answer")
                        self.assertIn("resume", launch.call_args.args[0])
                    else:
                        self.assertEqual(manifest["status"], "incomplete")
                        self.assertIn("failure", manifest)
                        if mode == "source-change":
                            self.assertEqual(manifest["fixture_changes"]["modified"], ["export.py"])

    def test_output_boundaries(self):
        for path in (run.ROOT, run.ROOT.parent, run.ROOT / "tests/smoke/output"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "published source"):
                run.output_path(path)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "sentinel").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be empty"):
                run.output_path(path)
            self.assertEqual((path / "sentinel").read_text(encoding="utf-8"), "keep")

    def test_changed_inputs_or_parent_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory).resolve()
            (out / "consumer").mkdir()
            manifest = {"case": "missing-context", "output_dir": str(out), "inputs": run.inputs("missing-context"),
                        "runtime_installed": {}, "turns": [], "session_id": None, "status": "prepared"}
            run.validate_resume("missing-context", out, manifest)
            manifest["inputs"]["driver"] = "changed"
            with self.assertRaisesRegex(ValueError, "hashes changed"):
                run.validate_resume("missing-context", out, manifest)
            manifest["inputs"] = run.inputs("missing-context")
            manifest["turns"] = [{"session_id": "parent-one"}]
            manifest["session_id"] = "parent-two"
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                run.validate_resume("missing-context", out, manifest)

    def test_shared_native_helpers_are_frozen_for_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory).resolve()
            (out / "consumer").mkdir()
            manifest = {"case": "missing-context", "output_dir": str(out), "inputs": run.inputs("missing-context"),
                        "runtime_installed": {}, "turns": [], "session_id": None, "status": "prepared"}
            run.validate_resume("missing-context", out, manifest)
            helper = run.ROOT / "tests/native_support.py"
            original_digest = run.digest
            with patch.object(run, "digest", side_effect=lambda path: "changed-helper" if path == helper else original_digest(path)):
                with self.assertRaisesRegex(ValueError, "hashes changed"):
                    run.validate_resume("missing-context", out, manifest)

    def test_changed_installed_input_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory).resolve()
            (out / "consumer").mkdir()
            manifest = {"case": "missing-reviewer", "output_dir": str(out), "inputs": run.inputs("missing-reviewer"),
                        "runtime_installed": {}, "turns": [], "session_id": None, "status": "prepared"}
            (out / "consumer/AGENTS.md").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Installed inputs changed"):
                run.validate_resume("missing-reviewer", out, manifest)
            (out / "consumer/AGENTS.md").unlink()
            manifest["baseline"] = {}
            (out / "consumer/__pycache__").mkdir()
            (out / "consumer/__pycache__/added.txt").write_bytes(b"added non-task file")
            with self.assertRaisesRegex(ValueError, "Non-task fixture files changed"):
                run.validate_resume("missing-reviewer", out, manifest)

    def test_failed_attempt_is_persisted_before_launch(self):
        for mode in ("truncated-timeout", "interrupted"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                out = Path(directory).resolve()
                (out / "consumer").mkdir()
                manifest = {"case": "missing-context", "output_dir": str(out), "inputs": run.inputs("missing-context"),
                            "runtime_installed": {}, "baseline": {}, "turns": [], "session_id": None, "status": "prepared"}
                run.write_json(out / "manifest.json", manifest)

                def model(*args, **kwargs):
                    started = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
                    self.assertEqual(started["status"], "incomplete")
                    self.assertEqual(len(started["turns"]), 1)
                    self.assertEqual(started["attempt_in_progress"], 1)
                    if mode == "interrupted":
                        raise KeyboardInterrupt()
                    if mode == "truncated-timeout":
                        raise subprocess.TimeoutExpired("codex", 1200, output=b'{"type":"thread.started","thread_id":"parent"}\n{"type":')

                with patch.object(run.shutil, "which", return_value="codex"), patch.object(run.subprocess, "check_output", return_value="fixture-version"), patch.object(run, "run_turn", side_effect=model):
                    if mode == "interrupted":
                        with self.assertRaises(KeyboardInterrupt):
                            run.execute(out, manifest)
                    else:
                        run.execute(out, manifest)
                saved = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["status"], "incomplete")
                self.assertEqual(len(saved["turns"]), 1)
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    run.validate_resume("missing-context", out, saved)
                prompt = (out / "turn-1.prompt.txt").read_bytes()
                saved["turns"] = []
                with patch.object(run.shutil, "which", return_value="codex"), self.assertRaisesRegex(RuntimeError, "filename reuse"):
                    run.execute(out, saved)
                self.assertEqual((out / "turn-1.prompt.txt").read_bytes(), prompt)


if __name__ == "__main__":
    unittest.main()
