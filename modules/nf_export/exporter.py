from pathlib import Path
from typing import Literal


def export_document(path: Path | None = None, format: Literal["txt", "docx"] = "txt") -> None:
    """
    Export document to the given format (placeholder).

    Planned: render text/docx with optional metadata/citations.
    """
    _ = (path, format)
    raise NotImplementedError("nf_export.export_document is a placeholder.")
