"""Model-free driver safeguards. Run explicitly: python tests/smoke/check_driver.py."""

import json
from pathlib import Path
import tempfile
import subprocess
import os
import sys
import time
import unittest
from unittest.mock import patch

import run


class DriverGuards(unittest.TestCase):
    def test_cross_day_children_and_unrelated_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sessions"
            parent = root / "2026/11/01/parent.jsonl"
            child = root / "2026/11/02/child.jsonl"
            parent.parent.mkdir(parents=True)
            child.parent.mkdir(parents=True)
            parent.write_text(json.dumps({"type": "session_meta", "payload": {"id": "parent", "source": "exec"}}) + "\n", encoding="utf-8")
            child.write_text(json.dumps({"type": "session_meta", "payload": {"id": "child", "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}}}) + "\n", encoding="utf-8")
            for name, content in {"partial": '{"type":', "old": '{}', "array": '[]', "null": '{"payload":null}'}.items():
                (parent.parent / f"{name}.jsonl").write_text(content, encoding="utf-8")
            with patch.dict(os.environ, {"CODEX_HOME": directory}), patch.object(run, "session_file", return_value=parent):
                self.assertEqual([r["id"] for r in run.native_evidence("parent")], ["parent", "child"])
                child.write_text(child.read_text(encoding="utf-8") + '{"type":', encoding="utf-8")
                with self.assertRaises((ValueError, RuntimeError)):
                    run.native_evidence("parent")

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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "export.py").write_text('value = 1\n', encoding="utf-8")
            before = run.inventory(root)
            subprocess.run([sys.executable, "-c", "import export"], cwd=root, check=True, timeout=10,
                           env={k: v for k, v in os.environ.items() if k not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"}})
            changes = run.fixture_changes(before, run.inventory(root))
            self.assertTrue(changes["generated_bytecode"])
            self.assertEqual(changes["added"], [])
            (root / "export.py").write_text('value = 2\n', encoding="utf-8")
            (root / "__pycache__/notes.txt").write_text('not bytecode', encoding="utf-8")
            changes = run.fixture_changes(before, run.inventory(root))
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
                with patch.object(run.shutil, "which", return_value="codex"), patch.object(run.subprocess, "check_output", return_value="fixture-version"), patch.object(run, "run_turn", side_effect=model) as launch, patch.object(run, "native_evidence", return_value=[]):
                    run.execute(out, manifest)
                    self.assertTrue(manifest["turns"][0]["completed"])
                    self.assertTrue(manifest["turns"][0]["identity_ok"])
                    if mode == "noise-bytecode":
                        self.assertEqual(manifest["status"], "pending-assessment")
                        self.assertTrue(manifest["fixture_changes"]["generated_bytecode"])
                        meta = out / "parent.jsonl"
                        meta.write_text(json.dumps({"type": "session_meta", "payload": {"id": "parent", "cwd": str(consumer)}}), encoding="utf-8")
                        with patch.object(run, "session_file", return_value=meta):
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

    def test_native_evidence_has_own_actions_without_reasoning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parent.jsonl"
            events = [
                {"type": "session_meta", "payload": {"id": "parent", "source": "cli"}},
                {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "parent-turn"}},
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "parent-call", "name": "spawn_agent", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "parent-call", "output": "parent-result"}},
                {"type": "event_msg", "payload": {"type": "item_completed", "thread_id": "other", "item": {"type": "CommandExecution", "command": "inherited"}}},
                {"type": "event_msg", "payload": {"type": "item_completed", "thread_id": "parent", "item": {"type": "Reasoning", "raw_content": "exclude"}}},
                {"type": "event_msg", "payload": {"type": "item_completed", "thread_id": "parent", "turn_id": "parent-turn", "item": {"type": "CommandExecution", "command": "own"}}},
            ]
            path.write_text("\n".join(map(json.dumps, events)), encoding="utf-8")
            child = {"type": "session_meta", "payload": {"id": "child", "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent", "agent_role": "plan-reviewer"}}}}}
            child_events = [child, *events,
                            {"type": "turn_context", "payload": {"turn_id": "inherited", "model": "inherited"}},
                            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "own"}},
                            {"type": "turn_context", "payload": {"turn_id": "own", "model": "observed"}},
                            {"type": "response_item", "payload": {"type": "function_call", "call_id": "child-function", "name": "read", "arguments": "{}"}},
                            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "child-function", "output": "own-read"}},
                            {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "child-custom", "name": "exec", "input": "own-code"}},
                            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "child-custom", "output": "own-result"}},
                            {"type": "event_msg", "payload": {"type": "item_completed", "thread_id": "child", "turn_id": "own", "item": {"type": "CommandExecution", "command": "child-own"}}}]
            (Path(directory) / "child.jsonl").write_text("\n".join(map(json.dumps, child_events)), encoding="utf-8")
            with patch.object(run, "session_file", return_value=path), patch.object(run, "session_root", return_value=Path(directory)):
                evidence = run.native_evidence("parent")
            self.assertEqual([e["id"] for e in evidence], ["parent", "child"])
            self.assertEqual(evidence[0]["actions"][0]["item"]["command"], "own")
            self.assertEqual(len(evidence[0]["actions"]), 1)
            self.assertEqual(evidence[1]["actions"][0]["item"]["command"], "child-own")
            self.assertEqual(len(evidence[1]["actions"]), 1)
            self.assertEqual(evidence[1]["settings"], [{"model": "observed"}])
            self.assertEqual({r["payload"]["call_id"] for r in evidence[0]["tool_records"]}, {"parent-call"})
            self.assertEqual({r["payload"]["call_id"] for r in evidence[1]["tool_records"]}, {"child-function", "child-custom"})
            self.assertEqual(len(evidence[1]["tool_records"]), 4)
            self.assertNotIn("raw_content", json.dumps(evidence))
            child_path = Path(directory) / "child.jsonl"
            original = child_path.read_text(encoding="utf-8")
            child_path.write_text(original + '\n' + json.dumps({"type": "turn_context", "payload": {"turn_id": []}}), encoding="utf-8")
            with patch.object(run, "session_file", return_value=path), patch.object(run, "session_root", return_value=Path(directory)):
                with self.assertRaisesRegex(RuntimeError, "Invalid native turn identity"):
                    run.native_evidence("parent")

    def test_failed_attempt_is_persisted_before_launch(self):
        for mode in ("truncated-timeout", "interrupted", "collection-failure"):
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
                    return subprocess.CompletedProcess([], 0, '{"type":"thread.started","thread_id":"parent"}\n{"type":"turn.completed"}\n', "")

                with patch.object(run.shutil, "which", return_value="codex"), patch.object(run.subprocess, "check_output", return_value="fixture-version"), patch.object(run, "run_turn", side_effect=model), patch.object(run, "native_evidence", side_effect=RuntimeError("collection unavailable")):
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
