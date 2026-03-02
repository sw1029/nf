현재 nf의 “정합성(Consistency)” 판정은 대략 (1) 문장 단위 세그멘테이션 → (2) 슬롯(나이/시간/장소/관계/소속/직업/재능/사망) 추출 → (3) 근거 검색(FTS 우선, 부족하면 vector 보강) → (4) 스키마 fact와 슬롯 비교로 OK/VIOLATE/UNKNOWN 산출 흐름입니다. 이 구조 자체는 “근거 없으면 확정하지 않는다(UNKNOWN 허용)” 쪽으로 설계되어 있어서, 정확도 관점에서는 “오탐(거짓 위배)”과 “미탐/UNKNOWN 남발”이 동시에 발생할 수 있는 지점이 꽤 명확합니다.

1. 엔티티(인물) 식별 실패 시 ‘전체 fact’와 비교하는 설계라 오탐 위험이 큽니다
   엔티티 후보 추출은 alias_text가 본문에 “부분 문자열로 포함되는지”만 보고 후보 집합을 만듭니다 . 문제는 (a) 인물명이 문장에 없는 경우(대명사/생략/서술체) 후보가 0이 되기 쉽고, (b) 그 경우 비교 대상이 특정 인물이 아니라 “해당 슬롯의 모든 fact”로 확장된다는 점입니다. fact 인덱스는 모든 fact를 (slot_key, **all**)에도 넣고 , 엔티티를 못 잡으면 그 **all** 버킷을 그대로 씁니다 .
   최악 시나리오: “그는 14세였다.” 같은 문장에서 엔티티 후보가 0이면, 프로젝트 내 다른 인물들의 ‘나이 fact’들과도 비교되고(14가 아닌 값이 많으면) VIOLATE가 나올 수 있습니다. 즉 “엔티티 미해결”을 UNKNOWN으로 처리하지 않고 “전체 엔티티 대비 위배”로 처리할 수 있어 정합성 오탐을 만들 수 있습니다.

2. 슬롯 비교 규칙이 ‘정확한 의미 비교’가 아니라 휴리스틱이라 경계 오류가 많습니다
   나이(age)는 int로 강제 변환 후 “정확히 같아야 OK”입니다 . 이야기 진행으로 나이가 증가하거나(시간 경과) “만 나이/서술적 표현”이 섞이면, 실제로는 자연스러운 변화인데 VIOLATE로 나올 수 있습니다(오탐).
   문자열 슬롯(time/place/relation/affiliation/job/talent)은 (1) 정규화 후 동일/부분문자열 포함이면 OK , (2) 토큰 겹침 비율이 0.85 이상이면 OK , (3) 숫자 불일치 + 낮은 유사도면 VIOLATE  입니다.
   이 방식은 “동의어/상하위어/수식어에 의해 의미가 달라지는 케이스”에서 취약합니다. 예: fact가 “마법사”인데 서술이 “흑마법사”면 부분문자열 포함 조건 때문에 OK가 되어(미탐) 실제 설정 위배를 놓칠 수 있습니다 .

3. 슬롯 추출(Claim extraction) 자체가 매우 제한적이라 미탐(=검사 자체가 안 됨)이 큽니다
   세그멘테이션은 문장부호 기반으로 자르는 단순 규칙입니다 . 이후 슬롯 추출은 규칙/모델 후보 중 슬롯별 최고 confidence만 선택하고, 각 슬롯을 “슬롯 1개짜리 claim”으로 쪼개서 저장합니다 .
   기본 rule은 정규식 몇 개에 크게 의존합니다. 예를 들어 나이는 “숫자 + 살/세”만 잡습니다 . 즉 “열네 살”(한글 수사), “중년”, “미성년” 같은 표현은 기본 규칙만으로는 빠질 가능성이 큽니다(미탐). 시간/장소/관계/소속/직업/재능/사망도 유사하게 제한된 패턴 위주입니다 .

