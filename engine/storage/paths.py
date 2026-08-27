"""Filesystem layout.

    ~/MeetNote/
      meetnote.db
      config.json
      logs/
        engine.log
      meetings/
        2026-08-27_1900_house-meeting/
          metadata.json
          transcript.txt
          transcript.json
          notes.md
          notes.txt

The storage root is overridable via config (Settings > Storage >
"Transcript storage location"); `set_storage_root` is called once at
startup after config is loaded.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_default_root = Path.home() / "MeetNote"
_storage_root = _default_root


def set_storage_root(path: Path) -> None:
    global _storage_root
    _storage_root = path
    ensure_dirs()


def storage_root() -> Path:
    return _storage_root


def meetings_root() -> Path:
    return _storage_root / "meetings"


def db_path() -> Path:
    return _storage_root / "meetnote.db"


def config_path() -> Path:
    return _storage_root / "config.json"


def logs_dir() -> Path:
    return _storage_root / "logs"


def ensure_dirs() -> None:
    meetings_root().mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "meeting"


def new_meeting_dir(title: str, started_at: datetime | None = None) -> Path:
    started_at = started_at or datetime.now()
    folder_name = f"{started_at:%Y-%m-%d_%H%M}_{slugify(title)}"
    meeting_dir = meetings_root() / folder_name
    meeting_dir.mkdir(parents=True, exist_ok=True)
    return meeting_dir
