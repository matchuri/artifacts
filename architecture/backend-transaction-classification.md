# 백엔드 트랜잭션 분류표

## 기준과 상태

- 상태: 전환 전 조사·확정 설계 기록. 현재 선언·코드 흐름은 조사 기록이고, 사용자 결정·수신자 정책·실패 기록 기준은 전환 목표입니다.
- 확인일: 2026-10-05 (Asia/Seoul, 코드 조사 10-04~05).
- backend 기준 커밋: `0f6a966e32da6f41c0f3af81f4320d84d7d3cc96`.
- 코드 근거 링크는 조사 기준 커밋에 고정했습니다. 구현 이후의 개발 기준과 현재 구조는 루트 `docs/`와 backend 코드를 확인합니다.
- 조사 시 backend 작업 트리: 추적 파일 변경 없음, 미추적 `.run/`은 조사 대상 제외.
- [모듈 경계·의존성 지도](./backend-module-boundaries.md)의 확정된 단일 JAR·공유 DB 목표를 사용합니다.
- 표는 업무 흐름별 분류입니다. 모든 private helper, 개별 Repository 호출을 독립 트랜잭션으로 나열하지 않습니다.
- 선언은 소스 기준입니다. 상위 호출의 트랜잭션 참여와 실제 commit/rollback은 프록시를 통과하는 실행으로 검증해야 합니다.
- 기존 로컬 검증: 같은 대화에서 동일 backend 커밋의 전체 테스트 484개 성공, API 계약 90개·JPA 엔티티 34개 감사 finding 0. H2 기반 테스트이며 운영 MySQL 동시성·복구 검증은 별도입니다.
- 외부 계약 제약: API Request/Response 요구사항, HTTP 오류·성공 응답, SSE payload와 성공 시 완료되는 업무 범위를 유지합니다. 실패 시 내부 부분 저장을 정리하는 C02는 오류 응답 형식을 변경하지 않습니다.
- 단계 범위: 현재 lazy expiration 저장 동작과 이벤트 실행 시점 유지. 보상 전략 재정의·동시성 고도화는 이후 작업으로 보류합니다.

## 분류 기준

| 분류 | 의미 | 초기 이벤트 전환 원칙 |
| --- | --- | --- |
| S: 원자적 쓰기 | 요청 완료 시 함께 반영되어야 하는 업무 상태 | 같은 트랜잭션의 직접 호출 또는 공개 명령으로 유지 |
| Q: 순수 조회 | 영속 상태 변경 없이 조회·계산 | 공개 조회 모델로 제공. 이벤트 응답을 기다리는 구조로 바꾸지 않음 |
| L: 저장을 동반하는 조회 | 조회 중 lazy expiration 등 영속 상태 변경 | 현재 쓰기 의미 유지. readOnly·배치 전환은 별도 결정 |
| E: 커밋 후 부수 효과 | 이미 확정된 상태의 알림·정리 | 실패로 본 트랜잭션을 되돌리지 않으며 전달 수준을 별도 정의 |
| X: 외부 연동 | SMTP·스토리지는 DB와 하나의 원자적 자원이 아님 | 호출 시점·DB 기록·보상·재시도 정책을 명시 |
| B: 항목별 배치 | 각 대상의 실패·커밋을 독립 처리 | 전체 배치를 한 트랜잭션으로 확대하지 않음 |

아래의 `W`는 현재 쓰기 허용 `@Transactional`, `R`은 현재 `readOnly=true` 선언입니다.
`W`가 실제 쓰기가 있음을 뜻하지는 않습니다. 메서드 선언이 클래스 선언을 덮어쓰는 경우 함께 반영했습니다.
별도 propagation 지정이 없는 선언은 기본 REQUIRED입니다.

## 트랜잭션 분류표

