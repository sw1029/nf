from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol


ExportFormat = Literal["txt", "docx"]


class Exporter(Protocol):
    def export_txt(self, input_path: Path, output_path: Path, *, include_meta: bool) -> Path: ...

    def export_docx(self, input_path: Path, output_path: Path, *, include_meta: bool) -> Path: ...

