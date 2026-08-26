"""Crash-recovery scan, run once at engine startup.

Scans the meetings directory directly (the filesystem, not just the SQLite
index — metadata.json is the source of truth) for any meeting whose status
never reached a terminal state. Those are what the frontend offers to
Resume via "An unfinished meeting was found."

Along the way it also self-heals the SQLite index: if the engine crashed
before a DB upsert landed, the row is rebuilt here from metadata.json so
the dashboard and recovery prompt never disagree.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from storage import db
from storage.paths import meetings_root

logger = logging.getLogger("meetnote.recovery")

# "notes_pending" is terminal for *recovery* purposes even though notes
# generation hasn't finished — there's no audio capture left to resume, only
# an AI retry, which the completion/dashboard UI offers directly rather than
# through the crash-recovery "Resume previous meeting?" prompt.
TERMINAL_STATUSES = {"completed", "notes_pending"}


def scan_for_unfinished() -> list[dict]:
    root = meetings_root()
    if not root.exists():
        return []

    unfinished: list[dict] = []
    for meeting_dir in sorted(root.iterdir()):
        metadata_path = meeting_dir / "metadata.json"
        if not meeting_dir.is_dir() or not metadata_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.error("Corrupt metadata.json in %s; skipping recovery for it", meeting_dir)
            continue

        db.upsert_meeting(_metadata_to_row(metadata, meeting_dir))

        if metadata.get("status") not in TERMINAL_STATUSES:
            unfinished.append(metadata)

    if unfinished:
        logger.warning("Found %d unfinished meeting(s) on startup", len(unfinished))
    return unfinished


def _metadata_to_row(metadata: dict, meeting_dir: Path) -> dict:
    return {
        "meeting_id": metadata["meeting_id"],
        "title": metadata["title"],
        "meeting_dir": str(meeting_dir),
        "template_id": metadata.get("template_id", "standard"),
        "started_at": metadata["started_at"],
        "ended_at": metadata.get("ended_at"),
        "duration_seconds": metadata.get("duration_seconds"),
        "status": metadata.get("status", "error"),
        "transcription_device": (metadata.get("transcription_mode") or {}).get("device"),
        "ai_provider_used": metadata.get("ai_provider_used"),
        "notes_status": metadata.get("notes_status", "not_started"),
    }