4. 근거 검색 품질이 ‘FTS + 토큰 겹침’ 중심이라 한국어/변형/의미 검색에서 정확도가 낮습니다
   FTS 검색은 SQLite FTS5의 bm25 기반이며, query 텍스트를 build_query로 만든 뒤 MATCH로 검색하고, doc_id/doc_ids/tag_path 등은 “정확히 일치” 필터로 적용합니다 . 한국어에서 형태소/조사/띄어쓰기 변형이 많으면 “원하는 근거 chunk를 못 찾는” 일이 흔해지고, 그러면 NO_EVIDENCE로 UNKNOWN이 늘어납니다.
   FTS가 부족하면 vector_search로 보강하는데, 기본 백엔드는 token overlap 입니다(문서 토큰과 질의 토큰의 겹침 비율) , 토큰화도 정규식 \w+ 기반이라 한국어 의미 유사 검색과는 거리가 있습니다 . 즉 “vector 보강”이 실질적으로는 의미 검색이라기보다 “단어 겹침 확장”이라 근거 회수율/정확도가 기대보다 낮을 수 있습니다.

5. 기본 문서 스코프가 ‘현 에피소드 ±10 + SETTING/CHAR/PLOT’로 고정되어 장기 설정에서 미탐이 생깁니다
   요청에서 doc_ids를 명시하지 않으면, 입력 문서 + 세계관 문서(SETTING/CHAR/PLOT) + 에피소드 번호 기준 윈도우(기본 10)만 검색 스코프로 잡습니다 . 장편에서 “초반에 결정된 설정”이 현재 에피소드에서 멀리 떨어져 있으면, 해당 근거를 검색 범위에서 제외해버려 NO_EVIDENCE/UNKNOWN이 늘 수 있습니다(미탐). 반대로, 세계관 문서가 방대해지면 노이즈가 늘어 상위 근거가 왜곡될 여지도 있습니다.

6. 엔티티/시간 정보가 “정합성 판정”에 직접적으로 정렬되지 않아 ‘정당한 변화’와 ‘모순’을 구분하기 어렵습니다
   현 구조는 time_key/timeline_idx 같은 메타 필터를 지원하는 검색 계층은 존재하지만(FTS에서 span overlap로 후처리) , 기본 실행에서는 보통 그 필터가 비어 있고, 슬롯 비교도 “현재 시점/타임라인”을 반영해 fact를 선택하지 않습니다. 결과적으로 (a) 시간 경과로 바뀐 값(나이/소속/관계 변화)을 VIOLATE로 오탐하거나, (b) 서로 다른 시점의 fact가 함께 존재할 때 CONFLICTING_EVIDENCE로 UNKNOWN이 남발될 수 있습니다 .

7. Graph 확장은 ‘seed/ambiguous’ 휴리스틱 기반이라 노이즈를 늘릴 수 있습니다
   Graph 확장은 “필터(엔티티/시간/타임라인) 또는 특정 슬롯 신호”로 seed를 만들고, hop 1~2로 확장해 doc_id 후보를 모읍니다 . 이 방식은 “그래프가 잘 구축된 경우”엔 도움이 되지만, 엔티티/시간 앵커 자체가 부정확하면 오히려 관련 없는 문서들이 후보로 들어와 근거 상위 랭크를 오염시킬 수 있습니다(오탐/미탐 모두 유발 가능).

8. “정확도”를 수치로 사용자에게 전달하는 Reliability가 과신을 유발할 수 있습니다
   현재 ReliabilityBreakdown은 (fts_strength, evidence_count, confirmed_evidence, model_score) 정도로 구성되고 , UNKNOWN이어도 “근거가 조금이라도 있으면 reliability가 0이 아니게 유지”됩니다 . 즉 “근거는 있는데 결론은 유보(UNKNOWN)”인 상황에서 점수가 중간 이상으로 나올 가능성이 있고, 사용자가 이를 “정합하다고 판정한 것”처럼 오해할 위험이 있습니다(정확도 체감 저하).

정리하면, 현재 구현은 “근거 없는 확정 금지” 정책 때문에 안전하게 UNKNOWN으로 빠지는 경우가 많고(미탐/유보), 동시에 엔티티 미해결/휴리스틱 비교 때문에 특정 상황에서는 VIOLATE 오탐도 만들 수 있습니다. 정확도(특히 정밀도)를 가장 위협하는 단일 포인트는 “엔티티 후보가 0일 때 전체 fact(**all**)와 비교하는 동작” 이고, 재현율을 가장 떨어뜨리는 포인트는 “제한된 슬롯/제한된 규칙 기반 추출” 과 “의미 검색이 아닌 토큰 겹침 vector 보강” 입니다.

