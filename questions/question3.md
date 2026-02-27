요구 정의(user_request.md)의 핵심은 “(1) 설정/플롯/등장인물 등 별도 문서 작성 → (2) 인덱싱/임베딩 → (3) 집필 중 텍스트에서 정합성 위배 구간을 문장 단위로 segmentation하고 신뢰성 점수·근거·예외처리(화이트리스트)까지 제공”입니다. 특히 정합성은 “명시 필드(나이/시간/장소/관계/사망 등) 기반 High-precision 체크”와 “암시/추정/서술 트릭은 Unknown 허용 + 필요 시 소형 모델(NLI/분류기) 위임”의 2단 구조를 요구합니다 . 또한 time_key/entity_id/timeline_idx 기반 필터·chunk 그룹화, 타임라인 문서, 그리고 대규모 원고에서의 성능/오염 방지(근거 강제, 충돌 시 unknown 강등, 작업 큐/메모리 상한)도 명시돼 있습니다  .

1. UI/UX 관점: 반영된 부분(구현 근거 포함)

(1) “설정/본문/구상/타임라인” 작업 흐름

* 좌측 탭(본문/설정/구상/타임라인)과 “새 문서/새 챕터”가 있어 문서 타입을 분리하는 기본 UX는 구현되어 있습니다 .
* EPISODE는 챕터(그룹) 기준 트리 + 드래그&드롭 재정렬(메타데이터 order)까지 지원합니다 .
* 타임라인 뷰는 doc.metadata.time_key / timeline_idx를 기반으로 정렬·표시됩니다 .

(2) 에디터 UX(자간/줄간격/폰트 등)

* user_request의 “자간/줄 간격 설정” 요구  는 설정 패널과 CSS 변수 기반으로 제공됩니다  .
* 페이지( A4 유사 ) 기반 편집(페이지 나눔/가이드/페이지 수 표시 등)과 문자 수/쪽수 상태바가 구현돼 있습니다  .

(3) “작가 도우미” 사이드바 + 정합성 UI 노출

* 우측 “작가 도우미” 사이드바(CHECK/SEARCH/PROPOSE)와 “오류 점검하기” 버튼이 구현돼 있습니다 .
* CHECK에는 “OK 단락도 보기” 토글과 (quick/deep/strict) 프리셋이 있고, entity/time/timeline 입력으로 집중 점검 필터를 받을 수 있습니다 .
* 정합성 결과는 본문 하이라이트로 표시됩니다(CSS Highlights 지원 시 native highlight, 아니면 span fallback) .
* 정합성 위배/보류 구간에서 “의도됨(승인)/무시” 액션 팝오버가 있습니다 .

(4) 백그라운드 작업/상태 위젯(성능 UX)

* 툴바에 jobs/consistency 배지와, 백그라운드 작업 패널 및 “배경 점검 상태” 패널이 있습니다  .
* 워커는 메모리 압박 시 heavy job lease를 멈추고 경고 이벤트(reason_code=PAUSED_DUE_TO_MEMORY_PRESSURE)를 남깁니다 . UI는 이 이유코드를 “시스템 대기 중”으로 표시하도록 매핑되어 있습니다 . (대규모 원고에서의 “프리징 방지” 요구에 부합 )

2. UI/UX 관점: user_request 대비 미비점/개선 필요(핵심 리스크 위주)

(1) “설정 문서 태깅/계층 분류”는 UI는 보이지만 ‘스키마/DB’로 이어지는지 불명확

* UI에는 “빠른 태그/메모(인물/사건/복선)” 위젯이 존재합니다 .
* 하지만 현재 에디터의 텍스트 추출은 DOM을 text로만 읽어오는 방식(range.toString)이라 , 인라인 태그가 “문서 content”로 저장되는 구조는 아닙니다(별도의 tag_assignment API로 저장하지 않으면 태그가 휘발될 가능성이 큼).
* 반면 백엔드 ingest는 “tag_assignment를 읽어 evidence/fact를 생성”하는 구조입니다  . 즉, user_request의 “설정 문서에 별도 태깅, 계층적 분류 제공”  을 실제 정합성 엔진에 연결하려면, UI 태그가 tag_assignment로 확정 저장되는 UX가 핵심인데 그 연결이 현재 코드만으로는 확정되지 않습니다(설계 상 ‘가장 큰 미비점’).

(2) 타임라인(time_key/timeline_idx) 편집 UX가 실질적으로 부족

