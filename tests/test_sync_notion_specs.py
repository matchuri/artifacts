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

    def test_notions_tab_indentation_matches_two_space_nested_lists(self) -> None:
        local = "- 관련 API\n  - `GET /api/v1/example`\n"
        remote = "- 관련 API\n\t- `GET /api/v1/example`\n"
        self.assertTrue(sync.markdown_equal(local, remote))

    def test_title_and_template_validate(self) -> None:
        path = Path("이메일 인증 기능.md")
        self.assertEqual("이메일 인증 기능", sync.validate_markdown(path, VALID_MARKDOWN))

    def test_missing_required_heading_fails(self) -> None:
        with self.assertRaises(sync.SyncError):
            sync.validate_markdown(Path("broken.md"), VALID_MARKDOWN.replace("## 엣지케이스", "## 예외"))

    def test_filename_and_h1_must_match(self) -> None:
        with self.assertRaises(sync.SyncError):
            sync.validate_markdown(Path("그룹 목록 조회 및 생성 기능.md"), VALID_MARKDOWN)

    def test_problematic_rename_is_similar_enough_to_block_creation(self) -> None:
        ratio = sync.difflib.SequenceMatcher(None, "그룹 목록 및 생성 기능", "그룹 목록 조회 및 생성 기능").ratio()
        self.assertGreaterEqual(ratio, sync.SIMILAR_TITLE_THRESHOLD)

    def test_reference_api_and_data_are_formatted_as_nested_lists(self) -> None:
        compact = VALID_MARKDOWN.replace(
            "- 참고",
            "- 관련 API: `GET /one`, `POST /two`\n- 관련 데이터: `first`, `second`\n- 미정 사항: 유지",
        )
        formatted = sync.format_reference_section(compact)
        self.assertIn("- 관련 API\n  - `GET /one`\n  - `POST /two`", formatted)
        self.assertIn("- 관련 데이터\n  - `first`\n  - `second`", formatted)
        self.assertIn("- 미정 사항: 유지", formatted)

    def test_compact_reference_list_fails_validation(self) -> None:
        compact = VALID_MARKDOWN.replace("- 참고", "- 관련 API: `GET /one`, `POST /two`")
        with self.assertRaises(sync.SyncError):
            sync.validate_markdown(Path("이메일 인증 기능.md"), compact)

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