아래는 “현재 nf 정합성(Consistency) 엔진”의 구조적 미비점을 기준으로, 정확도(특히 오탐 억제) 우선으로 개선/확장안을 정리한 것입니다. 근거는 repo의 현재 로직(예: `modules/nf_consistency/engine.py`) 기준으로 인용합니다.

1. 엔티티(인물) 미해결 시 “전체 fact(**all**)” 비교를 금지/약화 (오탐 억제에 가장 큼)

현재 fact 인덱스는 모든 fact를 `(slot_key, __all__)`에도 넣습니다 . 그리고 판단 시 엔티티를 못 잡으면 해당 슬롯의 후보를 `__all__`에서 그대로 가져옵니다 . 이 구조는 “주어가 명시되지 않은 문장”에서 다른 인물의 사실과 충돌하는 오탐(VIOLATE)을 유발하기 쉽습니다.

개선안(권장, 단기/저위험)

* “엔티티가 없으면 비교하지 않는다”를 기본 정책으로 둡니다.

  * 구체적으로: `target_entity_id is None`인 경우, `candidates = __all__`로 비교하는 대신 “UNKNOWN + AMBIGUOUS_ENTITY(또는 ENTITY_MISSING)”로 반환.
  * 예외: “세계관 전역 fact(엔티티가 원래 없는 fact)”만 허용. 이를 위해 `TagDef.constraints`에 `entity_scope: "global"|"entity_required"` 같은 플래그를 추가하고, global만 `__all__` 비교 허용.
* 부작용/최악: UNKNOWN 비율이 증가합니다(= 재현율 저하). 하지만 오탐 감소 효과가 커서 UX 신뢰도는 보통 상승합니다.

2. 메타(엔티티/시간) 필터를 “요청 기반”이 아니라 “claim별 자동 적용”으로 전환

현 FTS 검색은 `filters.entity_id/time_key/timeline_idx`가 들어오면 `entity_mention_span`/`time_anchor` 오버랩으로 결과를 강하게 거릅니다  . 하지만 Consistency 엔진은 기본적으로 이 메타 필터를 자동 산출하지 않아서(엔티티 후보는 문장 내 alias 매칭 정도로만) “근거 노이즈”가 그대로 상위 K에 남기 쉽습니다.

개선안(정확도/성능 밸런스 좋음)

* claim span(문장 구간)이 주어져 있으므로(엔진은 span을 유지하며 claim을 생성함 ), DB에서 그 span과 겹치는 `entity_mention_span`을 조회해

  * 겹치는 entity_id가 1개면 `filters.entity_id`로 자동 세팅,
  * 2개 이상이면 “ambiguous” 처리(UNKNOWN 유도),
  * 0개면 “직전 N문장(또는 N chars) 내 마지막 명시 엔티티”를 백오프(간단한 코리퍼런스 대체).
* 시간도 동일하게 `time_anchor` 오버랩을 조회해 `time_key` 또는 `timeline_idx`를 자동 세팅(가능할 때만).
* 이렇게 얻은 `auto_filters`를 retrieval에 주입:

  * 1차: FTS/Vector 조회 시 `filters`에 넣어서 애초에 노이즈를 제거(가장 효과 큼).
  * 2차(보수적): 기존 캐시를 유지하고 싶다면, 1차 조회는 기존대로 하고 결과 리스트에만 메타 필터를 후처리로 적용(정확도는 다소 떨어지지만 캐시 효율은 유지).

부작용/최악

* `entity_mention_span`/`time_anchor` 품질이 낮으면(별칭이 흔한 단어, 시간표현 누락) “정답 근거가 걸러져” UNKNOWN이 증가할 수 있습니다. 따라서 “자동필터는 ‘hard filter’가 아니라 ‘rerank 가중치’로 시작→확인되면 hard filter” 같은 단계적 적용이 안전합니다.

3. Slot 비교기(Comparator)를 TagDef 중심 “타입/제약 기반”으로 재설계

현재 비교는 나이/사망은 동등비교, 나머지 문자열 슬롯은 정규화 + 부분문자열/토큰겹침 기반입니다 . 이 방식은