* 타임라인 뷰는 메타(time_key/timeline_idx)를 기준으로 보여주지만 , 문서 컨텍스트 메뉴에는 회차 번호(episode_no)만 있고 time_key/timeline_idx를 설정하는 항목이 없습니다 .
* user_request는 time_key, entity_id, timeline_idx를 “정합성/검색/제안에서 필터링”하도록 확장하라고 명시합니다 . 현재는 입력 필드(필터)는 있지만 , 이를 생성/검증/수정하는 UI 플로우가 약합니다.

(3) “n~m화 에피소드 chunk”/범위 분석 UX 미노출

* user_request는 n~m화 구간을 묶어 chunk를 구성(그리고 사건 밀도 등 계량도 optional)  을 요구하지만, 기본 UI에서 범위 선택/분석 실행 UX는 보이지 않습니다.
* 백엔드에는 episode_id를 resolve하는 로직이 존재합니다 . 즉 “구현 기반은 있는데, 사용자 조작 UI/UX가 없다” 쪽에 가깝습니다.

(4) “검토 레벨(deep/strict)” UI 카피가 실제 로직 대비 과장될 위험

* UI는 deep를 “심리/간접 떡밥 모순 추론”, strict를 “심층 검증”으로 설명합니다 .
* 그런데 실제로 현재 CHECK job payload는 schema_scope를 항상 explicit_only로 고정합니다 . 즉, “암시/추정/서술 트릭” 레이어를 별도 파이프라인으로 돌리는 user_request의 의도  를 UI 레벨 변화만으로 충족한다고 보기 어렵습니다(현재 프리셋은 graph/triage/NLI 같은 파라미터만 바꾸는 형태 ).

(5) Export: UI 표기(.docx)와 구현 충돌 가능성(네이밍 충돌)

* export 모달은 docx 선택지를 노출합니다 .
* 그런데 editor.js에도 handleExport가 존재(클라이언트에서 .doc 다운로드)하고 , docs_tree.js에도 handleExport가 존재(서버 EXPORT job 실행)합니다 .
* 현재 스크립트 로딩 순서상 docs_tree.js가 editor.js 뒤에 로드되므로 , “마지막 정의가 덮어써져서 우연히 동작”하는 형태입니다. 유지보수/리팩터링 시 순서가 바뀌면 export가 깨질 수 있는 구조적 취약점입니다.

3. 정합성 로직: 타당성/성능/완성도(현재 구현 기반 평가)

(1) 설계 타당성(요구 의도와의 정합성)

* “명시 슬롯(age/time/place/relation/affiliation/job/talent/death)” 기반의 고정 슬롯 체계는 user_request의 High-precision 목표와 방향성이 맞습니다 . 실제로 슬롯 키가 제한되어 있고 , 비교도 간단한 규칙(나이=정수 동일, 사망=bool 동일, 문자열=정규화+토큰 유사도)로 구현돼 있습니다 .
* “근거 표준화(문서/섹션/태그 경로 + 스니펫)” 요구  는 evidence bundle에 section_path/tag_path/snippet_text 등이 포함되도록 구현돼 있습니다 .
* “충돌 시 UNKNOWN”도 구현돼 있습니다(OK와 VIOLATE 근거가 동시에 감지되면 UNKNOWN 처리) . 이는 user_request의 “근거 충돌 시 보류/unknown” 방향과 일치합니다 .

(2) 완성도/정확도 관점의 핵심 약점(최악 시나리오 포함)
A. ‘클레임 추출’이 기본 설정에서 거의 작동하지 않을 위험

* 추출 파이프라인의 기본 모드는 rule_only 입니다 . UI/자동 ingest에서 extraction profile을 넘기는 흐름이 기본 UX로는 보이지 않습니다(INGEST job params에 extraction을 넣지 않으면 rule_only로 떨어짐 ).
* rule_only의 builtin 규칙은 “장소/관계/소속/직업/재능”을 ‘장소: …’, ‘관계: …’처럼 명시 키워드 기반 패턴으로만 뽑습니다 . 일반적인 소설 서술(“서울에 도착했다”, “둘은 친구였다”)에서는 슬롯이 거의 추출되지 않아, 정합성 체크가 “아무 것도 못 찾는 것처럼 보이는” 최악의 사용자 경험이 발생할 수 있습니다.
* 모델 기반 보강(hybrid_local/remote/dual)은 설계상 존재하지만 , UI/기본 파이프라인이 이를 실제로 켜 주지 않으면 정확도는 요구 수준과 괴리됩니다.

