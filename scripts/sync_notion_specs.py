#!/usr/bin/env python3
"""Validate and publish Markdown feature specs to a Notion data source."""

from __future__ import annotations

import argparse
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

    def find_pages(self, data_source_id: str, title_property: str, title: str) -> list[dict[str, Any]]:
        response = self.request(
            "POST",
            f"/data_sources/{data_source_id}/query",
            {"page_size": 100, "filter": {"property": title_property, "title": {"equals": title}}},
        )
        return [item for item in response.get("results", []) if item.get("object") == "page"]

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


def specs_directory(config_path: Path, config: dict[str, Any]) -> Path:
    value = Path(config["specs_dir"])
    return (value if value.is_absolute() else config_path.parent / value).resolve()


def normalize_markdown(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def comparison_lines(value: str) -> list[str]:
    return [
        line.rstrip()
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


def validate_markdown(path: Path, markdown: str) -> str:
    title = title_from_markdown(path, markdown)
    if not title:
        raise SyncError(f"H1 제목이 비어 있습니다: {path}")
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


def validate_remote_schema(client: NotionClient, config: dict[str, Any]) -> None:
    properties = client.retrieve_data_source(config["data_source_id"]).get("properties", {})
    title_property = config["title_property"]
    if properties.get(title_property, {}).get("type") != "title":
        raise SyncError(f"Notion 속성 {title_property!r}이 title 타입이 아닙니다.")


def find_page(
    client: NotionClient,
    config: dict[str, Any],
    relative_path: str,
    title: str,
) -> tuple[str | None, str]:
    page_id = config["mappings"].get(relative_path, {}).get("page_id")
    if page_id:
        try:
            return page_id, client.retrieve_markdown(page_id)
        except NotionApiError as exc:
            if exc.status != 404:
                raise
    pages = client.find_pages(config["data_source_id"], config["title_property"], title)
    if len(pages) > 1:
        raise SyncError(f"제목이 같은 Notion 페이지가 여러 개입니다: {title}")
    if not pages:
        return None, ""
    page_id = pages[0]["id"]
    return page_id, client.retrieve_markdown(page_id)


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
) -> int:
    validate_remote_schema(client, config)
    changes = 0
    results: list[dict[str, Any]] = []
    for path, title in validated.items():
        relative_path = path.relative_to(specs_dir).as_posix()
        local = path.read_text(encoding="utf-8")
        page_id, remote = find_page(client, config, relative_path, title)
        if command == "plan":
            status = "missing_remote" if page_id is None else "in_sync" if markdown_equal(local, remote) else "update_required"
            changes += status != "in_sync"
            results.append({"spec": relative_path, "status": status})
            continue

        if page_id is None:
            page_id = client.create_page(
                config["data_source_id"], config["title_property"], title, normalize_markdown(local)
            )
            status = "created"
        elif markdown_equal(local, remote):
            status = "unchanged"
        else:
            client.replace_markdown(page_id, normalize_markdown(local))
            status = "updated"
        verified = markdown_equal(client.retrieve_markdown(page_id), local)
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
    for command in ("plan", "sync"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--spec", action="append", help="기능명세 이름 또는 .md 경로; 반복 가능")
    args = parser.parse_args()

    try:
        config_path = args.config.resolve()
        config = load_config(config_path)
        specs_dir = specs_directory(config_path, config)
        selectors = getattr(args, "spec", None)
        selected = select_specs(specs_dir, selectors)
        validated = validate_specs(selected)
        if args.command == "validate":
            print(json.dumps({"status": "valid", "specs": len(validated)}, ensure_ascii=False))
            return 0
        return run_remote(args.command, notion_client_from_environment(), config, specs_dir, validated)
    except (OSError, UnicodeError, SyncError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
