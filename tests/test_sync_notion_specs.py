from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
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


class RecordingNotionClient:
    def __init__(self, title: str, markdown: str) -> None:
        self.title = title
        self.markdown = markdown
        self.calls: list[str] = []

    def retrieve_data_source(self, data_source_id: str) -> dict:
        self.calls.append("retrieve_data_source")
        return {"properties": {"이름": {"type": "title"}}}

    def retrieve_page(self, page_id: str) -> dict:
        self.calls.append("retrieve_page")
        return {
            "properties": {
                "이름": {
                    "title": [{"plain_text": self.title}],
                }
            }
        }

    def retrieve_markdown(self, page_id: str) -> str:
        self.calls.append("retrieve_markdown")
        return self.markdown

    def replace_markdown(self, page_id: str, markdown: str) -> None:
        self.calls.append("replace_markdown")
        self.markdown = markdown

    def update_title(self, page_id: str, title_property: str, title: str) -> None:
        self.calls.append("update_title")
        self.title = title


class MarkdownTests(unittest.TestCase):
    def test_notions_empty_blocks_do_not_create_false_difference(self) -> None:
        remote = VALID_MARKDOWN.replace("\n\n", "\n<empty-block/>\n")
        self.assertTrue(sync.markdown_equal(VALID_MARKDOWN, remote))

    def test_notions_tab_indentation_matches_two_space_nested_lists(self) -> None:
        local = "- 관련 API\n  - `GET /api/v1/example`\n"
        remote = "- 관련 API\n\t- `GET /api/v1/example`\n"
        self.assertTrue(sync.markdown_equal(local, remote))

    def test_notion_markdown_escapes_literal_tilde(self) -> None:
        local = "- 점수는 0~100이고 후보는 0~3개입니다.\n"
        self.assertEqual(
            "- 점수는 0\\~100이고 후보는 0\\~3개입니다.\n",
            sync.to_notion_markdown(local),
        )

    def test_notion_markdown_preserves_escaped_tilde_and_markdown_code(self) -> None:
        local = """- 이미 0\\~100으로 이스케이프했습니다.
- `0~100`은 코드입니다.
- ~~제외된 문장~~입니다.

```text
0~100
```
"""
        self.assertEqual(local, sync.to_notion_markdown(local))

    def test_notion_escaped_tilde_does_not_create_false_difference(self) -> None:
        local = "- 점수는 0~100입니다.\n"
        remote = "- 점수는 0\\~100입니다.\n"
        self.assertTrue(sync.markdown_equal(local, remote))

    def test_verification_failure_message_contains_markdown_diff(self) -> None:
        message = sync.verification_failure_message(
            "기능.md",
            "기능",
            "다른 기능",
            "# 기능\n\n- local\n",
            "# 기능\n\n- remote\n",
        )
        self.assertIn("제목 불일치", message)
        self.assertIn("--- local", message)
        self.assertIn("+++ notion", message)
        self.assertIn("- local", message)
        self.assertIn("+- remote", message)

    def test_sync_does_not_retrieve_unchanged_page_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            specs_dir = Path(directory)
            path = specs_dir / "이메일 인증 기능.md"
            path.write_text(VALID_MARKDOWN, encoding="utf-8")
            client = RecordingNotionClient("이메일 인증 기능", VALID_MARKDOWN)
            config = {
                "data_source_id": "data-source",
                "title_property": "이름",
                "mappings": {path.name: {"page_id": "page-id"}},
            }

            with redirect_stdout(io.StringIO()):
                sync.run_remote("sync", client, config, specs_dir, {path: "이메일 인증 기능"})

            self.assertEqual(1, client.calls.count("retrieve_page"))
            self.assertEqual(1, client.calls.count("retrieve_markdown"))
            self.assertNotIn("replace_markdown", client.calls)

    def test_sync_rechecks_only_markdown_after_content_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            specs_dir = Path(directory)
            path = specs_dir / "이메일 인증 기능.md"
            path.write_text(VALID_MARKDOWN, encoding="utf-8")
            client = RecordingNotionClient(
                "이메일 인증 기능",
                VALID_MARKDOWN.replace("- 설명", "- 이전 설명"),
            )
            config = {
                "data_source_id": "data-source",
                "title_property": "이름",
                "mappings": {path.name: {"page_id": "page-id"}},
            }

            with redirect_stdout(io.StringIO()):
                sync.run_remote("sync", client, config, specs_dir, {path: "이메일 인증 기능"})

            self.assertEqual(1, client.calls.count("retrieve_page"))
            self.assertEqual(2, client.calls.count("retrieve_markdown"))
            self.assertEqual(1, client.calls.count("replace_markdown"))

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
