결론부터 말하면, “현재 nf 정합성 로직”은 기본 설정 기준으로 **보수적(정밀도↑ / 재현율↓)** 으로 설계되어 있지만, 정확도 관점에서 **구조적으로 취약한 구간이 몇 군데** 있습니다. 특히 “엔티티(누구에 대한 서술인가) 결정을 못 했을 때의 처리”와 “문자열 슬롯 비교(숫자 포함) 규칙”이 가장 큰 리스크입니다. 아래는 구현(커밋 `64b8693...`) 기준으로의 구체 검토입니다.

---

1. Claim/Slot 추출 단계의 재현율 한계 (정합성 검사가 ‘걸리는’ 문장 자체가 적어질 수 있음)

* 정합성 엔진은 `modules/nf_consistency/engine.py`에서 `_extract_claims()` 결과(슬롯이 잡힌 문장)만 검사합니다. 슬롯이 안 잡히면 그 문장은 애초에 정합성 판정 대상이 아닙니다.
* 기본 추출기는 `modules/nf_consistency/extractors/rule_extractor.py`의 `builtin_rules()`인데, “나이(11살/12세)”, “장소/위치: …”, “관계/소속/직업/재능: …” 같이 **형식이 드러나는 문장**에 매우 편중되어 있습니다. 서술형 문장(예: “그는 왕궁으로 갔다”, “그는 귀족 가문 출신이다”)은 규칙 기반만으로는 거의 놓칩니다.
* 모델 기반 보강은 `ExtractionPipeline`에 존재하지만(`modules/nf_consistency/extractors/pipeline.py`), 기본 프로필이 `rule_only`라면 작동하지 않습니다. 즉 “설정-작문”에서 자연 서술을 광범위하게 검사하려면 기본 설정 그대로는 재현율이 낮게 고정됩니다.

정확도 리스크(최악의 경우):

* 사용자는 “정합성 검사가 돌아가고 있다”고 느끼지만, 실제로는 **대부분 문장이 슬롯 미검출로 스킵**되어 “위배를 놓치는” 방향으로 수렴할 수 있습니다(재현율 저하).

---

2. 엔티티(누구의 속성인가) 그라운딩이 약하고, ‘엔티티 미결정’ 시 판정이 위험해질 수 있음

핵심 문제는 두 부분이 결합될 때 생깁니다.

(1) 엔티티 후보 탐지는 단순 부분문자열 매칭
`modules/nf_schema/identity.py`:

```python
def find_entity_candidates(text: str, alias_index: dict[str, set[str]]) -> set[str]:
    matched: set[str] = set()
    for alias_text, entity_ids in alias_index.items():
        if alias_text and alias_text in text:
            matched.update(entity_ids)
    return matched
```

* 토큰 경계/형태소/정규화가 없어서, 짧은 별칭(1~2글자)이 있으면 **오탐/과다 매칭**으로 “ambiguous(복수 후보)”가 자주 발생할 수 있습니다.
* 반대로 대명사/생략(“그”, “그녀”, “주인공”)에는 거의 무력이라 **엔티티 미검출(0개 후보)** 도 흔합니다.

(2) 엔티티를 못 정하면 “전체 엔티티의 모든 팩트”와 비교해 버림
`modules/nf_consistency/engine.py`의 `_judge_with_fact_index()`:

```python
if target_entity_id is None:
    candidates = fact_index.get((slot_key, _FACT_ALL_KEY), [])
else:
    candidates = [*fact_index.get((slot_key, target_entity_id), []),
                  *fact_index.get((slot_key, None), [])]
```

* `target_entity_id is None`이면 해당 슬롯(예: age)의 **모든 팩트(모든 인물/모든 엔티티)** 와 비교합니다.
* 이때 특정 문장이 실제로는 “A”에 대한 서술인데 엔티티가 미검출되면, “B의 나이/직업/소속”과도 비교되어 **거짓 VIOLATE(오탐)** 가 나올 수 있습니다.
* 계획 문서(“엔티티 불명확 시 unknown 우선”)의 의도와도 어긋나는 동작입니다(현재 구현은 unknown 우선이 아니라 “전체 팩트와 비교”를 우선).

정확도 리스크(최악의 경우):

