from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import backup
import cleanup


class BackupTests(unittest.TestCase):
    def make_project(self, root: Path) -> None:
        (root / "data" / "input").mkdir(parents=True)
        (root / "configs").mkdir()
        (root / "data" / "input" / "测试.txt").write_text("original", encoding="utf-8")
        (root / "configs" / "pipeline.yaml").write_text("enabled: true\n", encoding="utf-8")

    def test_create_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)

            destination = backup.create_backup(root, "first")

            self.assertEqual(destination, root / "bak" / "first")
            self.assertEqual(backup.verify_backup(destination), [])
            self.assertTrue((destination / "data" / "input" / "测试.txt").is_file())
            self.assertTrue((destination / "configs" / "pipeline.yaml").is_file())

    def test_verify_detects_changed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)
            destination = backup.create_backup(root, "first")
            (destination / "data" / "input" / "测试.txt").write_text("changed", encoding="utf-8")

            errors = backup.verify_backup(destination)

            self.assertTrue(any("大小不符" in error or "校验失败" in error for error in errors))

    def test_restore_keeps_a_safety_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)
            backup.create_backup(root, "first")
            current_file = root / "data" / "input" / "测试.txt"
            current_file.write_text("new content", encoding="utf-8")

            _, safety = backup.restore_backup(root, "first", force=True)

            self.assertEqual(current_file.read_text(encoding="utf-8"), "original")
            self.assertEqual(
                (safety / "data" / "input" / "测试.txt").read_text(encoding="utf-8"),
                "new content",
            )

    def test_default_backup_name_uses_input_workbook_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)
            (root / "data" / "input" / "测试.xlsx").write_bytes(b"xlsx")

            destination = backup.create_backup(root)

            self.assertEqual(destination.name, "测试")

    def test_cleanup_only_removes_workspace_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            self.make_project(root)
            (root / "data" / "middle").mkdir()
            (root / "data" / "output").mkdir()
            (root / "data" / "template").mkdir()
            (root / "data" / "middle" / "01_compress").mkdir()
            (root / "data" / "output" / "site").mkdir()
            (root / "data" / "template" / "template.xlsx").write_bytes(b"template")
            (root / "data" / "input" / ".gitkeep").touch()

            cleanup.clean_workspace(root)

            self.assertTrue((root / "data" / "input" / ".gitkeep").exists())
            self.assertFalse((root / "data" / "input" / "测试.txt").exists())
            self.assertFalse((root / "data" / "middle" / "01_compress").exists())
            self.assertFalse((root / "data" / "output" / "site").exists())
            self.assertTrue((root / "data" / "template" / "template.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
