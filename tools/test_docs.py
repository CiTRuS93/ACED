"""Offline regressions for the docs-only staging boundary and link conversion."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_docs


class StageSourcesTests(unittest.TestCase):
    def test_only_tracked_public_sources_are_staged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkout"
            target = Path(directory) / "staged"
            root.mkdir()
            files = {
                "README.md": "# ACED\n",
                "docs/guide.md": "# Guide\n",
                "docs/local-notes.md": "Untracked local material",
                "docs/runtime.sqlite": "Runtime data",
                ".env": "Local configuration",
                "src/aced/runtime.py": "# Source stays in GitHub\n",
                "examples/demo.py": "print('fixture')\n",
            }
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            tracked = [name for name in files if name != "docs/local-notes.md"]
            with (
                patch.object(build_docs, "ROOT", root),
                patch.object(
                    build_docs.subprocess, "check_output", return_value="\0".join(tracked)
                ),
            ):
                build_docs.stage_sources(target)
            self.assertEqual(
                {str(path.relative_to(target)) for path in target.rglob("*") if path.is_file()},
                {"README.md", "docs/guide.md", "examples/demo.py"},
            )

    def test_local_docs_and_assets_keep_fragments_and_code_links_remain_external(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkout"
            target = Path(directory) / "staged"
            (root / "docs").mkdir(parents=True)
            source = (
                "[Runtime](https://github.com/CiTRuS93/ACED/blob/main/docs/runtime.md#storage)\n"
                "![Image](https://raw.githubusercontent.com/CiTRuS93/ACED/main/docs/image.png)\n"
                "[Code](../src/aced/runtime.py#L10)\n"
                "[Other](https://example.org/guide)\n"
            )
            (root / "docs/guide.md").write_text(source, encoding="utf-8")
            (root / "docs/runtime.md").write_text("# Storage\n", encoding="utf-8")
            (root / "docs/image.png").write_bytes(b"fixture image")
            tracked = ["docs/guide.md", "docs/runtime.md", "docs/image.png", "src/aced/runtime.py"]
            with (
                patch.object(build_docs, "ROOT", root),
                patch.object(
                    build_docs.subprocess, "check_output", return_value="\0".join(tracked)
                ),
            ):
                build_docs.stage_sources(target)
            staged = (target / "docs/guide.md").read_text(encoding="utf-8")
            self.assertIn("[Runtime](runtime.md#storage)", staged)
            self.assertIn("![Image](image.png)", staged)
            self.assertIn(
                "[Code](https://github.com/CiTRuS93/ACED/blob/main/src/aced/runtime.py#L10)", staged
            )
            self.assertIn("[Other](https://example.org/guide)", staged)
            self.assertEqual((root / "docs/guide.md").read_text(encoding="utf-8"), source)


if __name__ == "__main__":
    unittest.main()