| ID | 실제 진입점·근거 | 현재 경계와 상태 변경 | 보존할 정합성·제안 분류 | 이벤트 전환 판단 |
| --- | --- | --- | --- | --- |
| T01 | [MemberServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/member/service/MemberServiceImpl.java): `registerLocalMember`, `registerLocalMemberV2`, `createMember` | 메서드 W. 로컬 가입은 이메일 인증 토큰 소비·회원 생성·약관 저장, V2는 취향 초기화 추가 | S: 가입 실패 시 토큰 소비·회원·약관·취향 부분 저장 방지 | identity 내부 유지 |
| T02 | [OAuth2LoginService](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/auth/service/OAuth2LoginService.java): `login` | 메서드 W. 소셜 회원 연결·생성, refresh token·exchange code 저장 | S: 회원과 로그인 결과의 즉시 정합성 | identity 내부 유지 |
| T03 | [AuthServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/auth/service/AuthServiceImpl.java): `login`, `refresh`, `logout`, `exchangeOAuth2Code` | 메서드 W. refresh 저장·교체·제거 또는 exchange code 사용 처리. login은 CAPTCHA 외부 검증 포함 | S, login은 X도 포함. 재발급·코드 소비 결과가 응답 시 확정되어야 함 | 토큰 변경은 동기 유지. 외부 검증 호출 경계는 별도 검토 |
| T04 | [MemberAgreementServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/member/service/MemberAgreementServiceImpl.java): `submitRequiredAgreements` | 메서드 W. 누락 동의 저장 후 revision 기반 access token 발급 | S: 동의 저장과 응답 token의 권한 의미 일치 | identity 내부 유지 |
| T05 | [EmailVerificationServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/auth/service/EmailVerificationServiceImpl.java): `sendVerificationEmail` | W + `noRollbackFor=BusinessException`. 이전 인증 만료·새 이력 저장 후 SMTP 동기 호출, 실패 시 FAILED 기록 후 예외 | S+X: 외부 발송과 DB는 원자적이지 않음. 실패 기록·재전송 cooldown 보존 | 비동기화하면 accepted/발송실패 응답 의미가 달라짐. 초기 유지 |
| T06 | 같은 이메일 서비스: `confirmVerificationEmail` | W + `noRollbackFor=AuthenticationException`. 만료·실패 횟수·FAILED 또는 검증 토큰 기록 | S: 인증 실패 응답에서도 실패 횟수·만료가 저장되는 현재 의미 | identity 내부 유지 |
| T07 | [AccountRecoveryServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/auth/service/AccountRecoveryServiceImpl.java): `findLoginId`, `resetPassword` | 메서드 W. 조회 형태인 findLoginId도 인증 토큰을 소비. resetPassword는 비밀번호·refresh 제거 포함 | S: 인증 토큰 단일 사용과 계정 변경, 후속 실패 시 rollback 보존 | 순수 조회로 오분류하지 않음 |
| T08 | MemberServiceImpl: `updateMyProfile`, `updateMyPassword`, `putMyLocation`, `updateMyTasteProfile`, `setPresetProfileImage` | 메서드 W. 회원·위치·취향·이미지 연결 변경. 카탈로그·이미지 데이터를 직접 읽음 | S: 프로필·취향 매핑의 일괄 변경. 조회 입력은 공개 snapshot으로 대체 가능 | 업무 변경은 identity, 선택 검증은 catalog/media 공개 조회 |
| T09 | MemberServiceImpl: `getMyProfile`, `getHomeMember`, `getMyLocation`, `getMyTasteProfile`; MemberAgreementServiceImpl 조회 메서드 | 대부분 클래스 R. `getMyTasteProfile`은 메서드 W지만 현재 본문은 조회·empty 결과 생성 | Q: 실제 저장 없는 조회. getHomeMember의 개인 추천 저장소 참조는 경계 문제 | 공개 조회 계약. W 선언과 실제 쓰기를 구분 |
| T10 | MemberServiceImpl: `withdraw` → [MemberWithdrawalManager](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/member/support/deletion/MemberWithdrawalManager.java) | 서비스 W. 회원 잠금·DELETED/purgeAt, 소유 그룹 잠금·soft delete, refresh/exchange 삭제 | S: 요청 성공 시 회원·소유 그룹·세션 처리의 현재 즉시성 | app 상위 W + identity/group 공개 명령. 후속 알림만 E 후보 |
| T11 | [MemberPurgeScheduler](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/member/support/deletion/MemberPurgeScheduler.java) → [MemberPurgeService](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/member/service/MemberPurgeService.java): `purgeIfDue` | 스케줄러 자체 선언 없음, 대상별 서비스 W. 회원 잠금·delete/flush, DB FK cascade로 종속 데이터 제거 | B+S: 회원 단위 원자성·삭제 기한·다른 회원 실패 격리 | 공유 DB 삭제 정책 유지. 비동기 연쇄 삭제는 별도 설계 |
| T12 | [RecommendationServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/recommendation/service/RecommendationServiceImpl.java): `createPersonalRecommendation` | W. 기존 추천 만료 확인, 취향·카탈로그·이력 입력 계산, 추천·후보 저장 | S: 추천과 후보 일괄 저장, 실패 시 기본 rollback | 계산은 동기 공개 계약. 결과 저장까지 추천 모듈 소유 |
| T13 | RecommendationServiceImpl: `rerollPersonalRecommendation` | W + `noRollbackFor=BusinessException`. 만료 확인, SKIP 이력·이전 추천 종료 후 새 추천·후보 생성 | S: 이력이 바로 다음 후보 제외에 사용됨. 업무 예외에서 부분 변경 커밋 가능성 검증 필요 | behavior를 초기 추천 모듈에 유지 |
| T14 | RecommendationServiceImpl: `selectPersonalRecommendationCandidate` | W + `noRollbackFor=BusinessException`. 최종 선택·종료·선택적 위치 context·CHOOSE 이력·flush | S: 선택과 다음 추천에 쓰이는 이력 즉시 정합성 | 초기 동일 모듈·트랜잭션 유지 |
| T15 | RecommendationServiceImpl: `getPersonalRecommendation`, `getPersonalRecommendationCandidates`, `getHomeRecommendations`, `getMyPersonalRecommendations`, `getMyPersonalRecommendationHistories` | 클래스 W. 조회 중 EXPIRED 상태 기록 | L: 조회가 만료 상태를 저장하는 현재 동작 보존 | 즉시 readOnly 전환 금지. 만료 갱신 분리는 별도 결정 |
| T16 | RecommendationServiceImpl: `createGuestPersonalRecommendation` | 메서드 R. 카탈로그 조회·추천 계산·썸네일 조합, 추천 저장 없음 | Q: 저장 없는 비회원 흐름 | 동기 조회·계산 유지 |
| T17 | [GroupManagementServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/group/service/impl/GroupManagementServiceImpl.java): `createGroup`, `updateGroup`, `leaveGroup`, `deleteGroup` | 클래스/메서드 W. 방·OWNER membership·위치·퇴장·초대/링크 정리. delete는 방 잠금과 삭제 전 수신자 snapshot | S: 방·멤버십·초대 정합성. 퇴장/삭제 SSE는 커밋 후 | group 내부 명령 유지, 알림 E |
| T18 | [GroupInviteServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/group/service/impl/GroupInviteServiceImpl.java): `createNicknameInvite`, `createInviteLink`, `reissueInviteLink`, `joinGroupByInviteLink`, `joinGroup`, `respondGroupInvite` | 클래스 W. 초대·기존 링크 만료·초대 수락/거절·membership 생성/재활성화 | S: 수락/입장과 membership 일괄 반영, 재발급 시 이전 링크 효력 제거 | group 내부 유지, 초대 생성·참여 알림 E |
| T19 | GroupInviteServiceImpl: `getCurrentInviteLink`, `previewInviteLink`, `getMyInvites`, `getMyInvitesV2`, `existsMyPendingInvite` | 메서드 R. 유효한 초대·그룹·회원 조회 | Q: 시간 유효성 조회와 저장형 만료 처리 구분 | 공개 조회 계약 |
| T20 | [GroupRecommendationServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/group/service/impl/GroupRecommendationServiceImpl.java): `createGroupRecommendation` | 클래스 W. 이전 추천 lazy expiration, 활성 추천 검증, 위치·PREPARING 추천 저장, 시작 이벤트 발행 | S: 활성 실행 규칙과 세션 저장. 기본 rollback | group 내부 유지, 시작 알림 E |
| T21 | GroupRecommendationServiceImpl: `readyGroupRecommendation` | W + `noRollbackFor=BusinessException`. readiness 저장, 전원 준비면 후보·카테고리 저장·OPEN 전이, 준비/열림 이벤트 발행 | S: 마지막 준비·후보 생성·OPEN 전이의 즉시성. 업무 예외 이후 상태 확인 필요 | 후보 생성을 비동기로 바꾸려면 새 중간 상태·API 정책 결정 필요 |
| T22 | GroupRecommendationServiceImpl: `voteGroupRecommendation` | W + `noRollbackFor=BusinessException`. 후보 검증, 기존 투표 변경/신규 저장·flush, 진행률 계산, 투표/전원완료 이벤트 | S: 세션별 회원 1표·재투표 규칙·상태 유효성, 동시 확정과의 경쟁 검증 | 투표 저장은 group, 진행 알림 E |
| T23 | GroupRecommendationServiceImpl: `finalizeGroupRecommendation` | W + `noRollbackFor=BusinessException`. OWNER·OPEN·후보 검증, 집계·최종 후보/시간·context 저장, 확정 이벤트 | S: 후보·집계·최종 상태 확정, 실패 후 알림 금지 | 첫 이벤트 경계 정리 후보. 확정 S, 화면 알림 E |
| T24 | 그룹 조회: GroupRecommendationServiceImpl의 `getGroupRecommendation`, `getGroupRecommendationCandidates`, `getGroupRecommendations`, `getGroupRecommendationsV2`, `getGroupRecommendationReadiness`, `getHomeActivities`; GroupManagementServiceImpl 조회 흐름 | 클래스 W. 추천 조회·홈 활동과 그룹 목록/상세에서 lazy expiration 실행. 후보 조회만 명시적 `noRollbackFor=BusinessException` | L: 조회 중 만료 저장과 예외 시의 커밋 의미 보존 | 조회 이름만으로 R 지정하지 않음 |
| T25 | [CommonApplicationService](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/common/service/CommonApplicationService.java): `getHome` | 메서드 W. 회원·개인 추천·그룹 활동을 호출하고 API HomeResponse 매핑. 하위 추천 흐름이 만료 상태 변경 | L: 홈 조합 시 현재 만료 반영 보존 | app 조합으로 이동. 초기 상위 쓰기 트랜잭션 유지 |
| T26 | [RealtimeEventService](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/realtime/service/RealtimeEventService.java): 연결; [RealtimeDomainEventListener](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/realtime/service/RealtimeDomainEventListener.java): 10개 handle | 연결은 R로 회원·멤버십 확인 후 인메모리 등록. handle은 AFTER_COMMIT, 자체 W·Async 선언 없음. 일부는 그룹 활성 회원을 Repository로 조회 | Q+E: DB 상태 확정 뒤 SSE 전달, 송신 실패 시 registry 연결 정리. 영속 전달 기록 없음 | 공개 수신자 조회 계약 사용. DB를 쓰는 후속 listener에는 새 트랜잭션 경계 필요 |
| T27 | [MenuImageAdminServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/menu/service/MenuImageAdminServiceImpl.java): `uploadPrimaryImage`; [PresetProfileImageAdminServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/image/service/PresetProfileImageAdminServiceImpl.java): `upload` | 진입점 @Transactional 없음. 객체 업로드 후 TransactionTemplate로 자산·연결 저장, DB 실패 시 신규 객체 삭제 보상 | X+S: 외부 업로드 성공과 DB 성공이 다름. 보상 실패 로그·잔여 객체 정책 유지 | 외부 I/O를 상위 W 안으로 무심코 감싸지 않음 |
| T28 | MenuImageAdminServiceImpl: `deletePrimaryImage`, 교체 이미지 정리 | 삭제는 메서드 W. 메뉴 이미지 연결 제거·자산 deleted, afterCommit에서 R2 객체 삭제. 실패는 로그 후 수용 | S+E+X: DB 커밋 후 객체 정리, 정리 실패가 DB 결과를 되돌리지 않음 | 현재 best-effort 유지 또는 내구성 있는 정리 작업으로 별도 결정 |
| T29 | PresetProfileImageAdminServiceImpl: `setDefault`, `delete` | 메서드 W + 활성 프리셋 잠금. delete는 soft delete 후 MemberProfileImageRepository로 사용 회원 연결을 기본 자산으로 갱신 | S: 기본 프리셋 규칙, 삭제된 프리셋 사용 회원 전원을 기본 이미지로 재지정 | app W + media/identity 공개 명령. 요청 완료 시 전원 재지정 유지 |
| T30 | [MenuReferenceServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/menu/service/MenuReferenceServiceImpl.java), [MenuAdminReferenceServiceImpl](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/menu/service/MenuAdminReferenceServiceImpl.java) | 기준 조회는 클래스 R. 생성·갱신·매핑·비활성 메서드는 W | Q/S: 카탈로그 검증·참조·비활성 정책 보존 | catalog 내부. 요청 시 필요한 활성 데이터는 공개 조회 |
| T31 | [ReferenceDataSeedService](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/infra/seed/ReferenceDataSeedService.java), [LocalSampleDataSeedService](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/infra/seed/LocalSampleDataSeedService.java), [LocalMenuImageSeedService](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/infra/seed/LocalMenuImageSeedService.java), [PresetProfileImageSeedService](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/infra/seed/PresetProfileImageSeedService.java) | 초기화 서비스 W. 여러 도메인 저장소에 기준·개발 데이터 기록 | S: 누락만 생성·반복 실행 안전성·profile 범위 보존 | app 기동 조합 + 각 소유 모듈의 seed 공개 명령 |