B. “explicit_only” 사용 방식이 오염/노이즈를 만들 수 있음

* explicit_only scope는 “EXPLICIT layer의 facts 중 REJECTED가 아닌 것(=PROPOSED 포함)”을 사용합니다 .
* 한편 AUTO fact는 정책상 PROPOSED로 강제 유지됩니다 (user_request의 ‘승인 전 자동확정 지양’ 취지와 일치). 하지만 체크에서 PROPOSED를 그대로 쓰면, “미승인/불확실 fact가 근거로 작동해 위배 경고를 양산”하는 최악의 상황이 가능합니다. 신뢰성 점수로 완화하더라도, 사용자 신뢰 저하 위험이 큽니다.

C. time_key/timeline/엔티티 기반 기능은 “백엔드 구현 대비 UI 노출 부족”으로 성능이 봉인될 가능성

* 그래프 기반 RAG는 entity_id/time_key/timeline_idx를 seed로 삼아 후보 문서를 확장하고  , 결과를 boost하는 rerank도 있습니다 .
* 워커도 entity_mention_span / time_anchor를 이용해 결과를 meta-filter할 수 있습니다 .
* 그런데 UI에서 이 anchor/span을 생성·검증·수정하는 플로우가 약하면(또는 없으면), graphRAG/필터링은 실질적으로 비활성에 가깝게 남습니다. 결국 “설계는 있는데 체감 성능이 안 나오는” 상태가 지속됩니다.

D. “암시/추정/서술 트릭” 레이어는 아직 ‘요구 수준의 기능’으로 보긴 어려움

* user_request는 이 레이어는 unknown을 기본으로 하고, 작은 모델(NLI/분류기) 또는 API에 위임하되 근거 충돌 시 보류를 요구합니다 .
* 현재 UI 프리셋은 verifier_mode(=NLI) 등을 켤 수는 있으나 , schema_scope가 고정 explicit_only이고, 핵심은 “클레임 추출/제약 모델링/근거 결합”인데 이 부분이 기본 설정에서 충분히 작동한다는 보장이 약합니다(특히 rule_only 문제).

(3) 성능/운영 안정성 관점

* 장점(구현 근거 명확): 워커는 heavy job 동시 실행 제한과 메모리 압박 시 lease pause를 구현했고 , UI에도 그 상태를 노출합니다 . 대규모 원고에서 “전체 프리징”을 피하기 위한 방향성은 요구와 정합적입니다 .
* 잠재 병목(최악 포함):

  * 엔티티/시간 앵커 자동 추출은 문자열 포함 검사·문장 단위 이벤트 생성 등 단순 휴리스틱이 섞여 있습니다  . 데이터가 커질수록 “잘못된 앵커가 그래프/RAG를 오염”시키거나 “불필요한 이벤트 폭증”으로 비용이 커질 수 있습니다.
  * vector index(INDEX_VEC)는 존재하지만 , 기본 post-save 파이프라인에 항상 포함되지는 않는 것으로 보입니다(FTS 중심) . 이 경우 벡터 기반 recall 개선이 체감되지 않거나, 사용자가 “검색/정합성은 왜 계속 BM25 수준인가”를 느끼게 됩니다.

정리(현 상태의 결론)

* UI/UX는 “작문 에디터 + 도우미 + 백그라운드 작업 가시화”까지는 상당히 완성도가 높고, user_request의 큰 골격(문서 분리, 에디터 레이아웃 옵션, 정합성 결과 하이라이트/예외처리 UI, 작업 큐/메모리 압박 UX)은 다수 반영돼 있습니다   .
* 반면 “정합성 성능(정확도)과 요구의 핵심 가치”는 (a) 기본 rule_only 추출로 인한 극저 recall 위험  , (b) UI 태깅→tag_assignment→schema/graph로 이어지는 연결 UX의 불명확성 , (c) time_key/entity_id/timeline_idx 기반 기능의 “UI 노출 부족”  때문에 user_request 대비 미비점이 큽니다.
* 즉, 현재 구현은 “틀(UX/인프라)은 갖췄지만, 정합성의 핵심인 ‘근거화(태깅/스키마)와 클레임 추출’이 사용자가 체감할 수준으로 기본 활성화돼 있지 않으면 성능·완성도 평가가 낮아질” 구조입니다.