* 대명사/생략이 많은 문체에서, 특정 슬롯(특히 age처럼 강하게 비교되는 슬롯)은 **전혀 관계없는 다른 인물 팩트와의 불일치로 VIOLATE가 발생**할 수 있습니다(정밀도 붕괴).
* 또는 반대로 여러 인물의 값이 섞여 있어 OK와 VIOLATE가 동시에 관측되면 UNKNOWN으로 내려가는데, 이때도 “실제 위배”를 잡아내지 못하고 UNKNOWN으로 도망갈 수 있습니다(재현율 저하).

---

3. 슬롯-팩트 매핑(어떤 tag_path가 어떤 슬롯인지)이 휴리스틱에 크게 의존

* `_fact_slot_key()`는 tag_def가 있으면 constraints/schema_type로 매핑을 시도하지만, 없으면 `_legacy_fact_slot_key()`로 tag_path 문자열에 키워드가 포함되는지로 판단합니다.
* tag_path 네이밍이 조금만 흔들리거나(예: “출신”, “거처”, “직위” 같은 표현) 키워드가 우연히 포함되면, **잘못된 슬롯으로 들어가거나** 아예 슬롯 키를 못 얻어서 **비교 대상에서 탈락**할 수 있습니다.

정확도 리스크:

* 스키마(태그 정의) 설계가 완벽히 정규화되어 있지 않으면, 정합성 엔진 정확도는 “모델 성능”이 아니라 **태그 네이밍 품질**에 의해 급격히 요동합니다.

---

4. 문자열 슬롯 비교 로직의 취약점 (특히 “숫자 포함 문자열”에서 위배를 놓치기 쉬움)

`modules/nf_consistency/engine.py`의 `_compare_slot()`에서 문자열 슬롯(time/place/relation/affiliation/job/talent)은 대략 다음 흐름입니다.

* (a) 정규화 후 완전일치/부분문자열 포함이면 OK
* (b) 토큰 오버랩 similarity ≥ 0.85면 OK
* (c) “숫자 불일치 + similarity가 매우 낮음(≤0.25)”일 때만 VIOLATE
* (d) 그 외는 None(판정 불가 → UNKNOWN 쪽으로 흘러감)

이 구조의 문제:

* “3서클 마법사” vs “4서클 마법사”처럼 **숫자만 다른 경우**는 토큰 오버랩이 높게 나와서 (c)로 못 들어가고 **UNKNOWN으로 빠질 가능성이 큽니다**.
* “부분문자열 포함이면 OK” 규칙은 “마법사” vs “서클 마법사” 같은 케이스에서 **너무 쉽게 OK**가 됩니다(정밀도 리스크).

정확도 리스크(최악의 경우):

* 숫자가 핵심 의미를 가지는 속성(job rank, 날짜, 시간, 회차 등)에서 **위배를 놓치고 UNKNOWN/OK로 흐르는** 패턴이 반복될 수 있습니다.

---

5. Retrieval/증거(evidence) 파트가 “정확도”를 직접 보장하지는 못함 (오히려 옵션 기능에서 오판 위험)

* 기본 판정(L1/L2)은 결국 “슬롯 vs 스키마 fact” 비교가 중심이고, retrieval은 근거 스니펫을 모으는 성격이 강합니다.
* `filters`에 `entity_id/time_key/timeline_idx` 같은 메타 필터가 들어오면(의도적으로) **vector_search를 호출하지 않도록 막아둔 테스트**가 존재합니다(`tests/test_nf_consistency_filters.py`). 즉 메타필터 모드에서는 FTS만으로 증거를 못 찾으면 “증거 부족”으로 더 쉽게 UNKNOWN이 됩니다(재현율 저하).
* Layer3 “UNKNOWN → OK 승격”은 opt-in이며(`layer3_verdict_promotion`), NLI 점수/confirmed evidence 수/FTS strength로 게이트를 걸었지만, 최악의 경우:

  * chunk span이 큰데 “approved/user tag span과 조금이라도 겹치면 confirmed” 처리(`_promote_confirmed_evidence`)가 과대승인처럼 작동하면,
  * 엉뚱한 스니펫이 confirmed로 집계되어 승격 조건을 만족,
  * NLI가 우연히 높은 entail을 내면 **잘못된 OK 승격**이 가능합니다(정밀도 리스크).

---

6. 테스트 커버리지 관점에서 “정확도 취약 구간”이 아직 방치된 신호

