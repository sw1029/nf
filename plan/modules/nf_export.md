# nf-export (TXT/DOCX) — MoSCoW 구현 계획

nf-export는 문서/구간을 TXT/DOCX로 내보내고(필수), 옵션으로 메타데이터(태그/근거 요약)를 포함한다.

참조:

- `plan/contracts.md`
- `plan/architecture_1.md`

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

- Phase 90에서 구현(선행: Orchestrator/Jobs/SSE + DocStore)
- 1차는 TXT 우선, DOCX는 라이브러리 선택 후 확정

---

# [M] Must — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(placeholder 기준)

```text
modules/nf_export/
  __init__.py
  txt.py
  docx.py
  templates/
```

## 1) ExportRequest/Result 계약

* ☐ 입력: `{pid, range, format, include_meta}`
* ☐ 출력: `{artifact_path, size_bytes, created_at}`

## 2) TXT export

* ☐ 원문 + 선택 meta 섹션(최소)

## 3) DOCX export

* ☐ 기본 스타일 템플릿 적용(선택)
* ☐ 메타 포함 시: 표/부록 형태로 태그/근거 요약

## 4) 테스트(pytest)

* ☐ `tests/test_nf_export_contracts.py`: Exporter/ExportFormat 계약 스모크
* ☐ (차순위) TXT export 스모크(임시 파일)
* ☐ (차순위) DOCX export 스모크(라이브러리 의존은 구현 시 결정)

---

# [S] Should — 권장

* ☐ 템플릿 커스터마이징(서식)
* ☐ 근거 인용 카드(문서ID/섹션/태그경로) 첨부

---

# [C] Could — 여유 시

* ☐ “에피소드별 요약 테이블” 출력 옵션

---

# [W] Won’t (now)

* ☐ PDF export

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