## 예외와 커밋

현재 `noRollbackFor`는 아래 경로에서 명시됩니다. 오류 응답이 항상 rollback을 뜻하지 않습니다.
이 표는 현재 소스의 조사 기록이며 아래 C02 적용 기준으로 후속 구현에서 범위를 정리합니다.

| 경로 | rollback 제외 예외 | 확인할 의미 |
| --- | --- | --- |
| 이메일 발송 | `BusinessException` | 중복 거절 시 이전 이력 만료, SMTP 실패 시 FAILED 기록 보존 |
| 이메일 확인 | `AuthenticationException` | 틀린 코드·만료·시도 초과의 상태 기록 보존 |
| 개인 재요청·최종 선택 | `BusinessException` | EXPIRED 기록 보존과 기타 업무 예외 이후 부분 변경 확인 |
| 그룹 후보 조회·준비·투표·최종 확정 | `BusinessException` | EXPIRED 기록 보존과 기타 업무 예외 이후 부분 변경 확인 |

일반 W의 런타임 예외는 기본 rollback 대상입니다. 현재 예외 제외 규칙은 소스 선언 그대로 기록한 것이며 그 적절성을 승인한 것은 아닙니다.
`noRollbackFor`가 메서드 전체에 적용되므로 만료 갱신 외의 변경도 남을 수 있습니다. 특정 오류를 의도된 만료 저장으로 볼지 실제 동작 테스트로 확인해야 합니다.
상위 REQUIRED 트랜잭션이 rollback-only가 된 경우 하위 `noRollbackFor`가 이를 취소하지 않습니다.

