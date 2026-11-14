"""Model-free checks for the development CLI launch boundary."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import native_support as native


class NativeRuntimeTests(unittest.TestCase):
    def test_child_environment_removes_only_desktop_launch_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            before = {"CODEX_WINDOWS_REGISTERED_CORE": "1", "CODEX_PERMISSION_PROFILE": "keep-policy",
                      "CODEX_HOME": "keep-home", "UNRELATED": "keep-value"}
            with patch.dict(os.environ, before, clear=True), patch.object(native.sys, "platform", "win32"):
                env = native.native_env(Path(directory))
                self.assertNotIn("CODEX_WINDOWS_REGISTERED_CORE", env)
                self.assertEqual(os.environ["CODEX_WINDOWS_REGISTERED_CORE"], "1")
                for key in before.keys() - {"CODEX_WINDOWS_REGISTERED_CORE"}:
                    self.assertEqual(env[key], before[key])
                self.assertEqual(env["GIT_CEILING_DIRECTORIES"], str(Path(directory).resolve().parent))

    def test_explicit_cli_selection_does_not_fall_back_on_error(self):
        with patch.dict(os.environ, {"CODEX_BIN": "chosen-cli"}), patch.object(native.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "CODEX_BIN"):
                native.resolve_codex()
        with patch.dict(os.environ, {"CODEX_BIN": sys.executable}):
            self.assertEqual(native.resolve_codex(), str(Path(sys.executable).resolve()))

    def test_windows_preflight_launches_only_sandbox_probe(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(native.sys, "platform", "win32"):
            def probe(command, prompt, cwd, timeout):
                self.assertIn("sandbox", command)
                self.assertNotIn("exec", command)
                self.assertIn(":workspace", command)
                self.assertIn("--include-managed-config", command)
                self.assertEqual(timeout, 30)
                return subprocess.CompletedProcess(command, 0, "native-file-access-ok\n", "")
            with patch.object(native.subprocess, "check_output", return_value="codex-cli test"), patch.object(native, "run_turn", side_effect=probe):
                result = native.check_codex_runtime("codex", Path(directory))
            self.assertEqual(result["file_access"], "passed")
            self.assertEqual(list((Path(directory) / ".tmp").iterdir()), [])

    def test_preflight_failure_has_actionable_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(native.sys, "platform", "win32"):
            with patch.object(native.subprocess, "check_output", return_value="codex-cli test"), patch.object(native, "run_turn", return_value=subprocess.CompletedProcess([], 1, "", "registered Core launch requires an installed app")):
                with self.assertRaisesRegex(RuntimeError, "CODEX_BIN.*registered Core"):
                    native.check_codex_runtime("codex", Path(directory))


if __name__ == "__main__":
    unittest.main()
