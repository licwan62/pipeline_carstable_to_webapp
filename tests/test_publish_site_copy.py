from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.publish_site_copy import replace_directory


class PublishSiteCopyTests(unittest.TestCase):
    def test_replaces_complete_destination_and_removes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "public"
            destination = root / "nas" / "car"
            source.mkdir()
            destination.mkdir(parents=True)
            (source / "index.html").write_text("new", encoding="utf-8")
            (source / "asset.js").write_text("asset", encoding="utf-8")
            (destination / "index.html").write_text("old", encoding="utf-8")
            (destination / "stale.txt").write_text("stale", encoding="utf-8")

            replace_directory(source, destination)

            self.assertEqual((destination / "index.html").read_text(encoding="utf-8"), "new")
            self.assertTrue((destination / "asset.js").is_file())
            self.assertFalse((destination / "stale.txt").exists())

    def test_requires_source_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "public"
            source.mkdir()
            with self.assertRaises(FileNotFoundError):
                replace_directory(source, root / "nas" / "car")


if __name__ == "__main__":
    unittest.main()