기본 REQUIRED 하위 서비스는 app 상위 트랜잭션에 참여하도록 구성할 수 있습니다.
반면 같은 객체 안의 자기 호출, 직접 new로 만든 listener 테스트, 트랜잭션 밖에서 발행한 이벤트는 프록시·트랜잭션 이벤트 동작을 증명하지 않습니다.

### C02 확정: 실패 시 보존할 기록

아래의 기존 업무상 실패 기록만 보존 대상으로 명시합니다. 단순히 BusinessException이라는 이유로 업무 변경 전체를 commit하지 않습니다.

| 실패 조건 | 보존할 기록 | 함께 rollback할 업무 변경 |
| --- | --- | --- |
| 이메일 인증 요청의 중복 가입 거절·새 발송 실패 | 해당 실패 흐름에서 기존 PENDING 인증을 만료 처리한 기록, 발송 실패 이력의 FAILED 상태 | 실패 기록과 무관한 회원·약관·취향·토큰·다른 업무 변경 |
| 이메일 인증 코드 불일치·기한 만료·시도 초과 | 해당 인증의 실패 횟수, EXPIRED/FAILED 상태 | 성공 검증 토큰 발급·소비와 다른 업무 변경 |
| 개인·그룹 추천 사용/조회에서 만료를 발견 | 해당 추천의 EXPIRED 상태와 만료 시각. 기존 저장형 조회 의미 유지 | 재요청의 SKIP/이전 종료/새 후보, 준비 상태·OPEN 전이·후보, 투표·최종 선택·context 등 일반 업무 변경 |
| 그 밖의 업무 검증·저장 실패 | 기존 운영 로그. 새로운 영속 실패 이력은 추가하지 않음 | 유스케이스의 일반 업무 변경 전체 |

