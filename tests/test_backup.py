from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import backup
import cleanup


class BackupTests(unittest.TestCase):
    def make_project(self, root: Path) -> None:
        (root / "input").mkdir()
        (root / "artifact" / "2026-09-01_01_old").mkdir(parents=True)
        (root / "public").mkdir()
        (root / "configs").mkdir()
        (root / "input" / "测试.txt").write_text("original", encoding="utf-8")
        (root / "artifact" / "2026-09-01_01_old" / "artifact.json").write_text("{}", encoding="utf-8")
        (root / "public" / "index.html").write_text("site", encoding="utf-8")
        (root / "configs" / "pipeline.yaml").write_text("enabled: true\n", encoding="utf-8")

    def test_create_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)

            destination = backup.create_backup(root, "first")

            self.assertEqual(destination, root / "bak" / "first")
            self.assertEqual(backup.verify_backup(destination), [])
            self.assertTrue((destination / "input" / "测试.txt").is_file())
            self.assertTrue((destination / "artifact" / "2026-09-01_01_old" / "artifact.json").is_file())
            self.assertTrue((destination / "public" / "index.html").is_file())
            self.assertTrue((destination / "configs" / "pipeline.yaml").is_file())

    def test_verify_detects_changed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)
            destination = backup.create_backup(root, "first")
            (destination / "input" / "测试.txt").write_text("changed", encoding="utf-8")

            errors = backup.verify_backup(destination)

            self.assertTrue(any("大小不符" in error or "校验失败" in error for error in errors))

    def test_restore_keeps_a_safety_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)
            backup.create_backup(root, "first")
            current_file = root / "input" / "测试.txt"
            current_file.write_text("new content", encoding="utf-8")

            _, safety = backup.restore_backup(root, "first", force=True)

            self.assertEqual(current_file.read_text(encoding="utf-8"), "original")
            self.assertEqual(
                (safety / "input" / "测试.txt").read_text(encoding="utf-8"),
                "new content",
            )

    def test_restore_migrates_legacy_data_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)
            legacy = root / "bak" / "legacy"
            (legacy / "data" / "input").mkdir(parents=True)
            (legacy / "data" / "output" / "site").mkdir(parents=True)
            (legacy / "configs").mkdir()
            (legacy / "data" / "input" / "old.xlsx").write_bytes(b"legacy")
            (legacy / "data" / "output" / "site" / "index.html").write_text(
                "legacy site", encoding="utf-8"
            )
            (legacy / "configs" / "pipeline.yaml").write_text("legacy: true\n", encoding="utf-8")
            sources = []
            for name in backup.LEGACY_SOURCE_DIR_NAMES:
                files = backup.source_inventory(legacy / name)
                sources.append(
                    {
                        "path": name,
                        "file_count": len(files),
                        "total_bytes": sum(item["size"] for item in files),
                        "files": files,
                    }
                )
            (legacy / backup.MANIFEST_NAME).write_text(
                json.dumps({"version": 1, "name": "legacy", "sources": sources}),
                encoding="utf-8",
            )

            backup.restore_backup(root, "legacy", force=True)

            self.assertEqual((root / "input" / "old.xlsx").read_bytes(), b"legacy")
            self.assertEqual(
                (root / "public" / "index.html").read_text(encoding="utf-8"), "legacy site"
            )
            self.assertFalse((root / "data").exists())

    def test_default_backup_name_uses_input_workbook_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)
            (root / "input" / "测试.xlsx").write_bytes(b"xlsx")

            destination = backup.create_backup(root)

            self.assertEqual(destination.name, "测试")

    def test_cleanup_only_removes_workspace_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)
            (root / "input" / ".gitkeep").touch()

            cleanup.clean_workspace(root)

            self.assertTrue((root / "input" / ".gitkeep").exists())
            self.assertFalse((root / "input" / "测试.txt").exists())
            self.assertFalse((root / "public" / "index.html").exists())
            self.assertTrue((root / "artifact" / "2026-09-01_01_old" / "artifact.json").exists())


if __name__ == "__main__":
    unittest.main()