* 엔진 기본 동작(OK/VIOLATE/UNKNOWN), ignore/whitelist, 일부 게이트는 테스트가 있지만,
* “동명이인/별칭 충돌”, “엔티티 미검출(대명사/생략)에서의 오탐 방지”, “숫자 포함 문자열 슬롯의 위배 판정” 같은 정확도 핵심 케이스는 테스트로 강하게 못 박혀 있지 않습니다(계획 문서에서도 차순위로 남아있음).

---

정리 (정확도 기준의 미비점)

가장 큰 정확도 리스크 2가지:

1. 엔티티를 못 박지 못한 문장에 대해 `target_entity_id=None`인 채로 **전체 엔티티 fact와 비교**하는 현재 전략은, 문체에 따라 **거짓 VIOLATE를 만들 수 있는 구조적 결함**입니다. (정밀도 최악 케이스)
2. 문자열 슬롯 비교에서 “숫자만 다른 케이스”를 강하게 VIOLATE로 만들지 못하고 UNKNOWN으로 빠질 수 있는 로직은, **중요한 위배를 놓치는 방향**으로 작동할 수 있습니다. (재현율 최악 케이스)

참고로, 관련 방법론/배경 논문(개선 방향을 정당화할 때 흔히 인용되는 축):

* RAG 기본: Patrick Lewis et al., “Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks”, NeurIPS 2020.
* 사실검증/근거 기반 판정 데이터셋 축: James Thorne et al., “FEVER: a Large-scale Dataset for Fact Extraction and VERification”, NAACL 2018.
* 엔티티 링킹(별칭/표기 변형을 더 견고하게 처리): Ledell Wu et al., “BLINK: Better Entity Linking via Neural Retrieval”, EMNLP 2020.
* 문서/문장 재랭킹(근거 선택 품질 향상): Omar Khattab, Matei Zaharia, “ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT”, SIGIR 2020.


현재 nf 정합성 엔진은 “(1) 문장 세그먼트 → (2) 슬롯(나이/시간/장소/…) 추출 → (3) 증거(FTS/Vector/Graph) 수집 → (4) 스키마 fact 비교로 OK/VIOLATE/UNKNOWN → (5) 옵션: rerank/NLI 기반 보강” 흐름입니다(`modules/nf_consistency/engine.py`, `modules/nf_consistency/extractors/*`). 이 구조를 유지하면서 정확도(오탐/미탐) 관점의 미비점을 보완·확장하는 방안을, “단기 보완(로직 변경 최소)” → “중기 확장(인덱스/메타 활용)” → “장기 고도화(모델 기반 구조화)”로 나눠 제시합니다.

---

1. 단기 보완: “엔티티 미결정 시 전 엔티티 fact와 비교”로 인한 거짓 VIOLATE 방지

문제(정확도 리스크가 가장 큼)

* 현재 `_judge_with_fact_index()`는 `target_entity_id is None`이면 `(slot_key, __all__)`로 “모든 엔티티 fact”를 후보로 가져옵니다. 이 상태에서 슬롯 비교가 강하게 일치/불일치를 내면, 실제 대상 인물이 아닌 fact와의 불일치로 VIOLATE가 발생할 수 있습니다(거짓 양성). 해당 분기 자체가 위험합니다(엔티티를 못 박지 못한 문장은 원칙적으로 비교 불가에 가까움).

개선안 A(가장 안전, 구현 난이도 낮음)

* “엔티티 속성형 슬롯”에 대해서는 `target_entity_id=None`일 때 비교 자체를 중단하고 UNKNOWN 처리로 보내는 게 정밀도 최우선 전략입니다.
* 엔티티 속성형 슬롯 예: `age, death, job, talent, affiliation`(relation은 설계에 따라 다르지만 기본은 엔티티 속성 취급이 안전).
* 구현 포인트

  * `modules/nf_consistency/engine.py`:

    * `_judge_with_fact_index()`에서 `target_entity_id is None`일 때:

      * `slot_key`가 엔티티 속성형이면 `return None, [], meta`(판정 불가로 올려보냄)
      * 또는 후보를 `(slot_key, None)` 즉 “entity_id가 없는 global fact”로만 제한.
    * UNKNOWN 사유에 `ENTITY_UNRESOLVED` 같은 새 코드를 추가해 디버깅 가능하게.

개선안 B(정밀도 유지 + 재현율 보완)

