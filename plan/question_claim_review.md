# question.md 주장 검토 결과

## 검토 범위
- 기준 문서: `question.md`
- 기준 코드: `modules/`, `tests/` 현재 구현
- 판정 등급: `타당`, `부분 타당`, `비타당`

## 결론 요약
- 핵심 주장 대부분은 타당하며, 이번 반영에서 **비디자인 범위** 중심으로 구현했다.
- 신규 UI 위젯/레이아웃 재설계는 본 구현에서 제외하고 별도 요구사항으로 분리했다.

## 항목별 검토
1. 닫힌 구간 + 변경 구간만 백그라운드 정합성 검사: `타당`
   - 근거: `modules/nf_orchestrator/user_ui.html`의 segment/fingerprint/pending 처리.
   - 반영: 인접 구간 병합 배치 실행 + 실행/대기 상태 텍스트 강화.

2. 위배/unknown 하이라이트 존재: `타당`
   - 근거: CSS Highlight API(`nf-violate`, `nf-unknown`)와 fallback 하이라이트.
   - 반영: 유지(회귀 없음).

3. 의미 기반 옵션은 있으나 벡터는 토큰 오버랩 스텁: `타당`
   - 근거: `modules/nf_retrieval/vector/manifest.py` + `embedder.py` 구현.
   - 반영: `token_overlap` / `hashed_embedding` 백엔드 플러그인화 추가.

4. heavy job 백그라운드 실행 + 동시성/메모리 가드: `타당`
   - 근거: `modules/nf_workers/runner.py` heavy type 제한, 메모리 압력 체크.
   - 반영: 메모리 압력 WARN 이벤트(reason_code) 발행 및 쿨다운 적용.

5. 잡 상태/멈춤 원인 설명 UI 부족: `타당`
   - 근거: 기존 `waitForJob`는 가짜 진행률 폴링 중심.
   - 반영: SSE 우선 + 폴백 폴링, 이벤트 메시지/원인코드 텍스트 반영.

6. UI 옵션 기본값/동작 불일치(checkbox value 사용): `타당(심각)`
   - 근거: `value === 'on'` 방식과 `checked` 상태 불일치.
   - 반영: `checked` 기반 read/write로 전면 수정, 초기 동기화 정리.

7. 고급 옵션 UI 값과 백엔드 계약 불일치: `타당`
   - 근거: UI `on/off` vs 서버 계약(`auto/manual`, `conservative_nli`, `embedding_anomaly`).
   - 반영: UI 옵션 값과 프리셋을 서버 계약값으로 정합화.

8. whitelist/ignore UI 미구현: `비타당`
   - 근거: 기존 카드 액션 + API 연동 이미 구현.
   - 반영: 기존 기능 유지(회귀 방지).

9. tag_path 설명이 메인 결과에 부족: `부분 타당`
   - 근거: 상세에는 있으나 기본 카드 가시성 제한.
   - 반영: `/query/verdicts`에 `tag_path_preview` 추가 및 카드 기본영역 노출.

10. episode 매핑/전파 품질 병목(정규식 버그): `타당`
    - 근거: `r"\\d+"` 오기.
    - 반영: `r"\d+"` 수정 + `metadata.episode_no` 우선 파싱.

## 채택/미채택 정리
- 채택(구현): 1, 2, 3, 4, 5, 6, 7, 9, 10
- 미채택(근거상 비타당): 8

## 비디자인 원칙
- UI 위젯/레이아웃 재설계는 본 범위에서 제외.
- 필요한 디자인 변경점은 `plan/user_ui_widget_design_requirements.md`로 이관.
