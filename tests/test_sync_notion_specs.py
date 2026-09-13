from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_notion_specs.py"
SPEC = importlib.util.spec_from_file_location("sync_notion_specs", SCRIPT)
assert SPEC and SPEC.loader
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


VALID_MARKDOWN = """# 이메일 인증 기능

## 설명

- 설명

## 수용 기준

- 기준

## 엣지케이스

- 예외

## 참고

- 참고
"""


class MarkdownTests(unittest.TestCase):
    def test_notions_empty_blocks_do_not_create_false_difference(self) -> None:
        remote = VALID_MARKDOWN.replace("\n\n", "\n<empty-block/>\n")
        self.assertTrue(sync.markdown_equal(VALID_MARKDOWN, remote))

    def test_title_and_template_validate(self) -> None:
        path = Path("이메일 인증 기능.md")
        self.assertEqual("이메일 인증 기능", sync.validate_markdown(path, VALID_MARKDOWN))

    def test_missing_required_heading_fails(self) -> None:
        with self.assertRaises(sync.SyncError):
            sync.validate_markdown(Path("broken.md"), VALID_MARKDOWN.replace("## 엣지케이스", "## 예외"))

    def test_duplicate_titles_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.md"
            second = Path(directory) / "second.md"
            first.write_text(VALID_MARKDOWN, encoding="utf-8")
            second.write_text(VALID_MARKDOWN, encoding="utf-8")
            with self.assertRaises(sync.SyncError):
                sync.validate_specs([first, second])

    def test_resolve_spec_rejects_file_outside_specs_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            specs = root / "features"
            specs.mkdir()
            outside = root / "outside.md"
            outside.write_text(VALID_MARKDOWN, encoding="utf-8")
            with self.assertRaises(sync.SyncError):
                sync.resolve_spec(specs.resolve(), str(outside))


if __name__ == "__main__":
    unittest.main()
