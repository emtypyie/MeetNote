"""SQLite index of meetings.

`metadata.json` inside each meeting's own folder is the authoritative
record for that meeting (it's what crash recovery reads). This database is
a fast, queryable index over those records for the dashboard — every write
here happens alongside a metadata.json write, never instead of one, and
listing code tolerates rows whose folder has since been deleted.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from storage.paths import db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    meeting_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    meeting_dir TEXT NOT NULL,
    template_id TEXT NOT NULL DEFAULT 'standard',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds REAL,
    status TEXT NOT NULL,
    transcription_device TEXT,
    ai_provider_used TEXT,
    notes_status TEXT
);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(db_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.execute(_SCHEMA)


def upsert_meeting(row: dict) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO meetings (
                meeting_id, title, meeting_dir, template_id, started_at, ended_at,
                duration_seconds, status, transcription_device, ai_provider_used, notes_status
            ) VALUES (:meeting_id, :title, :meeting_dir, :template_id, :started_at, :ended_at,
                      :duration_seconds, :status, :transcription_device, :ai_provider_used, :notes_status)
            ON CONFLICT(meeting_id) DO UPDATE SET
                title=excluded.title,
                ended_at=excluded.ended_at,
                duration_seconds=excluded.duration_seconds,
                status=excluded.status,
                transcription_device=excluded.transcription_device,
                ai_provider_used=excluded.ai_provider_used,
                notes_status=excluded.notes_status
            """,
            row,
        )


def list_meetings(limit: int = 200) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM meetings ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if Path(d["meeting_dir"]).exists():
            result.append(d)
    return result


def get_meeting(meeting_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM meetings WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_meeting(meeting_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM meetings WHERE meeting_id = ?", (meeting_id,))