* “흑마법사 vs 마법사”(부분문자열 포함) 같은 의미 위배를 OK로 놓치거나,
* 반대로 조사/수식어 차이로 불필요한 VIOLATE/UNKNOWN이 나올 수 있습니다.

개선안(단기: 규칙 강화 / 중기: 타입화)

* 단기: slot별로 “부분문자열 포함을 OK로 처리하는 규칙”을 축소(특히 job/relation/affiliation). 지금은 `claimed in expected`면 OK로 처리합니다 .

  * job/affiliation/relation은 “부분문자열 포함=약한 증거”로만 두고, 기본은 토큰/동의어/enum 매칭으로 판단하도록 변경.
* 중기: `TagDef.schema_type`과 `TagDef.constraints`를 적극 사용.

  * ENUM인 경우: canonical set(또는 alias map)을 constraints에 넣고 “동등 비교”로 전환.
  * STR이더라도 constraints에 `synonyms`, `hypernyms`, `forbid_contains_ok` 같은 정책을 넣어 슬롯별로 다르게 비교.
* 최악: 제약이 잘못 설계되면 오탐/미탐 모두 악화됩니다. 특히 enum 사전(동의어) 관리가 부실하면 성능이 급락합니다.

4. Slot 추출(Extraction)에서 “슬롯 당 1개 후보만 채택”을 완화 (미탐 감소)

현재 ExtractionPipeline은 후보 리스트에서 slot_key별 “첫 후보”만 채택합니다 . 그리고 엔진은 슬롯을 “슬롯 1개짜리 claim”으로 쪼갭니다 . 이 조합은

* 한 문장에 숫자가 여러 개일 때(나이/날짜/회차 등) 잘못된 숫자를 잡아 비교하거나,
* “주어-서술어 결합”이 필요한 관계/소속류에서 핵심 단서를 잃기 쉽습니다.

개선안

* N-best 후보 유지:

  * pipeline 단계에서 slot별 top-N 후보(span 포함)를 유지하고, engine에서 “엔티티/시간 근처 span” 또는 “근거 상위 evidence에 더 잘 맞는 후보”를 선택.
* “엔티티 포함 claim 템플릿” 생성:

  * 엔티티가 해결된 경우, retrieval query를 `"{entity} {slot_keyword} {value}"` 형태로 확장(예: “아린 나이 14”)하여 근거 회수율을 올림.
* 최악: 후보 수를 늘리면 처리량이 증가하고, 잘못된 후보까지 비교해 “conflicting(OK+VIOLATE 동시 관측)”이 증가할 수 있습니다. 따라서 top-N은 아주 작게(2~3) 두는 편이 안전합니다.

5. Retrieval 개선: FTS 기본 토크나이저/Vector가 “의미 검색”이 아님

* FTS는 `fts5(content, …)`로 생성되며 별도 tokenizer 설정이 없습니다 . 한국어는 형태소/띄어쓰기 변형에 취약해 recall이 떨어질 가능성이 큽니다.
* Vector도 기본은 token overlap 또는 hashed embedding 정도입니다 , 토큰화도 `\w+` 기반입니다 . 즉 “의미 유사”가 아니라 “단어 겹침”에 가깝습니다.

개선안(정확도 우선 순)

* 단기(설정만으로 가능한 것부터):

  * Vector backend를 `hashed_embedding`으로 기본 전환(이미 구현돼 있음) . 토큰 겹침보다 그나마 완화된 유사도를 제공합니다(여전히 의미 임베딩은 아님).
  * `tag_path`가 존재할 때(FTS index는 tag_assignment overlap으로 tag_path를 넣음 ), slot에 대응하는 tag_path를 soft-boost(점수 가산)하여 상위 K의 노이즈를 줄임.
* 중기(정확도 상승 폭 큼):

  * 진짜 임베딩 기반 retriever 도입(E5류 dual-encoder, bge/e5 계열; Sentence-BERT 계열 등).
  * 저장은 지금 shard(json) 구조를 유지하되 `embedding: list[float]`를 추가하고, FAISS/HNSW 같은 ANN 인덱스로 교체(또는 sqlite-vec).
