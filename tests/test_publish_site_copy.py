from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.publish_site_copy import STATE_DIR, publish_owned


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def claim(destination: Path, publisher: str, files: list[str], nav: list | None = None) -> None:
    """模拟另一个项目按同一约定发布到站点。"""
    for relative in files:
        write(destination / relative, publisher)
    write(destination / STATE_DIR / f"{publisher}.json", json.dumps({"files": {f: "x" for f in files}}))
    registry_path = destination / STATE_DIR / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {"publishers": {}}
    registry["publishers"][publisher] = {"nav": nav or []}
    write(registry_path, json.dumps(registry))


class PublishSiteCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.source = root / "public"
        self.destination = root / "nas" / "car"
        write(self.source / "index.html", "new")
        write(self.source / "assets" / "app" / "viewer.js", "viewer")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def state(self) -> dict:
        return json.loads((self.destination / STATE_DIR / "pipeline_carstable_to_webapp.json").read_text(encoding="utf-8"))

    def test_first_publish_adopts_previous_whole_site_and_keeps_other_publishers(self) -> None:
        write(self.destination / "index.html", "old")
        write(self.destination / "stale.txt", "stale")
        claim(self.destination, "amazon_competitor_analysis", ["asin_analysis.html", "data/asin-analysis/index.json"],
              [{"href": "asin_analysis.html", "label": "ASIN 分析"}])

        publish_owned(self.source, self.destination)

        self.assertEqual((self.destination / "index.html").read_text(encoding="utf-8"), "new")
        self.assertFalse((self.destination / "stale.txt").exists())
        self.assertEqual((self.destination / "asin_analysis.html").read_text(encoding="utf-8"), "amazon_competitor_analysis")
        self.assertTrue((self.destination / "data" / "asin-analysis" / "index.json").is_file())
        self.assertEqual(sorted(self.state()["files"]), ["assets/app/viewer.js", "index.html"])
        registry = json.loads((self.destination / STATE_DIR / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(registry["publishers"]), ["amazon_competitor_analysis", "pipeline_carstable_to_webapp"])
        self.assertEqual(registry["publishers"]["amazon_competitor_analysis"]["nav"][0]["href"], "asin_analysis.html")

    def test_removes_only_own_files_dropped_from_build(self) -> None:
        write(self.source / "old-page.html", "old page")
        publish_owned(self.source, self.destination)
        claim(self.destination, "other", ["other.html"])
        (self.source / "old-page.html").unlink()
        write(self.destination / "manual.txt", "manual")

        result = publish_owned(self.source, self.destination)

        self.assertFalse((self.destination / "old-page.html").exists())
        self.assertTrue((self.destination / "other.html").is_file())
        self.assertTrue((self.destination / "manual.txt").is_file())
        self.assertEqual((result["copied"], result["removed"]), (0, 1))
        self.assertFalse(list(self.destination.rglob("*.publishing")))

    def test_conflicts_change_nothing(self) -> None:
        publish_owned(self.source, self.destination)
        claim(self.destination, "other", ["shared.html"])
        write(self.source / "shared.html", "mine")
        write(self.source / "index.html", "changed")
        with self.assertRaises(ValueError):
            publish_owned(self.source, self.destination)
        self.assertEqual((self.destination / "shared.html").read_text(encoding="utf-8"), "other")
        self.assertEqual((self.destination / "index.html").read_text(encoding="utf-8"), "new")

        (self.source / "shared.html").unlink()
        write(self.source / "manual.txt", "mine")
        write(self.destination / "manual.txt", "manual")
        with self.assertRaises(ValueError):
            publish_owned(self.source, self.destination)
        self.assertEqual((self.destination / "manual.txt").read_text(encoding="utf-8"), "manual")

    def test_first_publish_skips_identical_existing_files(self) -> None:
        write(self.destination / "index.html", "new")
        write(self.destination / "assets" / "app" / "viewer.js", "old viewer")

        result = publish_owned(self.source, self.destination)

        self.assertEqual(result["copied"], 1)
        self.assertEqual((self.destination / "assets" / "app" / "viewer.js").read_text(encoding="utf-8"), "viewer")

    def test_transient_network_errors_are_retried(self) -> None:
        from tools.publish_site_copy import with_retry

        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                error = OSError("unexpected network error")
                error.winerror = 59
                raise error
            return "ok"

        self.assertEqual(with_retry(flaky, delays=(0, 0, 0)), "ok")
        with self.assertRaises(FileNotFoundError):
            with_retry(lambda: (_ for _ in ()).throw(FileNotFoundError("missing")), delays=(0,))

    def test_requires_source_index(self) -> None:
        (self.source / "index.html").unlink()
        with self.assertRaises(FileNotFoundError):
            publish_owned(self.source, self.destination)


if __name__ == "__main__":
    unittest.main()
