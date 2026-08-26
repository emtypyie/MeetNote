"""Atomic file writes.

Every checkpoint write (metadata.json, transcript.json) goes through this so
a crash or power loss mid-write can never leave a corrupt, half-written
file behind — the file on disk is always either the previous complete
version or the new complete version, never a truncated mix of both. This is
what makes crash recovery trustworthy.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, content: str) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)  # atomic on both Windows and POSIX


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def append_text(path: Path, content: str) -> None:
    """Append is not atomic the same way, but combined with fsync this
    minimizes the crash window, and transcript.txt is a human-readable
    convenience copy — transcript.json (written atomically) is the
    authoritative source used for recovery."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
