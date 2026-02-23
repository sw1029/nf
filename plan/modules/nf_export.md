# nf-export (TXT/DOCX) — MoSCoW 구현 계획

nf-export는 문서/구간을 TXT/DOCX로 내보내고(필수), 옵션으로 메타데이터(태그/근거 요약)를 포함한다.

> 표기 규칙: ☐ TODO / ☑ Done / ◐ Partial(스텁/의도 미적용)

참조:

- `plan/contracts.md`
- `plan/architecture_1.md`

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

테스트는 conda의 `nf` 환경에서 수행한다.

- Phase 90에서 구현(선행: 오케스트레이터/잡/SSE + DocStore)
- 1차는 TXT 우선, DOCX는 라이브러리 선택 후 확정

---

# [M] 필수 — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(플레이스홀더 기준)

```text
modules/nf_export/
  __init__.py
  txt.py
  docx.py
  templates/
```

## 1) ExportRequest/Result 계약

* ☑ 입력: `{project_id, range, format, include_meta}`
* ☑ 출력: `{artifact_path, size_bytes, created_at}`

## 2) TXT 내보내기

* ☑ 원문 + 선택 메타 섹션(최소)

## 3) DOCX 내보내기

* ☑ 기본 스타일 템플릿 적용(선택)
* ☑ 메타 포함 시: 표/부록 형태로 태그/근거 요약

## 4) 테스트(pytest)

* ☑ `tests/test_nf_export_contracts.py`: Exporter/ExportFormat 계약 스모크
* ☐ (차순위) TXT 내보내기 스모크(임시 파일)
* ☐ (차순위) DOCX 내보내기 스모크(라이브러리 의존은 구현 시 결정)

---

# [S] 권장 — 권장

* ☐ 템플릿 커스터마이징(서식)
* ☐ 근거 인용 카드(문서ID/섹션/태그경로) 첨부

---

# [C] 선택 — 여유 시

* ☐ “에피소드별 요약 테이블” 출력 옵션

---

# [W] 현재 제외

* ☐ PDF 내보내기

---

## 계약 인터페이스(상세; 구현 기준)

```python
from typing import Literal, Protocol
from pathlib import Path


class Exporter(Protocol):
    def export_txt(self, input_path: Path, output_path: Path, *, include_meta: bool) -> Path: ...
    def export_docx(self, input_path: Path, output_path: Path, *, include_meta: bool) -> Path: ...


ExportFormat = Literal["txt", "docx"]
```