일반 업무 변경은 같은 트랜잭션으로 rollback하고, 실패 기록은 해당 대상·실패 조건을 식별해 보존합니다.
구현 시 실패 기록의 저장 경계를 업무 rollback 경계와 분리하되 잠금·상위 트랜잭션의 영향을 확인합니다.
API 오류 코드·HTTP 상태·응답 envelope는 유지합니다. 가입/복구 인증 토큰 소비는 실패 기록이 아니므로 업무 실패 시 rollback합니다.

## 이벤트 전달 정책

### 현재 사실

- 그룹 서비스가 Spring `ApplicationEventPublisher`로 10종의 realtime 이벤트를 발행합니다. 같은 이벤트 타입이 여러 진입점에서 발행될 수 있습니다.
- 그룹 상태 변경은 원본 서비스 트랜잭션 안에서 실행하고 SSE 변환은 AFTER_COMMIT listener가 수행합니다.
- Async 선언과 전달 영속 기록이 없습니다. AFTER_COMMIT은 실행 시점이며 비동기·유실 방지 보장을 뜻하지 않습니다.
- SSE 계약은 오프라인 저장과 Last-Event-ID 재전송을 제공하지 않습니다. 서버 재시작 후 registry 연결도 복구되지 않습니다.
- 소비자 처리 성공과 클라이언트 수신 성공은 다릅니다. 현 registry는 일부 송신 예외를 기록·정리하고 반환하므로 listener 성공만으로 화면 전달을 보장할 수 없습니다.

