# Matchuri Artifacts Agent Router

이 저장소는 Matchuri 루트, backend, frontend와 분리된 내부 산출물 저장소입니다. 일반 개발 작업의 상시 컨텍스트가 아니며, 사용자가 내부 산출물 작성·감사·동기화를 명시적으로 요청했을 때만 엽니다.

## 기본 원칙

- 요청된 최상위 도메인과 그 진입점만 읽습니다. 저장소 전체를 선행 탐색하지 않습니다.
- 새 산출물 종류는 최상위 디렉터리로 분리하고 자체 `index.md`, 템플릿, 검증 규칙을 둡니다.
- 자격 증명은 커밋하지 않습니다. 로컬 실행은 환경 변수, CI는 GitHub Actions secret을 사용합니다.
- 외부 문서 도구는 배포 대상입니다. 동기화 방향과 기준 원본은 각 도메인에서 명시합니다.

## 기능명세

- 진입점: `specs/index.md`
- 상세 기능명세 기준 원본: `specs/features/*.md`
- 템플릿: `specs/templates.md`
- Notion 동기화: `scripts/sync_notion_specs.py`
- Notion은 Markdown의 단방향 미러이며 직접 편집한 내용은 기준이 아닙니다.
- Notion 호환성을 위해 기능명세의 `참고 > 관련 기능`은 링크 없이 기능명만 일반 텍스트로 적습니다. 로컬 파일·상대경로 링크를 사용하지 않습니다.
- 에이전트는 명세와 자동화 코드를 작성·검증합니다. 실제 동기화는 GitHub Actions가 수행합니다.
- 자동화는 원격 페이지를 삭제하거나 보관 처리하지 않습니다.

## 검증

```powershell
python scripts\sync_notion_specs.py validate
python scripts\sync_notion_specs.py format
python -m unittest discover -s tests -p "test_*.py"
```
