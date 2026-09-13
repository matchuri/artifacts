# 기능명세

Matchuri의 상세 기능 동작, 수용 기준, 엣지케이스를 관리합니다.

## 기준과 경계

- 기준 원본은 `features/*.md`입니다.
- 새 문서는 `templates.md`를 복사해 작성합니다.
- Notion은 GitHub Actions가 갱신하는 단방향 미러입니다.
- Notion에서 직접 수정한 내용은 이 저장소로 역동기화하지 않습니다.
- 원격 페이지 삭제·보관은 자동화하지 않습니다.

## 검증과 배포

```powershell
python scripts\sync_notion_specs.py validate
python -m unittest discover -s tests -p "test_*.py"
```

Pull request에서는 형식과 테스트만 검증합니다. `main`에 관련 파일이 반영되거나 수동 실행할 때만 Notion 동기화가 수행됩니다.