### 제안

| 처리 | 시점·트랜잭션 | 전달 수준·실패 정책 |
| --- | --- | --- |
| 투표·후보·최종 확정·탈퇴 접근 차단·이력 저장 | 요청 트랜잭션 S | 기존 즉시 정합성 유지. 처리 실패 시 정의된 rollback/오류 의미 유지 |
| 그룹 도메인 이벤트 → 현재 SSE 변환 | 업무 커밋 이후 E | 현행 best-effort 기준. 오프라인·유실 시 REST 상태가 최종 기준 |
| 향후 반드시 완료해야 하는 다른 모듈의 상태 변경 | 커밋 후 별도 트랜잭션 | 업무와 같은 트랜잭션에 전달 기록 저장, 재처리·멱등성·실패 관측 설계 필요 |
| 이미지 객체 정리 | DB 커밋 이후 E/X | 현재 로그 기반 best-effort. 지속 실패를 복구해야 하면 영속 정리 작업 도입 판단 |
| 인증 이메일 비동기 발송 | 현재 동기 X를 변경하는 별도 결정 | 응답 계약·유효기간·cooldown·만료된 발송 작업·민감 payload 보관 정책을 먼저 정의 |

도메인 이벤트는 발행 모듈의 사실을 표현하고 SSE event type·payload는 전송 계약으로 변환합니다.
Entity·Lazy proxy·API 응답 DTO 대신 ID와 필요한 불변 snapshot을 사용합니다.
영속 처리가 필요한 이벤트의 계약 후보는 `eventId`, `occurredAt`, 업무 대상 ID, 필요 시 대상 version·schema version입니다.
`eventId` 생성과 재시도 시 동일 ID 유지, 소비자별 중복 방지 키·업무 unique 제약을 함께 정의합니다.

Async를 추가하면 같은 세션에서 여러 이벤트가 역순 도착할 수 있으므로 대상 version 검증이나 직렬 처리 정책이 필요합니다.
수신 대상 snapshot과 전송 시의 현재 접근 권한은 별개입니다. 퇴장·삭제 이후 민감 payload 수신 가능성을 경계별로 검증합니다.
현재 그룹 삭제는 삭제 전 대상 목록을 이벤트에 담고, 다른 많은 알림은 소비 시점의 활성 회원을 조회합니다. 이를 바꾸면 수신자 정책도 달라집니다.

Spring Modulith는 이번 단계에서 모듈 경계 정의·검증에 사용합니다.
Event Publication Registry 또는 Outbox를 통한 보상·영속 전달·재처리는 C04에 따라 이후 별도 설계 대상으로 보류합니다.
SSE 연결 자체의 재전송 보장은 별도 전송 계약이며 이 도구를 채택했다는 이유만으로 생기지 않습니다.
현행 AFTER_COMMIT 실행 시점·SSE best-effort를 유지하며 broker·명시적 비동기화·새 전달 수준은 이번 단계에 도입하지 않습니다.

### C05 확정: 수신 대상과 권한

에이전트 결정: 그룹의 일반 상태 알림은 전송 시점의 현재 접근 권한을 기준으로 하고, 삭제 종료 알림만 삭제 직전 대상 snapshot을 사용합니다.
이는 전환 목표입니다. 기존 직접 Repository 참조를 공개 조회 계약으로 바꾸는 단계에서 적용하며 아직 코드에 구현하지 않았습니다.