* 엔티티 미검출이면 “문장 내 alias 매칭”만 쓰지 말고, 후술(2)의 “엔티티 mention span” 기반으로 보정해서 `target_entity_id`를 얻도록 합니다. 이걸 하면 A처럼 무조건 UNKNOWN으로 빠지는 비율을 줄이면서도 거짓 VIOLATE를 크게 감소시킬 수 있습니다.

부작용(최악 시나리오)

* 개선안 A는 재현율이 떨어져 UNKNOWN이 늘어날 수 있습니다. 다만 현재 구조는 거짓 VIOLATE가 더 치명적(사용자 신뢰 붕괴)이므로, 기본값을 A로 두고 B를 옵션/메타 인덱스 활성화로 확장하는 편이 안전합니다.

---

2. 중기 확장: 엔티티/시간 “메타 인덱스”를 정합성 엔진이 직접 활용 (대명사/생략 문체 대응)

현재 상태

* worker의 FTS 인덱싱 과정에 `entity_mention_span`, `time_anchor`를 생성하는 로직이 이미 존재합니다(`modules/nf_workers/runner.py`의 `_handle_index_fts()`에서 grouping 옵션이 켜지면 생성).
* 그런데 consistency 엔진(`modules/nf_consistency/engine.py`)은 엔티티 결정을 `find_entity_candidates()`(단순 substring 매칭)만 사용합니다(`modules/nf_schema/identity.py`). 이 때문에 “그/그녀/주인공” 같은 대명사/생략이 많으면 엔티티를 못 박고, (1)의 문제가 터집니다.

개선안

* consistency 실행 시, 각 claim span(절대좌표 `claim_abs_start/end`)에 대해 DB의 `entity_mention_span`을 조회해 “그 span에 겹치거나 가장 가까운 엔티티”를 추정합니다.
* 동시에 time도 `time_anchor`를 이용해 time_key/timeline_idx를 추정해 retrieval filter로 넣으면 증거 검색의 정확도도 올라갑니다(특히 동일 인물/동일 장소가 여러 회차에 반복되는 경우).

구체 구현 포인트

* `modules/nf_consistency/engine.py`에 helper 추가(개념):

  * `_resolve_entity_from_spans(conn, project_id, doc_id, snapshot_id, span_start, span_end) -> entity_id|None`
  * `_resolve_time_from_anchors(conn, project_id, doc_id, snapshot_id, span_start, span_end) -> {time_key,timeline_idx}|None`
* 그리고 claim 처리 루프에서:

  * `target_entity_id`를 `find_entity_candidates()` 결과가 0/다수일 때 span 기반 결과로 보정
  * retrieval_filters에 `entity_id/time_key/timeline_idx`를 claim별로 임시 주입(캐시 키가 달라지는 비용은 있지만, 정확도 향상이 더 큼)

인덱스 생성 조건 보완(중요)

* 현재는 graph_mode가 manual/auto일 때 preflight에서 grouping을 강제로 켜는 경향이 있습니다(인덱스 비용 때문에). 정합성 정확도를 올리려면 “graph_mode와 무관하게” 최소한 `entity_mentions/time_anchors`는 consistency preflight에서 항상 활성화하는 옵션이 필요합니다.
* 구현 포인트: `modules/nf_workers/runner.py`의 `_run_consistency_preflight()`에서 `ensure_index_fts`를 수행할 때 grouping을 graph_mode에만 묶지 말고, 예를 들어 `consistency_params.grouping_for_consistency=true` 같은 플래그로 분리.

부작용

* 인덱싱 비용 증가(특히 문서가 많을 때). 다만 entity/time span은 “문장 단위 스캔 + 문자열 매칭” 수준이어서, 벡터 인덱스에 비하면 비교적 저렴합니다. 최악의 경우를 대비해 “doc scope 제한(현재 문서 + 주변 episode + 설정/캐릭터/플롯)”은 이미 엔진에 존재하므로(`_build_default_doc_scope()`), 여기에 맞춰 grouping scope도 제한하는 게 안전합니다.

---

3. 단기 보완: alias 매칭(엔티티 후보 탐지) 품질 개선으로 ambiguous 과다 발생/오탐 감소

문제

* `find_entity_candidates()`는 “alias_text가 text에 포함되면 매칭”이라, 짧은 별칭/부분문자열 문제로 ambiguous가 쉽게 발생합니다. ambiguous이면 엔진은 UNKNOWN으로 강등합니다(미탐 증가).

개선안

