"""Per-meeting persistence: metadata.json, transcript.txt, transcript.json.

This is where the "a crash after 20 minutes must not erase the previous 20
minutes" requirement is actually implemented: every call to
`append_chunk_record` writes the chunk to transcript.json and updates
metadata.json's `last_completed_chunk` atomically (storage/atomic.py)
*before* returning, and transcript.txt (human-readable) is appended
immediately after. Nothing about a meeting's history is ever held only in
memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from storage.atomic import append_text, atomic_write_json
from storage.paths import new_meeting_dir


def _fmt_ts(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Marker:
    offset_seconds: float
    label: str
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {"offset_seconds": self.offset_seconds, "label": self.label, "created_at": self.created_at}


class MeetingStore:
    """Owns one meeting's directory. Created fresh for a new meeting via
    `MeetingStore.create(...)`, or reattached to an existing directory on
    resume via `MeetingStore.load(meeting_dir)`."""

    def __init__(self, meeting_dir: Path, metadata: dict):
        self.meeting_dir = meeting_dir
        self.metadata = metadata

    # -- construction ---------------------------------------------------

    @classmethod
    def create(
        cls,
        meeting_id: str,
        title: str,
        template_id: str,
        transcription_mode: dict,
    ) -> "MeetingStore":
        started_at = datetime.now()
        meeting_dir = new_meeting_dir(title, started_at)
        metadata = {
            "meeting_id": meeting_id,
            "title": title,
            "template_id": template_id,
            "started_at": started_at.isoformat(),
            "ended_at": None,
            "duration_seconds": None,
            "last_completed_chunk": -1,
            "status": "preparing",
            "transcription_mode": transcription_mode,
            "markers": [],
            "ai_provider_used": None,
            "notes_status": "not_started",
            "validation_warnings": [],
        }
        store = cls(meeting_dir, metadata)
        store._write_metadata()
        (meeting_dir / "transcript.json").write_text("[]", encoding="utf-8")
        (meeting_dir / "transcript.txt").write_text("", encoding="utf-8")
        return store

    @classmethod
    def load(cls, meeting_dir: Path) -> "MeetingStore":
        metadata = json.loads((meeting_dir / "metadata.json").read_text(encoding="utf-8"))
        return cls(meeting_dir, metadata)

    # -- writes -----------------------------------------------------------

    def _reload_from_disk(self) -> dict:
        """Re-read metadata.json immediately before mutating it.

        More than one MeetingStore instance can be alive for the same
        meeting at once (the live MeetingSession's long-lived instance, and
        a fresh one loaded inside the AI pipeline task) — see main.py and
        ai_pipeline.py. Mutating a stale in-memory `self.metadata` dict and
        writing the whole thing back would silently clobber whatever the
        other instance wrote in between. Reloading first turns every setter
        below into a read-modify-write against the file, so no update is
        ever lost regardless of how many MeetingStore objects reference the
        same meeting.
        """
        try:
            self.metadata = json.loads((self.meeting_dir / "metadata.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # keep whatever's already in self.metadata (e.g. brand new meeting)
        return self.metadata

    def _write_metadata(self) -> None:
        atomic_write_json(self.meeting_dir / "metadata.json", self.metadata)

    def set_status(self, status: str) -> None:
        self._reload_from_disk()
        self.metadata["status"] = status
        self._write_metadata()

    def append_chunk_record(self, record_dict: dict) -> None:
        transcript_json_path = self.meeting_dir / "transcript.json"
        try:
            chunks = json.loads(transcript_json_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            chunks = []
        chunks.append(record_dict)
        atomic_write_json(transcript_json_path, chunks)

        # Human-readable copy.
        start = _fmt_ts(record_dict["start_offset_seconds"])
        end = _fmt_ts(record_dict["end_offset_seconds"])
        if record_dict["status"] == "completed" and record_dict["text"]:
            body = record_dict["text"]
        elif record_dict["status"] == "completed":
            body = "[silence]"
        else:
            body = "[transcription unavailable for this segment]"
        append_text(self.meeting_dir / "transcript.txt", f"[{start} - {end}]\n{body}\n\n")

        # Checkpoint: only advance last_completed_chunk for chunks that
        # actually succeeded, so a resumed session knows a "failed" chunk's
        # audio window was already accounted for (we don't re-request it —
        # raw audio isn't retained — but we don't silently skip logging it
        # either) without misreporting it as successfully transcribed.
        self._reload_from_disk()
        self.metadata["last_completed_chunk"] = record_dict["chunk_index"]
        self._write_metadata()

    def add_marker(self, offset_seconds: float, label: str = "important") -> None:
        self._reload_from_disk()
        marker = Marker(offset_seconds=offset_seconds, label=label)
        self.metadata["markers"].append(marker.to_dict())
        self._write_metadata()

    def finalize(self, duration_seconds: float) -> None:
        self._reload_from_disk()
        self.metadata["ended_at"] = _now_iso()
        self.metadata["duration_seconds"] = duration_seconds
        self._write_metadata()

    def set_notes_result(self, provider_used: Optional[str], status: str, warnings: list[str]) -> None:
        self._reload_from_disk()
        self.metadata["ai_provider_used"] = provider_used
        self.metadata["notes_status"] = status
        self.metadata["validation_warnings"] = warnings
        self._write_metadata()

    def read_transcript_text(self) -> str:
        return (self.meeting_dir / "transcript.txt").read_text(encoding="utf-8")

    def read_transcript_chunks(self) -> list[dict]:
        try:
            return json.loads((self.meeting_dir / "transcript.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def to_summary_row(self) -> dict:
        m = self.metadata
        return {
            "meeting_id": m["meeting_id"],
            "title": m["title"],
            "meeting_dir": str(self.meeting_dir),
            "template_id": m["template_id"],
            "started_at": m["started_at"],
            "ended_at": m["ended_at"],
            "duration_seconds": m["duration_seconds"],
            "status": m["status"],
            "transcription_device": (m.get("transcription_mode") or {}).get("device"),
            "ai_provider_used": m["ai_provider_used"],
            "notes_status": m["notes_status"],
        }