| 이벤트·경계 | 대상 선정·전송 시 확인 | 처리 |
| --- | --- | --- |
| SSE 연결 | 현재 ACTIVE 회원, 그룹 연결은 현재 ACTIVE membership과 삭제되지 않은 그룹 | 기존 연결 API의 request/response·오류 계약 유지 |
| 그룹 참여·퇴장·준비·후보·투표·확정 | 전송 시 삭제되지 않은 그룹의 ACTIVE membership 및 ACTIVE 회원 | group 공개 조회가 수신자 ID를 제공. 현재 권한 없는 그룹 연결에는 payload를 보내지 않고 정리 |
| GROUP_DELETED | 삭제 트랜잭션에서 캡처한 삭제 직전 활성 수신자, 전송 시 회원 ACTIVE 여부 확인 | 삭제 때문에 membership이 LEFT가 된 대상을 제외하지 않음. 기존 종료 payload를 보낸 후 해당 그룹 연결 정리 |
| GROUP_INVITE_CREATED | event의 지정 대상 회원. 전송 시 ACTIVE 회원·유효한 PENDING 초대·삭제되지 않은 그룹 확인 | 유효하지 않으면 알림 생략. 개인 stream과 외부 payload 유지 |
| GROUP_RECOMMENDATION_VOTE_COMPLETED | event의 지정 대상이 전송 시 ACTIVE 회원·현재 그룹 OWNER·ACTIVE membership인지 확인 | 다른 회원에게 전송하거나 새 OWNER로 임의 전환하지 않음. 조건 불충족이면 생략 |

대상 조회는 group/identity 공개 계약에서 수행하고 realtime은 Entity·Repository를 직접 참조하지 않습니다.
일반 그룹 알림의 ACTIVE 회원·membership 필터와 삭제 알림의 snapshot은 현재 흐름을 유지하고, 그룹 유효성·개인 대상 재확인·연결 정리를 경계에 명시합니다.
이는 송신 직전의 권한 확인이며 조회와 socket 송신 사이의 완전한 동시성 직렬화를 보장하지 않습니다.
C06에 따라 새 잠금·상태 version·직렬 큐·경쟁 상황 전용 개선을 이번 단계에 추가하지 않습니다.

## 검증 항목

아래는 후속 리팩토링의 수용 기준이며 이번 문서 작성에서 새로 실행한 동작 테스트가 아닙니다.
기존 동작은 필요한 통합 테스트로, 정책 분기는 순수 단위 테스트로 검증합니다.

| ID | 동작 시나리오 | 기대 결과 |
| --- | --- | --- |
| V01 | 업무 트랜잭션 성공/실패 뒤 실제 이벤트 소비 | commit이면 정확한 payload 전달, rollback이면 AFTER_COMMIT 소비 없음 |
| V02 | 만료된 개인·그룹 조회와 명시적 업무 예외 | 각 진입점의 기존 만료 저장/rollback 의미 유지 |
| V03 | 개인 재요청·그룹 준비 도중 계산/검증 실패 | noRollbackFor 적용 시 남는 이전 종료·이력·준비 상태를 확인하고 의도된 결과만 승인 |
| V04 | 보류: 마지막 준비 동시 요청, 투표와 확정 경쟁, 중복 활성 추천 생성의 신규 검증 | C06에 따라 이후 동시성 개선 범위. 이번 단계는 기존 unique·lock·재투표 검증과 관련 테스트 보존 |
| V05 | 탈퇴에서 소유 그룹 변경 실패 또는 토큰 제거 실패 | 상위 유스케이스의 정의된 원자성, 탈퇴 직후 인증·그룹 접근 차단 유지 |
| V06 | 가입/계정 복구 후속 검증 실패와 토큰 재사용 | 인증 토큰 소비와 회원·비밀번호 변경의 rollback 및 단일 사용 의미 유지 |
| V07 | 기본 프리셋 변경·프리셋 삭제·다수 회원 사용 | 기본 최대 1개·기본 삭제 제한, 삭제된 프리셋 사용 회원 전원 기본 이미지 재지정. 선택 경쟁의 새 검증은 후속 범위 |
| V08 | 이미지 업로드 성공 후 DB 실패, 커밋 후 객체 삭제 실패 | 신규 객체 보상 시도, DB 상태 보존, 실패 원인 추적 가능 |
| V09 | SSE sender 실패·종료·연결 없는 수신자 | 이미 완료한 업무 상태 보존, 기존 외부 payload·event type·권한 경계 유지 |
| V10 | 보류: 영속 소비자를 채택한 경우 재시작·재처리·중복/역순 delivery | C04의 보상 전략 재정의 때 적용. 이번 단계에서 새 영속 소비자 도입 없음 |
| V11 | purge 기한 전/후, 여러 종속 데이터와 한 대상 실패 | 기한 준수·DB cascade·다른 대상 처리 유지 |
| V12 | 모듈 추출 뒤 전체 context·bootJar 실행·홈/추천 조회 | bean/entity/repository 스캔·QueryDSL 생성·기존 HTTP/SSE 계약 확인. 성능 최적화는 D05의 후속 범위 |
| V13 | 일반 그룹 알림 이후 퇴장·회원 비활성, 삭제 종료 알림, 개인 초대·OWNER 알림의 대상 검증 | C05의 현재 권한 필터·삭제 snapshot 예외·개인 지정 대상 정책을 순차 상태 변경 테스트로 검증 |
| V14 | 기존 HTTP request/response 정상·실패 흐름 | 필드·타입·필수성·null, 상태 코드·오류 코드·응답 envelope, 성공 시 업무 완료 의미 보존. Swagger 산출물 전용 테스트 대신 실제 API 통합 테스트 사용 |