* alias 전처리/매칭 규칙 강화:

  1. 너무 짧은 alias(예: 1~2자)는 기본적으로 제외하거나, “토큰 경계”가 성립할 때만 매칭
  2. NFKC 정규화 + 공백 정규화 후 비교(현재는 그대로 비교)
  3. 한글/영문/숫자 경계를 고려한 “단어 경계 매칭” 도입(정규식/커스텀 boundary)
* 구현 포인트: `modules/nf_schema/identity.py`의 `build_alias_index()`에서 정규화된 키를 만들고, `find_entity_candidates()`에서 boundary 체크 함수를 사용.

부작용

* recall(엔티티 발견률)이 떨어질 수 있음. 그래서 (2)의 mention span 보정과 함께 들어가야 손실을 상쇄할 수 있습니다.

---

4. 단기 보완: 문자열 슬롯 비교에서 “숫자만 다른 경우” 위배를 놓치는 문제(UNKNOWN 남발) 개선

문제

* `_compare_slot()`의 문자열 슬롯은 토큰 overlap 기반이라 “3서클 마법사 vs 4서클 마법사”처럼 핵심 숫자만 다른 경우가 UNKNOWN으로 빠질 수 있습니다. 또한 부분문자열 포함이면 너무 쉽게 OK가 됩니다.

개선안

* 문자열 슬롯 비교를 “텍스트 유사도 + 숫자/기호 기반 강제 규칙” 혼합으로 강화:

  1. 양쪽에 숫자가 존재하고 숫자 집합이 다르면 기본적으로 VIOLATE(또는 최소 UNKNOWN+강한 conflicting)로 처리
  2. 부분문자열 OK는 “한쪽이 다른 쪽을 포함하면서, 숫자/부정 키워드가 충돌하지 않을 때”로 제한
  3. slot별로 규칙을 달리 적용:

     * `job/talent/affiliation`: 숫자 차이는 강한 위배 신호
     * `place`: 숫자보다 지명/행정구역 변형(접미사 제거) 중심(현재 일부 구현 있음)
     * `time`: 문자열 비교 대신 파싱/정규화(최소 YYYY-MM-DD, HH:MM)
* 구현 포인트: `modules/nf_consistency/engine.py`의 `_compare_slot()` 내부에 숫자 추출 로직을 먼저 넣고, slot별 정책 테이블로 분기.

부작용

* “의도적으로 다르게 표현”한 문장(예: ‘3서클에 준하는’)에서 거짓 위배가 날 수 있음. 따라서 숫자 규칙을 “hard violate”로 하기보다, 초기에는 “UNKNOWN + CONFLICTING_EVIDENCE”로 보내고(사용자 확인 유도), 충분히 데이터가 쌓이면 hard violate로 올리는 단계적 접근이 안전합니다.

---

5. 중기 확장: time_key/timeline_idx를 “정합성 판정”에도 반영 (동일 인물의 시간축 변화 표현)

현재 상태

* time_key/timeline_idx는 retrieval 필터로만 쓰입니다(`modules/nf_retrieval/fts/fts_index.py`에서 time_anchor overlap 필터링). 정합성 판정(팩트 비교)은 시간축 개념이 거의 없습니다.

확장 방향

* fact에도 “유효 시간 범위/시점”을 붙여, claim의 time_key/timeline_idx와 호환되는 fact만 비교.
* 최소 구현(정확도 우선): time filter가 존재하면 fact 후보를 time-compatible한 것으로 제한하고, 없으면 기존처럼 비교하되 UNKNOWN을 보수적으로.

구체 구현 포인트(스키마 확장 필요)

* `schema_facts`에 `time_key`/`timeline_idx` 또는 `episode_id/scene_idx` 같은 qualifier 컬럼(또는 JSON constraints) 추가
* `_build_fact_index()`를 (slot_key, entity_id, time_bucket) 형태로 확장하거나, 후보를 가져온 뒤 후필터링

부작용

* DB/마이그레이션 비용이 큼. 하지만 장기적으로 “설정은 고정, 사건은 시간에 따라 변화”라는 소설 도메인에서는 필수에 가깝습니다.

---

6. 단기 보완: evidence “confirmed” 승격 조건을 과대승인되지 않게 보수화

문제

* `_promote_confirmed_evidence()`는 증거 span이 user_tag span 또는 approved evidence span과 “겹치기만 하면” confirmed로 승격합니다. chunk/span이 큰 경우 우연 겹침으로 confirmed가 부풀려질 수 있고, 이는 layer3 승격 조건(confirmed_evidence_count>=2)과 결합되면 거짓 OK로 이어질 수 있습니다.

