from pathlib import Path
from typing import Literal


def export_document(path: Path | None = None, format: Literal["txt", "docx"] = "txt") -> None:
    """
    지정 형식으로 문서 내보내기(placeholder).

    예정: 메타데이터/인용 포함 선택형 렌더링.
    """
    _ = (path, format)
    raise NotImplementedError("nf_export.export_document는 placeholder입니다.")
