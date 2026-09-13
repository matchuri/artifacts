# Matchuri Artifacts

제품 코드 저장소의 상시 컨텍스트에서 분리해야 하는 Matchuri 내부 산출물을 관리하는 독립 Git 저장소입니다.

## 구조

```text
artifacts/
├─ AGENTS.md
├─ README.md
├─ .github/workflows/
├─ scripts/
├─ tests/
└─ specs/
   ├─ features/
   ├─ index.md
   ├─ templates.md
   └─ .notion-sync.json
```

`specs/`는 첫 번째 산출물 도메인일 뿐입니다. 이후 리서치, 보고서, 운영 산출물 등이 필요하면 각각 별도 최상위 디렉터리와 진입점을 추가합니다.

## 기능명세 동기화

`specs/features/*.md`가 기준 원본이고 Notion은 읽기 편한 미러입니다. `main`에 관련 변경이 반영되면 GitHub Actions가 변경 내용을 Notion으로 단방향 동기화합니다. 스케줄 실행과 원격 삭제는 사용하지 않습니다.

저장소의 GitHub Actions secret에 `NOTION_API_KEY`를 등록해야 합니다. 로컬 Infisical의 같은 이름 secret은 GitHub Actions에 자동 전달되지 않습니다.

```powershell
python scripts\sync_notion_specs.py validate
python scripts\sync_notion_specs.py plan --spec "이메일 인증 기능"
python scripts\sync_notion_specs.py sync --spec "이메일 인증 기능"
```

`plan`과 `sync`에는 `NOTION_API_KEY` 환경 변수가 필요합니다. `--spec`을 생략하면 모든 기능명세를 대상으로 합니다. 일상적인 에이전트 작업에서는 로컬 `sync`를 실행하지 않습니다.
