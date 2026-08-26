"""Runs the post-meeting AI pipeline for one meeting and persists the
result. Decoupled from any live MeetingSession so it can be re-run as a
"Retry Analysis" action even after an engine restart (product spec section
17 — the meeting is never lost just because AI analysis wasn't available
when the meeting ended).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from export.docx import write_docx
from export.markdown import write_markdown
from export.txt import write_notes_txt
from intelligence.analysis.service import NotesGenerationFailed, generate_notes
from intelligence.router import AIRouter
from intelligence.templates import get_template
from storage import db
from storage.meeting_store import MeetingStore

logger = logging.getLogger("meetnote.ai_pipeline")

BroadcastFn = Callable[[dict], None]


def run_ai_pipeline(meeting_id: str, ai_router: AIRouter, broadcast: BroadcastFn) -> None:
    row = db.get_meeting(meeting_id)
    if row is None:
        logger.error("run_ai_pipeline: unknown meeting_id %s", meeting_id)
        return

    meeting_dir = Path(row["meeting_dir"])
    store = MeetingStore.load(meeting_dir)

    store.set_status("generating_notes")
    db.upsert_meeting(store.to_summary_row())
    broadcast({"type": "notes_generating", "meeting_id": meeting_id})

    template = get_template(store.metadata.get("template_id", "standard"))
    transcript_text = store.read_transcript_text()
    if not transcript_text.strip():
        store.set_notes_result(None, "failed", ["Transcript is empty; nothing to analyze"])
        store.set_status("completed")
        db.upsert_meeting(store.to_summary_row())
        broadcast({"type": "notes_failed", "meeting_id": meeting_id, "reason": "empty transcript"})
        return

    markers = [m["offset_seconds"] for m in store.metadata.get("markers", [])]
    meeting_date = (store.metadata.get("started_at") or "")[:10]

    try:
        result = generate_notes(
            router=ai_router,
            transcript_text=transcript_text,
            meeting_title=store.metadata["title"],
            meeting_date=meeting_date,
            duration_seconds=store.metadata.get("duration_seconds") or 0.0,
            important_marker_offsets=markers,
            template=template,
        )
    except NotesGenerationFailed as exc:
        logger.error("AI notes generation failed for %s: %s", meeting_id, exc)
        store.set_notes_result(None, "pending", [str(exc)])
        store.set_status("completed")  # transcript itself is complete; only notes are pending
        db.upsert_meeting(store.to_summary_row())
        broadcast({"type": "notes_failed", "meeting_id": meeting_id, "reason": str(exc)})
        return

    write_markdown(meeting_dir, result.notes_markdown)
    write_notes_txt(meeting_dir, result.notes_markdown)
    write_docx(meeting_dir, store.metadata["title"], meeting_date, result.notes_markdown)

    warning_messages = [w.message for w in result.warnings]
    store.set_notes_result(result.provider_used, "completed", warning_messages)
    store.set_status("completed")
    db.upsert_meeting(store.to_summary_row())
    broadcast(
        {
            "type": "notes_ready",
            "meeting_id": meeting_id,
            "provider_used": result.provider_used,
            "warnings": warning_messages,
        }
    )
