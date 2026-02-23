from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol


ExportFormat = Literal["txt", "docx"]


class Exporter(Protocol):
    def export_txt(
        self,
        input_path: Path,
        output_path: Path,
        *,
        include_meta: bool,
        meta_lines: list[str] | None = None,
    ) -> Path: ...

    def export_docx(
        self,
        input_path: Path,
        output_path: Path,
        *,
        include_meta: bool,
        meta_lines: list[str] | None = None,
        meta_rows: list[dict[str, str]] | None = None,
    ) -> Path: ...
