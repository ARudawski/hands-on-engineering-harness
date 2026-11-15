"""Portable plugin contract; no model/account credentials required."""

import hashlib
import json
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
import zipfile

import yaml


SOURCE = Path(__file__).resolve().parents[1]
SKILLS = {"route", "clarify-scope", "write-spec", "plan-slices", "plan-feature",
          "deliver-task", "research", "deliver-code", "implement-slice", "review-code"}


class PluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = runpy.run_path(str(SOURCE / "scripts/build_plugin.py"))

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "source"
        self.root.mkdir()
        shutil.copytree(SOURCE / ".apm", self.root / ".apm")
        for name in ("plugin.json", "LICENSE", "THIRD-PARTY-NOTICES.md"):
            shutil.copy2(SOURCE / name, self.root / name)
        self.output = Path(directory.name) / "plugin.zip"

    def build(self):
        self.builder["build"](self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_complete_self_contained_skills_and_unchanged_source(self):
        before = {p.relative_to(self.root): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        files = self.build()
        self.assertEqual({p.split("/")[1] for p in files if p.endswith("/SKILL.md")
                          and p.count("/") == 2}, SKILLS)
        manifest = json.loads(files["plugin.json"])
        self.assertEqual(manifest["name"], "hands-on-engineering-harness")
        self.assertIn("LICENSE", files)
        self.assertIn("THIRD-PARTY-NOTICES.md", files)
        for name in SKILLS:
            prefix = f"skills/{name}/"
            entry = files[prefix + "SKILL.md"].decode()
            self.assertEqual(yaml.safe_load(entry.split("---", 2)[1])["name"], name)
            self.assertIn("references/harness/runtime.md", entry)
            local = {p[len(prefix):]: value for p, value in files.items() if p.startswith(prefix)}
            self.builder["validate_links"](local)
            for relative, content in before.items():
                if relative.parts[0] == ".apm":
                    self.assertEqual(local["references/harness/" + relative.relative_to(".apm").as_posix()], content)
            runtime = local["references/harness/runtime.md"].decode()
            self.assertIn("same reviewer session", runtime)
            self.assertIn("incomplete", runtime)
            self.assertIn("@deliver-task", runtime)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes()
                                 for p in self.root.rglob("*") if p.is_file()})

    def test_reproducible_and_no_unrelated_files(self):
        (self.root / "secret.txt").write_text("never package")
        files = self.build()
        digest = hashlib.sha256(self.output.read_bytes()).digest()
        self.build()
        self.assertEqual(digest, hashlib.sha256(self.output.read_bytes()).digest())
        self.assertNotIn("secret.txt", files)
        self.assertFalse(any(p.startswith((".git/", ".tmp/", "tests/")) for p in files))

    def test_broken_reference_rejected_before_output(self):
        path = self.root / ".apm/skills/route/SKILL.md"
        path.write_text(path.read_text() + "\n[missing](missing.md)\n")
        with self.assertRaisesRegex(ValueError, "reference"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_missing_or_invalid_skill_rejected(self):
        path = self.root / ".apm/skills/route/SKILL.md"
        path.write_text("---\nname: wrong\ndescription: ''\n---\n")
        with self.assertRaisesRegex(ValueError, "skill"):
            self.build()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "skill"):
            self.build()

    def test_invalid_manifest_rejected(self):
        path = self.root / "plugin.json"
        manifest = json.loads(path.read_text())
        manifest["$schema"] = "wrong"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.build()

    def test_source_overwrite_and_symlinks_rejected(self):
        self.output = self.root / "LICENSE"
        original = self.output.read_bytes()
        with self.assertRaisesRegex(ValueError, "output"):
            self.build()
        self.assertEqual(self.output.read_bytes(), original)
        self.output = self.root.parent / "plugin.zip"
        path = self.root / ".apm/skills/route/SKILL.md"
        path.unlink()
        path.symlink_to(self.root / "LICENSE")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.build()

    def test_reference_cannot_escape_component(self):
        with self.assertRaisesRegex(ValueError, "reference"):
            self.builder["validate_links"]({"SKILL.md": b"[bad](../foreign.md)"})
