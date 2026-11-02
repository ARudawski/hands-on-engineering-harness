"""Model-free driver safeguards. Run explicitly: python tests/smoke/check_driver.py."""

import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

import run


class DriverGuards(unittest.TestCase):
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
            (out / "consumer/__pycache__/added.pyc").write_bytes(b"added non-task file")
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
            with patch.object(run, "session_file", return_value=path):
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

                with patch.object(run.shutil, "which", return_value="codex"), patch.object(run.subprocess, "check_output", return_value="fixture-version"), patch.object(run.subprocess, "run", side_effect=model), patch.object(run, "native_evidence", side_effect=RuntimeError("collection unavailable")):
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
