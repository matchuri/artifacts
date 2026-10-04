"""Validate architecture artifact structure, local links and proposed module DAG."""

from pathlib import Path
import re
import sys
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent
REQUIRED_SECTIONS = {
    "backend-module-boundaries.md": (
        "기준과 상태", "현재 의존성", "제안 모듈 경계", "제안 의존성",
        "경계별 정합성", "결정 사항", "근거",
    ),
    "backend-transaction-classification.md": (
        "기준과 상태", "분류 기준", "트랜잭션 분류표", "예외와 커밋",
        "이벤트 전달 정책", "검증 항목", "결정 사항", "근거",
    ),
}


def validate() -> list[str]:
    findings: list[str] = []
    for filename in ("index.md", "templates.md", *REQUIRED_SECTIONS):
        if not (ROOT / filename).is_file():
            findings.append(f"Missing artifact: {filename}")
    for path in sorted(ROOT.glob("*.md")):
        content = path.read_text(encoding="utf-8-sig")
        for heading in REQUIRED_SECTIONS.get(path.name, ()):
            if not re.search(rf"^## {re.escape(heading)}$", content, re.MULTILINE):
                findings.append(f"{path.name}: missing section {heading}")
        in_fence = False
        table_width = None
        identifiers: set[str] = set()
        for number, line in enumerate(content.splitlines(), 1):
            if line.startswith("```"):
                in_fence = not in_fence
                table_width = None
                continue
            if in_fence:
                continue
            for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", line):
                target = match.group(1).strip().strip("<>")
                if target.startswith(("#", "https://", "http://", "mailto:")):
                    continue
                local = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if not (path.parent / local).resolve().exists():
                    findings.append(f"{path.name}:{number}: broken link {target}")
            if line.startswith("|"):
                width = len(re.split(r"(?<!\\)\|", line)) - 2
                if table_width is not None and width != table_width:
                    findings.append(f"{path.name}:{number}: inconsistent table width")
                table_width = width
                identifier = re.match(r"\| ([TDVC]\d{2}) \|", line)
                if identifier:
                    key = identifier.group(1)
                    if key in identifiers:
                        findings.append(f"{path.name}:{number}: duplicate ID {key}")
                    identifiers.add(key)
            else:
                table_width = None
        if in_fence:
            findings.append(f"{path.name}: unclosed code fence")
    path = ROOT / "backend-module-boundaries.md"
    if path.is_file():
        content = path.read_text(encoding="utf-8-sig")
        section = re.search(r"^## 제안 의존성\n(.*?)(?=^## |\Z)", content, re.MULTILINE | re.DOTALL)
        graph = re.search(r"```mermaid\n(.*?)```", section.group(1), re.DOTALL) if section else None
        if not graph:
            findings.append("Missing proposed Mermaid dependency graph")
        else:
            nodes = set(re.findall(r"^\s+([A-Z]+)\[", graph.group(1), re.MULTILINE))
            edges: dict[str, set[str]] = {node: set() for node in nodes}
            for source, targets in re.findall(r"^\s+([A-Z]+) --> ([A-Z]+(?: & [A-Z]+)*)$", graph.group(1), re.MULTILINE):
                for target in targets.split(" & "):
                    if source not in nodes or target not in nodes:
                        findings.append(f"Unknown graph node: {source} -> {target}")
                    else:
                        edges[source].add(target)
            visited: set[str] = set()
            active: set[str] = set()

            def visit(node: str) -> None:
                if node in active:
                    findings.append(f"Proposed dependency cycle through {node}")
                    return
                if node in visited:
                    return
                active.add(node)
                for target in sorted(edges[node]):
                    visit(target)
                active.remove(node)
                visited.add(node)

            for node in sorted(nodes):
                visit(node)
            if not nodes or not any(edges.values()):
                findings.append("Proposed dependency graph is empty")
    return findings


if __name__ == "__main__":
    results = validate()
    print("\n".join(results) if results else "Architecture artifacts: structure, links, tables and proposed DAG OK")
    sys.exit(bool(results))
