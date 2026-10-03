"""Verify that published frontend provenance covers the complete source tree."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import build_frontend


class MxuSourceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "MXU"
        self.source.mkdir()
        self.git("init")
        self.git("config", "user.name", "Source Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "core.autocrlf", "false")
        (self.source / "feature.ts").write_bytes(b"original\n")
        (self.source / "other.ts").write_bytes(b"untouched\n")
        (self.source / ".gitignore").write_bytes(b"dist/\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.lock = {"commit": self.git("rev-parse", "HEAD").stdout.strip(), "patch": "mxu.patch"}
        (self.source / "feature.ts").write_bytes(b"adapted\n")
        self.patch = self.root / "mxu.patch"
        self.patch.write_bytes(self.git("diff", "--binary").stdout.encode("utf-8"))
        self.git("restore", "feature.ts")
        self.addCleanup(patch.stopall)
        patch.object(build_frontend, "ROOT", self.root).start()

    def git(self, *arguments):
        return subprocess.run(["git", "-C", str(self.source), *arguments], check=True,
                              capture_output=True, encoding="utf-8")

    def test_clean_source_applies_patch_and_repeated_build_is_allowed(self):
        build_frontend.prepare_source(self.source, self.lock)
        build_frontend.prepare_source(self.source, self.lock)
        self.assertEqual((self.source / "feature.ts").read_text(encoding="utf-8"), "adapted\n")

    def test_extra_tracked_changes_are_rejected_and_preserved(self):
        build_frontend.prepare_source(self.source, self.lock)
        original_index = (self.source / ".git/index").read_bytes()
        (self.source / "other.ts").write_text("local changes\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "outside the pinned patch"):
            build_frontend.prepare_source(self.source, self.lock)
        self.assertEqual((self.source / "other.ts").read_text(encoding="utf-8"), "local changes\n")
        self.assertEqual((self.source / ".git/index").read_bytes(), original_index)

    def test_extra_untracked_source_is_rejected_but_ignored_builds_are_allowed(self):
        build_frontend.prepare_source(self.source, self.lock)
        (self.source / "dist").mkdir()
        (self.source / "dist/index.html").write_text("generated", encoding="utf-8")
        build_frontend.prepare_source(self.source, self.lock)
        (self.source / "extra.ts").write_text("unexpected\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "outside the pinned patch"):
            build_frontend.prepare_source(self.source, self.lock)
        self.assertTrue((self.source / "extra.ts").is_file())


if __name__ == "__main__":
    unittest.main()