* 최악:

  * 임베딩 모델 도입은 “학습 도메인 불일치(소설체/고유명사)”에서 성능이 기대만큼 안 나올 수 있고, 인덱스/메모리 비용이 급증합니다. 특히 온디바이스 목표면 양자화/캐시/샤딩 전략이 필수입니다.

6. “local reranker / local NLI”가 실제 모델이 아니라 휴리스틱 (layer3 판정 신뢰도 문제)

현재 local NLI는 토큰 겹침 + 일부 반의어/부정어 시그널로 점수를 만드는 휴리스틱입니다  . local reranker도 유사하게 토큰 겹침 기반입니다 . 그런데 Consistency 엔진은 이 점수를 이용해 rerank 및 (옵션) UNKNOWN→OK 승격까지 수행합니다(엔진 내부 로직 참조).

개선안(정확도 최우선이면 사실상 필수)

* 진짜 cross-encoder reranker(문장쌍 분류/랭킹) + NLI(or contradiction) 모델로 교체.

  * reranker: Cross-Encoder 기반(예: MS MARCO 계열) 또는 소형 다국어/한국어 cross-encoder.
  * contradiction: MNLI/ANLI 계열 NLI 모델 또는 “contradiction 전용”으로 미세조정된 모델.
* 계산비용을 줄이기 위한 게이팅:

  * (1) fact 비교로 VIOLATE가 강하게 나오면 모델 호출 생략,
  * (2) UNKNOWN이고 evidence가 충분하며(confidence/confirmed 포함) 승격 가능성이 있을 때만 호출.
* 최악:

  * 모델이 강해질수록 “근거가 잘못 뽑혔을 때” 오히려 그럴듯한 오판을 강화할 수 있습니다(garbage-in-garbage-out). 그래서 2)에서 말한 “근거 노이즈 제거”가 선행돼야 합니다.

7. self-evidence 필터 정책을 “검사 목적”에 맞게 분리

현재 self-evidence 제거는 기본 활성이고, scope가 `range`면 선택 범위 전체와 겹치는 근거를 제거합니다(범위 검사 시 내부 근거를 크게 날릴 수 있음). 이 정책은 “자기 텍스트로 자기 텍스트를 정당화”하는 승격(promotion) 방지에는 유리하지만, “같은 범위 내부의 모순 탐지”에는 불리합니다.

개선안

* 목적을 분리:

  * (A) “승격(promotion) 금지용” self-evidence 제거
  * (B) “모순 탐지용”은 같은 문서 내 다른 구간 근거는 허용(현재도 일부는 허용하지만 range 선택 시 과도해질 수 있음)
* 기본 scope를 `claim_span`(해당 claim span만 제외)로 낮추고, range 전체 제외는 옵션으로 두는 편이 정확도/사용성 양쪽에 안전합니다.

8. 평가/계측: “정확도 개선”이 진짜인지 확인할 테스트 하네스 필요

엔진은 이미 stats/unknown_reason_counts 등을 누적합니다. 하지만 “정확도(precision/recall) 지표”는 별도로 계산하지 않습니다.

개선안

* 자동 생성 테스트셋:

  * 승인된 schema_facts(ground truth)에서 템플릿 기반으로 문장 생성 → OK 케이스.
  * 값만 바꾼 반례 생성 → VIOLATE 케이스.
  * 엔티티/시간을 일부러 제거 → UNKNOWN 기대 케이스.
* 슬롯별 confusion matrix(OK/VIOLATE/UNKNOWN) 및 “오탐 우선 지표(precision@VIOLATE)”를 주 지표로 두고, 1)~7) 변경의 효과를 수치로 확인.

참고(논문 위주, 관련 축)

* Reimers & Gurevych, “Sentence-BERT” (2019): 문장 임베딩 기반 retrieval/유사도
* Karpukhin et al., “DPR” (2020): dual-encoder dense retrieval 기본 형태
* Nogueira & Cho, “Passage Re-ranking with BERT” (2019): cross-encoder reranker 계열의 고전
* Thorne et al., FEVER (2018): “claim-evidence-verdict” 구조의 사실검증 태스크(정합성 판정 설계 참고)
* Liu et al., DeBERTa (2021): NLI/분류 backbone로 자주 쓰이는 계열