현재 GroupRecommendationRepository의 일반 세션 조회에 명시적 비관 잠금이 없고,
GroupRecommendation Entity에도 @Version 선언이 확인되지 않았습니다. 동시성의 안전성을 현재 테스트 성공만으로 단정하지 않습니다.
현재 RealtimeDomainEventListenerTest는 listener를 직접 생성·호출하는 단위 테스트이므로 V01의 실제 commit/rollback 검증을 추가할 필요가 있습니다.

## 결정 사항

| ID | 항목 | 확정 내용·이번 단계 범위 |
| --- | --- | --- |
| C01 | 프리셋 삭제 | 사용자 확정: 삭제된 프리셋 사용 회원 전원을 기본 이미지로 재지정. 다른 프리셋 사용 회원까지 초기화하지 않음 |
| C02 | 실패 기록과 rollback | 사용자 원칙 + 위 보존 대상 목록: 명시된 실패 기록만 보존, 나머지 업무 변경 함께 rollback. 구현 대기 |
| C03 | API 성공 의미 | 사용자 확정: 성공 응답 스펙·완료 시점·현재 업무 완료 범위 유지. 전체 Request/Response 요구사항 변경 금지 |
| C04 | 이벤트 보상 전략 | 사용자 보류: 이후 재정의. 이번에는 기존 best-effort·기존 이미지 보상 처리 유지 |
| C05 | 수신 대상·권한 | 위 에이전트 정책 확정: 전송 시 현재 권한, 그룹 삭제는 삭제 직전 snapshot 예외, 개인 알림은 지정 대상 재확인. 구현 대기 |
| C06 | 동시성 | 사용자 보류: 새로운 동시성 개선·대규모 경쟁 검증은 후속 작업. 기존 제약·잠금은 유지 |

## 근거

- [트랜잭션 구현 규칙](../../../docs/backend/guide.md), [데이터 보존·만료·삭제 정책](../../../docs/data/policies.md), [SSE 전달 계약](../../../docs/api/realtime.md).
- [인증 토큰 소비·회전](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/auth/support/token/SessionTokenService.java), [이메일 인증 토큰 소비](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/auth/support/verification/EmailVerificationTokenVerifier.java).
- [그룹 만료 갱신](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/group/support/recommendation/GroupRecommendationExpirationManager.java), [일반 세션 조회](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/group/repository/GroupRecommendationRepository.java), [추천 상태 엔티티](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/group/entity/GroupRecommendation.java).
- [투표 unique 제약](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/group/entity/GroupRecommendationVote.java), [SSE 송신 실패 처리](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/main/java/matchuri/backend/domain/realtime/support/RealtimeSseEmitterRegistry.java).
- [현재 listener 단위 테스트](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/test/java/matchuri/backend/domain/realtime/service/RealtimeDomainEventListenerTest.java), [회원 삭제 통합 테스트](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/test/java/matchuri/backend/domain/member/MemberDeletionIntegrationTest.java), [그룹 HTTP 통합 테스트](https://github.com/matchuri/backend/blob/0f6a966e32da6f41c0f3af81f4320d84d7d3cc96/src/test/java/matchuri/backend/api/group/GroupIntegrationTest.java).
- [Spring 트랜잭션 이벤트](https://docs.spring.io/spring-framework/reference/data-access/transaction/event.html): commit phase와 트랜잭션 없는 발행의 listener 의미.
- [Spring Modulith 이벤트 처리](https://docs.spring.io/spring-modulith/reference/events.html): 기본 동기 발행, 비동기 실패 위험과 트랜잭션 내 전달 기록·재처리의 도구 근거.
