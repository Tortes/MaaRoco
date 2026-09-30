import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import sync_gitee


def release_fixture():
    return {"tag_name": "v1.2.3", "name": "Version 1.2.3", "body": "Release notes",
            "html_url": "https://github.com/Tortes/MaaRoco/releases/tag/v1.2.3",
            "prerelease": False, "published_at": "2026-09-30T00:00:00Z",
            "assets": [{"id": 1, "name": "app.zip", "size": 11, "digest": "sha256:abc",
                        "browser_download_url": "https://github.com/Tortes/MaaRoco/releases/download/v1.2.3/app.zip",
                        "updated_at": "2026-09-30T00:00:00Z"}]}


class SplitReleaseTest(unittest.TestCase):
    def test_split_reassembles_byte_identical_original(self):
        content = bytes(range(256)) * 33
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "app.zip"
            original.write_bytes(content)
            parts = sync_gitee.split_asset(original, size_limit=1000)
            self.assertEqual(len(parts), 9)
            self.assertTrue(all(part.stat().st_size <= 1000 for part in parts))
            self.assertEqual(b"".join(part.read_bytes() for part in parts), content)
            self.assertEqual(sync_gitee.checksum(original), hashlib.sha256(content).hexdigest())

    def test_boundary_keeps_original_name_and_small_file_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.zip"
            path.write_bytes(b"12345")
            self.assertEqual(sync_gitee.split_asset(path, 5), [path])
        with patch.object(sync_gitee, "PART_SIZE", 5):
            self.assertEqual(sync_gitee.asset_parts({"name": "a.zip", "size": 5}), [("a.zip", 5)])
            self.assertEqual(sync_gitee.asset_parts({"name": "a.zip", "size": 11}),
                             [("a.zip.001", 5), ("a.zip.002", 5), ("a.zip.003", 1)])

    def test_rejects_asset_path_traversal(self):
        for name in ("../outside", "a/b", "a\\b", "..", "a\nb"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                sync_gitee.safe_name(name)

    def test_notes_give_exact_parts_and_original_hash(self):
        with patch.object(sync_gitee, "PART_SIZE", 5):
            notes = sync_gitee.download_notes(release_fixture())
        self.assertIn("app.zip.003", notes)
        self.assertIn("$count = 3", notes)
        self.assertIn("cat 'app.zip'.001 'app.zip'.002 'app.zip'.003 > 'app.zip'", notes)
        self.assertIn("原始文件 SHA-256：`abc`", notes)

    def test_incomplete_release_never_gets_completion_marker(self):
        release = release_fixture()
        self.assertNotIn(sync_gitee.MARKER, sync_gitee.release_body(release))
        self.assertIn(sync_gitee.MARKER, sync_gitee.release_body(release, complete=True))

    def test_changed_same_size_source_asset_changes_fingerprint(self):
        release = release_fixture()
        before = sync_gitee.fingerprint(release)
        release["assets"][0]["digest"] = "sha256:different"
        self.assertNotEqual(before, sync_gitee.fingerprint(release))


def mock_mirror():
    mirror = sync_gitee.Mirror.__new__(sync_gitee.Mirror)
    mirror.attachments = Mock()
    mirror.download = Mock()
    mirror.upload = Mock()
    mirror.api = Mock()
    return mirror


class ResumeReleaseTest(unittest.TestCase):
    def test_complete_release_skips_download_and_upload(self):
        release = release_fixture()
        target = {"id": 42, **{key: release[key] for key in ("tag_name", "name", "prerelease")},
                  "body": sync_gitee.release_body(release, complete=True)}
        mirror = mock_mirror()
        mirror.attachments.return_value = [{"name": "app.zip", "size": 11},
                                           {"name": "GITEE_DOWNLOAD.md", "size": 1},
                                           {"name": "SHA256SUMS-Gitee.txt", "size": 1}]
        self.assertTrue(mirror.sync(release, target)["verified"])
        mirror.download.assert_not_called()
        mirror.upload.assert_not_called()
        mirror.api.assert_not_called()


class RetentionTest(unittest.TestCase):
    def test_keeps_latest_stable_and_preview_by_publication_date(self):
        releases = [
            {"tag_name": "v1", "prerelease": False, "published_at": "2026-01-01"},
            {"tag_name": "v2", "prerelease": False, "published_at": "2026-01-03"},
            {"tag_name": "v3-preview.1", "prerelease": True, "published_at": "2026-01-02"},
            {"tag_name": "v3-preview.2", "prerelease": True, "published_at": "2026-01-04"}]
        self.assertEqual(sync_gitee.retained_tags(releases), {"v2", "v3-preview.2"})
        self.assertEqual(sync_gitee.retained_tags(releases[:2]), {"v2"})

    def test_archiving_preserves_unrelated_attachments_and_links_to_original(self):
        mirror = sync_gitee.Mirror.__new__(sync_gitee.Mirror)
        mirror.attachments = Mock(return_value=[
            {"id": 1, "name": "app.zip.001"},
            {"id": 2, "name": "GITEE_DOWNLOAD.md"},
            {"id": 3, "name": "manually-uploaded.txt"}])
        mirror.api = Mock()
        release = release_fixture()
        with patch.object(sync_gitee, "PART_SIZE", 5):
            report = mirror.archive(release, {"id": 42, "body": "old notes"})
        self.assertEqual(report["removed_files"], 2)
        deleted = [call.args[1] for call in mirror.api.call_args_list if call.args[0] == "DELETE"]
        self.assertEqual(deleted, ["/releases/42/attach_files/1", "/releases/42/attach_files/2"])
        notes = mirror.api.call_args.kwargs["json"]["body"]
        self.assertTrue(notes.startswith("Release notes"))
        self.assertIn(release["assets"][0]["browser_download_url"], notes)
        self.assertNotIn(sync_gitee.MARKER, notes)

    def test_historical_note_updates_do_not_become_latest_release(self):
        mirror = Mock()
        release = release_fixture()
        mirror.api.side_effect = [
            {"tag_name": "v0.1.0"},
            {"id": 42, "tag_name": release["tag_name"], "name": release["name"],
             "body": "published notes", "prerelease": False},
            {}, {"tag_name": release["tag_name"]}]
        sync_gitee.restore_latest_stable(mirror, [release])
        update = mirror.api.call_args_list[2]
        self.assertEqual(update.args, ("PATCH", "/releases/42"))
        self.assertTrue(update.kwargs["json"]["body"].startswith("published notes"))

    def test_changed_source_does_not_silently_keep_stale_binary(self):
        release = release_fixture()
        target = {"id": 42, "body": sync_gitee.release_body(release, complete=True)}
        release["assets"][0]["digest"] = "sha256:replacement"
        mirror = mock_mirror()
        mirror.attachments.return_value = []
        with self.assertRaisesRegex(RuntimeError, "Source attachments changed"):
            mirror.sync(release, target)
        mirror.upload.assert_not_called()

    def test_failed_upload_is_not_marked_complete(self):
        release = release_fixture()
        release["assets"][0]["size"] = 4
        mirror = mock_mirror()
        mirror.attachments.return_value = []
        mirror.upload.side_effect = RuntimeError("upload interrupted")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.zip"
            path.write_bytes(b"test")
            mirror.cache = Path(directory)
            mirror.download.return_value = path, sync_gitee.checksum(path)
            with self.assertRaisesRegex(RuntimeError, "upload interrupted"):
                mirror.sync(release, {"id": 42, "body": "notes"})
        mirror.api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
