#!/usr/bin/env python3
"""Validate and publish Markdown feature specs to a Notion data source."""

from __future__ import annotations

import argparse
import difflib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "specs" / ".notion-sync.json"
REQUIRED_HEADINGS = ("## 설명", "## 수용 기준", "## 엣지케이스", "## 참고")
SIMILAR_TITLE_THRESHOLD = 0.88


class SyncError(RuntimeError):
    """A safe, user-facing synchronization error."""


class NotionApiError(SyncError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"Notion API {status} {code}: {message}")
        self.status = status


class NotionClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(3):
            request = Request(
                f"{API_BASE}{path}",
                data=data,
                method=method,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Notion-Version": NOTION_VERSION,
                    "Content-Type": "application/json",
                },
            )
            try:
                with urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                try:
                    error = json.loads(body)
                except json.JSONDecodeError:
                    error = {}
                if exc.code == 429 and attempt < 2:
                    delay = float(exc.headers.get("Retry-After", "1"))
                    time.sleep(min(delay, 10))
                    continue
                raise NotionApiError(
                    exc.code,
                    error.get("code", "http_error"),
                    error.get("message", str(exc.reason)),
                ) from exc
            except URLError as exc:
                raise SyncError(f"Notion API 연결 실패: {exc.reason}") from exc
        raise SyncError("Notion API 재시도 한도를 초과했습니다.")

    def retrieve_data_source(self, data_source_id: str) -> dict[str, Any]:
        return self.request("GET", f"/data_sources/{data_source_id}")

    def retrieve_page(self, page_id: str) -> dict[str, Any]:
        return self.request("GET", f"/pages/{page_id}")

    def find_pages(self, data_source_id: str, title_property: str, title: str) -> list[dict[str, Any]]:
        response = self.request(
            "POST",
            f"/data_sources/{data_source_id}/query",
            {"page_size": 100, "filter": {"property": title_property, "title": {"equals": title}}},
        )
        return [item for item in response.get("results", []) if item.get("object") == "page"]

    def list_pages(self, data_source_id: str) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            payload: dict[str, Any] = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            response = self.request("POST", f"/data_sources/{data_source_id}/query", payload)
            pages.extend(item for item in response.get("results", []) if item.get("object") == "page")
            if not response.get("has_more"):
                return pages
            cursor = response.get("next_cursor")
            if not cursor:
                raise SyncError("Notion 페이지 목록의 다음 cursor가 없습니다.")

    def retrieve_markdown(self, page_id: str) -> str:
        response = self.request("GET", f"/pages/{page_id}/markdown")
        if response.get("truncated"):
            raise SyncError("Notion Markdown 응답이 잘려 안전하게 동기화할 수 없습니다.")
        return response.get("markdown", "")

    def replace_markdown(self, page_id: str, markdown: str) -> None:
        self.request(
            "PATCH",
            f"/pages/{page_id}/markdown",
            {
                "type": "replace_content",
                "replace_content": {"new_str": markdown},
                "allow_async": False,
            },
        )

    def update_title(self, page_id: str, title_property: str, title: str) -> None:
        self.request(
            "PATCH",
            f"/pages/{page_id}",
            {
                "properties": {
                    title_property: {
                        "type": "title",
                        "title": [{"type": "text", "text": {"content": title}}],
                    }
                }
            },
        )

    def create_page(self, data_source_id: str, title_property: str, title: str, markdown: str) -> str:
        response = self.request(
            "POST",
            "/pages",
            {
                "parent": {"type": "data_source_id", "data_source_id": data_source_id},
                "properties": {
                    title_property: {
                        "type": "title",
                        "title": [{"type": "text", "text": {"content": title}}],
                    }
                },
                "markdown": markdown,
            },
        )
        page_id = response.get("id")
        if not page_id:
            raise SyncError("Notion이 생성된 페이지 ID를 반환하지 않았습니다.")
        return page_id


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SyncError(f"동기화 설정을 찾을 수 없습니다: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(f"동기화 설정을 읽을 수 없습니다: {path}") from exc
    for key in ("data_source_id", "title_property", "specs_dir"):
        if not config.get(key):
            raise SyncError(f"동기화 설정에 {key} 값이 필요합니다.")
    config.setdefault("mappings", {})
    return config


def save_config(path: Path, config: dict[str, Any]) -> None:
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def specs_directory(config_path: Path, config: dict[str, Any]) -> Path:
    value = Path(config["specs_dir"])
    return (value if value.is_absolute() else config_path.parent / value).resolve()


def normalize_markdown(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def comparison_lines(value: str) -> list[str]:
    return [
        line.expandtabs(2).rstrip()
        for line in normalize_markdown(value).splitlines()
        if line.strip() and line.strip() != "<empty-block/>"
    ]


def markdown_equal(left: str, right: str) -> bool:
    return comparison_lines(left) == comparison_lines(right)


def title_from_markdown(path: Path, markdown: str) -> str:
    for line in normalize_markdown(markdown).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    raise SyncError(f"H1 제목이 없습니다: {path}")


def expandable_reference_line(line: str) -> tuple[str, list[str]] | None:
    if not line.startswith("- ") or ": " not in line:
        return None
    label, value = line[2:].split(": ", 1)
    if label != "관련 데이터" and not label.endswith("API"):
        return None
    items = [item.strip() for item in value.split(", ") if item.strip()]
    return label, items


def format_reference_section(markdown: str) -> str:
    lines = normalize_markdown(markdown).splitlines()
    try:
        reference_index = lines.index("## 참고")
    except ValueError:
        return normalize_markdown(markdown)
    formatted = lines[: reference_index + 1]
    for line in lines[reference_index + 1 :]:
        expandable = expandable_reference_line(line)
        if expandable is None:
            formatted.append(line)
            continue
        label, items = expandable
        formatted.append(f"- {label}")
        formatted.extend(f"  - {item}" for item in items)
    return "\n".join(formatted).strip() + "\n"


def validate_markdown(path: Path, markdown: str) -> str:
    title = title_from_markdown(path, markdown)
    if not title:
        raise SyncError(f"H1 제목이 비어 있습니다: {path}")
    if title != path.stem:
        raise SyncError(f"파일명과 H1 제목이 다릅니다: {path.name!r} != {title!r}")
    lines = [line.strip() for line in normalize_markdown(markdown).splitlines()]
    positions: list[int] = []
    for heading in REQUIRED_HEADINGS:
        count = lines.count(heading)
        if count == 0:
            raise SyncError(f"필수 섹션 {heading!r}이 없습니다: {path}")
        if count > 1:
            raise SyncError(f"필수 섹션 {heading!r}이 중복되었습니다: {path}")
        positions.append(lines.index(heading))
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise SyncError(f"필수 섹션 순서가 올바르지 않습니다: {path}")
    reference_index = lines.index("## 참고")
    for line in normalize_markdown(markdown).splitlines()[reference_index + 1 :]:
        if expandable_reference_line(line):
            raise SyncError(f"참고 항목은 하위 목록으로 줄바꿈해야 합니다: {path}: {line}")
    return title


def resolve_spec(specs_dir: Path, selector: str) -> Path:
    direct = Path(selector)
    candidates = [direct]
    if not direct.is_absolute():
        candidates.extend((specs_dir / direct, specs_dir / f"{selector}.md"))
    matches = list(dict.fromkeys(candidate.resolve() for candidate in candidates if candidate.is_file()))
    if not matches:
        raise SyncError(f"기능명세를 찾을 수 없습니다: {selector}")
    if len(matches) > 1:
        raise SyncError(f"기능명세 경로가 모호합니다: {selector}")
    path = matches[0]
    try:
        path.relative_to(specs_dir)
    except ValueError as exc:
        raise SyncError(f"기능명세 폴더 밖의 파일은 사용할 수 없습니다: {path}") from exc
    return path


def select_specs(specs_dir: Path, selectors: list[str] | None) -> list[Path]:
    paths = [resolve_spec(specs_dir, selector) for selector in selectors] if selectors else sorted(specs_dir.rglob("*.md"))
    if not paths:
        raise SyncError(f"기능명세가 없습니다: {specs_dir}")
    return list(dict.fromkeys(path.resolve() for path in paths))


def validate_specs(paths: Iterable[Path]) -> dict[Path, str]:
    titles: dict[str, Path] = {}
    validated: dict[Path, str] = {}
    for path in paths:
        title = validate_markdown(path, path.read_text(encoding="utf-8"))
        if title in titles:
            raise SyncError(f"중복된 기능명세 제목 {title!r}: {titles[title]}, {path}")
        titles[title] = path
        validated[path] = title
    return validated


def format_specs(paths: Iterable[Path]) -> int:
    changed = 0
    for path in paths:
        before = path.read_text(encoding="utf-8")
        after = format_reference_section(before)
        if after != normalize_markdown(before):
            path.write_text(after, encoding="utf-8")
            changed += 1
    return changed


def validate_remote_schema(client: NotionClient, config: dict[str, Any]) -> None:
    properties = client.retrieve_data_source(config["data_source_id"]).get("properties", {})
    title_property = config["title_property"]
    if properties.get(title_property, {}).get("type") != "title":
        raise SyncError(f"Notion 속성 {title_property!r}이 title 타입이 아닙니다.")


def page_title(page: dict[str, Any], title_property: str) -> str:
    title_items = page.get("properties", {}).get(title_property, {}).get("title", [])
    return "".join(item.get("plain_text") or item.get("text", {}).get("content", "") for item in title_items)


def similar_pages(
    client: NotionClient,
    config: dict[str, Any],
    title: str,
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for page in client.list_pages(config["data_source_id"]):
        remote_title = page_title(page, config["title_property"])
        if not remote_title or remote_title == title or page.get("in_trash") or page.get("archived"):
            continue
        ratio = difflib.SequenceMatcher(None, title, remote_title).ratio()
        if ratio >= SIMILAR_TITLE_THRESHOLD:
            candidates.append({"id": page["id"], "title": remote_title})
    return candidates


def find_page(
    client: NotionClient,
    config: dict[str, Any],
    relative_path: str,
    title: str,
) -> tuple[str | None, str, str]:
    page_id = config["mappings"].get(relative_path, {}).get("page_id")
    if page_id:
        try:
            page = client.retrieve_page(page_id)
            if not page.get("in_trash") and not page.get("archived"):
                return page_id, client.retrieve_markdown(page_id), page_title(page, config["title_property"])
        except NotionApiError as exc:
            if exc.status != 404:
                raise
    pages = client.find_pages(config["data_source_id"], config["title_property"], title)
    if len(pages) > 1:
        raise SyncError(f"제목이 같은 Notion 페이지가 여러 개입니다: {title}")
    if not pages:
        return None, "", ""
    page_id = pages[0]["id"]
    return page_id, client.retrieve_markdown(page_id), page_title(pages[0], config["title_property"])


def bind_spec(
    client: NotionClient,
    config_path: Path,
    config: dict[str, Any],
    specs_dir: Path,
    path: Path,
    remote_title: str,
) -> int:
    validate_remote_schema(client, config)
    pages = client.find_pages(config["data_source_id"], config["title_property"], remote_title)
    if len(pages) != 1:
        raise SyncError(f"Notion 제목 {remote_title!r}의 활성 페이지가 {len(pages)}개입니다. 정확히 1개여야 합니다.")
    relative_path = path.relative_to(specs_dir).as_posix()
    page_id = pages[0]["id"]
    for mapped_path, mapping in list(config["mappings"].items()):
        if mapped_path != relative_path and mapping.get("page_id") == page_id:
            del config["mappings"][mapped_path]
    config["mappings"][relative_path] = {"page_id": page_id}
    save_config(config_path, config)
    print(json.dumps({"command": "bind", "spec": relative_path, "page_id": page_id}, ensure_ascii=False))
    return 0


def notion_client_from_environment() -> NotionClient:
    token = os.environ.get("NOTION_API_KEY", "").strip()
    if not token:
        raise SyncError("NOTION_API_KEY 환경 변수가 필요합니다.")
    return NotionClient(token)


def run_remote(
    command: str,
    client: NotionClient,
    config: dict[str, Any],
    specs_dir: Path,
    validated: dict[Path, str],
    allow_create: bool = False,
) -> int:
    validate_remote_schema(client, config)
    changes = 0
    results: list[dict[str, Any]] = []
    for path, title in validated.items():
        relative_path = path.relative_to(specs_dir).as_posix()
        local = path.read_text(encoding="utf-8")
        page_id, remote, remote_title = find_page(client, config, relative_path, title)
        candidates = similar_pages(client, config, title) if page_id is None else []
        if command == "plan":
            if candidates:
                status = "possible_rename"
            elif page_id is None:
                status = "missing_remote"
            elif remote_title != title or not markdown_equal(local, remote):
                status = "update_required"
            else:
                status = "in_sync"
            changes += status != "in_sync"
            result: dict[str, Any] = {"spec": relative_path, "status": status}
            if candidates:
                result["candidates"] = candidates
            results.append(result)
            continue

        if page_id is None:
            if candidates and not allow_create:
                names = ", ".join(candidate["title"] for candidate in candidates)
                raise SyncError(f"유사한 Notion 페이지가 있어 자동 생성을 중단했습니다: {title} -> {names}")
            page_id = client.create_page(
                config["data_source_id"], config["title_property"], title, normalize_markdown(local)
            )
            status = "created"
        else:
            title_changed = remote_title != title
            content_changed = not markdown_equal(local, remote)
            if title_changed:
                client.update_title(page_id, config["title_property"], title)
            if content_changed:
                client.replace_markdown(page_id, normalize_markdown(local))
            if title_changed and content_changed:
                status = "renamed_and_updated"
            elif title_changed:
                status = "renamed"
            elif content_changed:
                status = "updated"
            else:
                status = "unchanged"
        verified_page = client.retrieve_page(page_id)
        verified = markdown_equal(client.retrieve_markdown(page_id), local) and page_title(
            verified_page, config["title_property"]
        ) == title
        if not verified:
            raise SyncError(f"Notion 반영 검증에 실패했습니다: {relative_path}")
        changes += status != "unchanged"
        results.append({"spec": relative_path, "status": status, "verified": True})

    print(json.dumps({"command": command, "changes": changes, "results": results}, ensure_ascii=False))
    return 1 if command == "plan" and changes else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("format")
    for command in ("plan", "sync", "bind"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument(
            "--spec",
            action="append",
            required=command == "bind",
            help="기능명세 이름 또는 .md 경로; 반복 가능",
        )
        if command == "sync":
            command_parser.add_argument(
                "--allow-create",
                action="store_true",
                help="유사 제목 후보가 있어도 새 Notion 페이지 생성을 허용",
            )
        if command == "bind":
            command_parser.add_argument("--remote-title", required=True, help="연결할 기존 Notion 페이지 제목")
    args = parser.parse_args()

    try:
        config_path = args.config.resolve()
        config = load_config(config_path)
        specs_dir = specs_directory(config_path, config)
        selectors = getattr(args, "spec", None)
        selected = select_specs(specs_dir, selectors)
        if args.command == "format":
            changed = format_specs(selected)
            validated = validate_specs(selected)
            print(json.dumps({"status": "formatted", "changed": changed, "specs": len(validated)}, ensure_ascii=False))
            return 0
        validated = validate_specs(selected)
        if args.command == "validate":
            print(json.dumps({"status": "valid", "specs": len(validated)}, ensure_ascii=False))
            return 0
        client = notion_client_from_environment()
        if args.command == "bind":
            if len(validated) != 1:
                raise SyncError("bind는 --spec 하나만 지정해야 합니다.")
            path = next(iter(validated))
            return bind_spec(client, config_path, config, specs_dir, path, args.remote_title)
        return run_remote(
            args.command,
            client,
            config,
            specs_dir,
            validated,
            allow_create=getattr(args, "allow_create", False),
        )
    except (OSError, UnicodeError, SyncError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
