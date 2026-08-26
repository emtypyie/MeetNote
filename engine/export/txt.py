from __future__ import annotations

import re
from pathlib import Path


def _markdown_to_plain(markdown_text: str) -> str:
    lines = []
    for line in markdown_text.splitlines():
        stripped = re.sub(r"^#{1,6}\s*", "", line)  # drop heading markers, keep the text
        stripped = re.sub(r"^[-*]\s+", "- ", stripped)  # normalize bullets
        lines.append(stripped)
    return "\n".join(lines)


def write_notes_txt(meeting_dir: Path, notes_markdown: str) -> Path:
    path = meeting_dir / "notes.txt"
    path.write_text(_markdown_to_plain(notes_markdown), encoding="utf-8")
    return path
