"""Renders the generated Markdown notes into a .docx that mirrors the
configured template's section structure as closely as practical."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Pt


def write_docx(meeting_dir: Path, meeting_title: str, meeting_date: str, notes_markdown: str) -> Path:
    doc = Document()

    doc.add_heading(meeting_title, level=0)
    doc.add_paragraph(meeting_date)

    for raw_line in notes_markdown.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=1)
        elif line.startswith("# "):
            doc.add_heading(line[2:].strip(), level=1)
        elif line.startswith("- ") or line.startswith("* "):
            doc.add_paragraph(line[2:].strip(), style="List Bullet")
        else:
            p = doc.add_paragraph(line)
            p.paragraph_format.space_after = Pt(6)

    path = meeting_dir / "notes.docx"
    doc.save(str(path))
    return path
