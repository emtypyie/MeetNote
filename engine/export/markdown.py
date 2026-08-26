from __future__ import annotations

from pathlib import Path


def write_markdown(meeting_dir: Path, notes_markdown: str) -> Path:
    path = meeting_dir / "notes.md"
    path.write_text(notes_markdown, encoding="utf-8")
    return path
