# 미정/유저 승인 필요 항목 (결정/차순위 계획 로그)

> 구현 순서(Phase) 통제: `plan/IMPLEMENTATION_CHECKLIST.md` (본 문서는 결정/승인/옵트인만 추적)

이 문서는 `plan/*` 설계 문서에서 **정합성/서술 누락이 아니라**,
정책 선택이 필요하거나 **유저 승인/옵트인**이 필요한 항목을 정리합니다.

각 항목은:

* **1차(우선) 결정**: MVP/1차 배포에 반영
* **2차(차순위) 계획**: optional/추후 확장으로 구체화

> 변경/결정이 확정되면 이 문서에서 해당 항목을 “결정됨”으로 옮기고,
> 관련 설계/체크리스트 문서(`architecture_*.md`, `TODO.md`)를 갱신하는 것을 목표로 합니다.

---

## D1) 문법 교정 / “자간·줄간격” 교정의 의미와 범위

- 근거: `plan/user_request.md:8`, `plan/user_request.md:10`
- 1차(우선) 결정
  - `자간/줄간격`은 **교정이 아니라 레이아웃 설정(Editor Settings)** 으로 규정
  - `띄어쓰기/문장부호`는 **문법(Proofread/Grammar) 범위**로 이관
  - 실행 방식은 **실시간 표시(에디터 내 lint/underline)** 를 기준으로 함
  - 모델 기반 교정은 1차에서 제외
- 2차(차순위) 계획
  - 모델 기반 문법 교정(옵트인): 로컬/원격 중 택1, “근거/규칙 위반” 중심으로 제한
  - 대용량 문서/전체 범위에 대한 `PROOFREAD` batch job(선택): UI는 결과 스트리밍으로 표시

---

## D2) `tag_path` vs `entity_id`(정규화) — “인물/장소 동일성” 표현 방식

- 근거: `plan/architecture_2.md:213`, `plan/user_request.md:50`, `plan/TODO.md:99`
- 결정이 필요한 이유: 예시 `tag_path`는 `설정/인물/주인공/나이`처럼 **엔티티 이름을 경로에 포함**하지만,
  스키마 팩트에는 `entity_id`도 등장합니다(중복/정규화 정책 미정).
- 1차(우선) 결정: **옵션 2**
  - MVP부터 `entity`/`entity_alias`를 도입하고 가능한 경우 `entity_id`를 채움
  - 단, 불명확/충돌 시에는 **보수적으로 unknown/미지정 처리**(판단 회피)
- 2차(차순위) 계획
  - identity resolution 고도화(동명이인/호칭 변화/alias 품질): 규칙 강화 + 사용자 피드백 기반

---

## D3) “자동 추출” 팩트의 승인 정책(명시/암시 모두)

- 근거: `plan/user_request.md:61`, `plan/user_request.md:77`, `plan/architecture_2.md:211`, `plan/architecture_2.md:224`
- 1차(우선) 결정: **옵션 1**
  - `AUTO` 생성 팩트(명시/암시)는 전부 `PROPOSED`로 저장(사용자 승인 필요)
  - 사용자 태깅/입력에서 파생된 팩트는 `USER`로 기록(승인 정책은 UI 워크플로에서 명확화)
- 2차(차순위) 계획: **옵션 2(선택 구현)**
  - 특정 “명시 필드”에 한해 `AUTO+APPROVED`를 허용하는 정책 스위치 도입(기본 off)
  - 조건: 강한 규칙 기반 + 근거 필수 + 충돌 시 즉시 unknown/PROPOSED 강등

---

## D4) `SUGGEST`의 `LOCAL` 의미(로컬 LLM vs rule-base/템플릿)

- 근거: `plan/user_request.md:12`, `plan/architecture_2.md:370`, `plan/architecture_2.md:408`
- 1차(우선) 결정
  - `LOCAL`은 **rule-base/템플릿 기반 제안**을 우선 구현(근거 묶기/요약/체크 중심)
  - 동시에 “로컬 생성 모델” 분기를 포함하되, 1차에는 **분기/인터페이스/다운로드 플로우만** 구현
- 2차(차순위) 계획
  - 로컬 생성 모델(양자화 LLM) 실구현: 런타임/포맷(예: gguf/ONNX 등) 확정 + ModelStore 다운로드/업데이트 + 품질/안전 정책
  - `LOCAL_GEN` 모드의 결과도 근거 인용(evidence) 강제(가능하면)

---

## D5) Sync Retrieval(UX)에서 Vector 확장 허용 범위

- 근거: `plan/architecture_2.md:104`, `plan/architecture_2.md:425`, `plan/user_request.md:64`
- 1차(우선) 결정
  - Sync retrieval은 **FTS-only** 로 제한
  - Vector retrieval/expand는 **job으로 내려보내고**, UI는 **스트리밍(events)로 표시**
- 2차(차순위) 계획
  - 벡터 검색 결과 캐시/샤드 프리로드/최근 사용 기반 최적화(프리징 방지 범위 내)

---

## D6) 시점(time_key) / 세계관 타임라인(timeline_idx) 정책

- 근거: `plan/user_request.md:8-1`, `plan/user_request.md:8-2`
- 결정이 필요한 이유: “시점”은 절대시간/상대시간/에피소드(화수) 축이 혼재하며, 자동 매핑은 오염 위험이 큼.
- 1차(우선) 결정(권장)
  - 시점 chunk/time anchor는 **사용자 요청 시에만 생성**(리소스/오염 방지)
  - 1차 제안은 **상대 time_key + 화수/episode 기반 매핑**을 기본으로 하고, `AUTO → PROPOSED`로만 저장
  - 세계관 타임라인은 별도 문서(`timeline_doc_id`)로 유지하며, 타임라인 이벤트는 `timeline_idx`를 가진다
  - time anchor는 가능하면 `timeline_idx`를 참조하되, 불명확/충돌 시 미지정(null) 또는 UNKNOWN 처리
- 2차(차순위) 계획
  - 사용자 승인/조정 이후 2차 제안(재매핑/정교화) 및 chunk 역인덱스 생성(검색 최적화)
