from __future__ import annotations

import html
import zipfile
from pathlib import Path
from typing import Iterable, Literal


def _ensure_path(path: str | Path) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _paragraph(text: str) -> str:
    if text == "":
        return "<w:p/>"
    escaped = html.escape(text)
    return f"<w:p><w:r><w:t>{escaped}</w:t></w:r></w:p>"


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    def cell(text: str) -> str:
        escaped = html.escape(text)
        return f"<w:tc><w:p><w:r><w:t>{escaped}</w:t></w:r></w:p></w:tc>"

    def row(values: Iterable[str]) -> str:
        return "<w:tr>" + "".join(cell(value) for value in values) + "</w:tr>"

    parts = ["<w:tbl>", row(headers)]
    parts.extend(row(values) for values in rows)
    parts.append("</w:tbl>")
    return "".join(parts)


def _render_docx(paragraphs: list[str], table_xml: str = "") -> bytes:
    body = "".join(_paragraph(text) for text in paragraphs)
    if table_xml:
        body += table_xml
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:body>"
        + body
        + "</w:body></w:document>"
    ).encode("utf-8")


class ExporterImpl:
    def export_txt(
        self,
        input_path: Path | str,
        output_path: Path | str,
        *,
        include_meta: bool,
        meta_lines: list[str] | None = None,
    ) -> Path:
        input_path = _ensure_path(input_path)
        output_path = _ensure_path(output_path)
        text = input_path.read_text(encoding="utf-8")
        if include_meta:
            meta_block = "\n".join(meta_lines) if meta_lines else "[nf-export]"
            text = text + "\n\n" + meta_block
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        return output_path

    def export_docx(
        self,
        input_path: Path | str,
        output_path: Path | str,
        *,
        include_meta: bool,
        meta_lines: list[str] | None = None,
        meta_rows: list[dict[str, str]] | None = None,
    ) -> Path:
        input_path = _ensure_path(input_path)
        output_path = _ensure_path(output_path)
        text = input_path.read_text(encoding="utf-8")
        paragraphs = text.splitlines()
        table_xml = ""
        if include_meta:
            paragraphs.append("")
            if meta_lines:
                paragraphs.extend(meta_lines)
            else:
                paragraphs.append("[nf-export]")
            if meta_rows:
                headers = ["tag_path", "value", "status", "evidence"]
                rows = [
                    [
                        row.get("tag_path", ""),
                        row.get("value", ""),
                        row.get("status", ""),
                        row.get("evidence", ""),
                    ]
                    for row in meta_rows
                ]
                table_xml = _render_table(headers, rows)
        content_types = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
            "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
            "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
            "<Override PartName=\"/word/document.xml\" "
            "ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
            "</Types>"
        )
        rels = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            "<Relationship Id=\"rId1\" "
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" "
            "Target=\"word/document.xml\"/>"
            "</Relationships>"
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w") as docx:
            docx.writestr("[Content_Types].xml", content_types)
            docx.writestr("_rels/.rels", rels)
            docx.writestr("word/document.xml", _render_docx(paragraphs, table_xml))
        return output_path


def export_document(path: Path | None = None, format: Literal["txt", "docx"] = "txt") -> Path:
    if path is None:
        raise ValueError("path required")
    exporter = ExporterImpl()
    output = path.with_suffix(f".{format}")
    if format == "txt":
        return exporter.export_txt(path, output, include_meta=False)
    return exporter.export_docx(path, output, include_meta=False)