개선안

* overlap을 “비율 기반”으로 바꾸거나(교집합 길이 / evidence 길이), 최소 교집합 길이를 둡니다.
* `chunk_id`가 있는 경우 chunk-level 단위로 더 엄격히(예: 동일 chunk_id에서 승인된 span이 존재해야 confirmed)
* 구현 포인트: `modules/nf_consistency/engine.py`의 `_overlaps_any_span()`/`_promote_confirmed_evidence()`에서 overlap 기준을 강화.

부작용

* confirmed가 줄어 layer3 승격이 덜 일어남(재현율 하락). 그러나 layer3 승격은 애초에 “과신 방지”가 우선이므로, 보수화가 맞습니다.

---

7. 중기 확장: 슬롯 추출(Extraction) 재현율을 “규칙+로컬모델” 혼합으로 끌어올리되, 오탐을 막는 게이트를 강화

현재 상태

* 기본 `rule_only`는 자연 서술형 문장에서 place/time/relation 등을 거의 못 잡습니다.
* 이미 `ExtractionPipeline`은 `hybrid_local/hybrid_remote/hybrid_dual`을 지원합니다.

개선안(정확도 우선)

* 기본을 무조건 모델로 바꾸기보다는, “모델 호출 게이트”를 강하게 둔 하이브리드로:

  1. rule로 slot이 0개면 모델 호출 후보
  2. segment에 특정 트리거가 있을 때만(예: 조사 패턴, 시간 표현, 이동 동사) 모델 호출
  3. 모델 candidate confidence가 slot별 최소 임계값을 넘을 때만 채택(현재는 전역 0.2 수준이라 느슨함)
* 구현 포인트

  * `modules/nf_consistency/extractors/pipeline.py`에서 `missing_slots` 처리 전에 “segment-level gating” 추가
  * `modules/nf_consistency/engine.py`에서 `_DEFAULT_CLAIM_CONFIDENCE_MIN`을 slot별로 분리(예: place/time는 0.6, job/age는 0.8 등)

부작용

* 성능 비용 및 모델 오탐. 그래서 “rule-only baseline 유지 + opt-in”을 기본으로 두고, 프로젝트 설정에서 단계적으로 활성화하는 편이 안전합니다.

---

8. 테스트/평가 보강(정확도 개선을 ‘회귀 없이’ 진행하기 위한 최소 장치)

현재 테스트는 기본 스모크에 가깝고, 정확도 취약 케이스(엔티티 미결정/숫자 문자열/대명사/별칭 충돌)를 강하게 고정하지 못합니다.

추가 권장 테스트(단위/품질 게이트)

* 엔티티 미결정 상태에서 “다른 인물 fact” 때문에 VIOLATE가 나오는 회귀를 막는 테스트
* 숫자 포함 문자열(job/talent)에서 “숫자만 다름”이 UNKNOWN으로 빠지지 않는 정책 테스트(정책이 hard-violate인지 soft-unknown인지에 맞춰 기대값 정의)
* 짧은 alias가 본문 단어 일부에 포함될 때 후보가 과대매칭되지 않는 테스트
* mention span 기반 entity 보정이 대명사 문장에서 작동하는 테스트(인덱싱 grouping을 포함한 e2e 형태)

---

참고할 만한 연구 축(방법론 근거)

* 사실 검증과 근거 기반 판정: Thorne et al., “FEVER”, NAACL 2018.
* 엔티티 링킹(별칭/표기 변형 견고화): Wu et al., “BLINK”, EMNLP 2020.
* 대명사/지시어 해소(코리퍼런스): Lee et al., “End-to-end Neural Coreference Resolution”, EMNLP 2017; Joshi et al., “SpanBERT”, TACL 2020(코리퍼런스/추출 기반으로 자주 결합).
* RAG 기본 구조: Lewis et al., “Retrieval-Augmented Generation”, NeurIPS 2020.

위 개선안 중 “정확도 최우선(오탐 억제)” 관점에서 가장 즉시 효과가 큰 것은 (1)+(2)+(4)입니다. 특히 (1)에서 엔티티 미결정 비교를 막지 않으면, 이후 어떤 고도화를 붙여도 특정 문체에서 거짓 VIOLATE가 구조적으로 발생할 수 있습니다.
