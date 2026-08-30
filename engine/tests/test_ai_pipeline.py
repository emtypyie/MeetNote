"""Regression tests for engine/ai_pipeline.py's exception handling.

The AI pipeline must never leave a meeting's notes_status stuck at
"not_started" after an attempt was actually made — that would poll forever
on the Completion page (GENERATING_STATUSES / notes_status === "not_started"
in desktop/src/pages/Completion.tsx) with no retry action ever surfaced,
which is a silent failure indistinguishable from "still working".
"""

from __future__ import annotations

from storage import db
from storage.meeting_store import MeetingStore

import ai_pipeline


def _meeting_with_transcript(meeting_id: str) -> MeetingStore:
    store = MeetingStore.create(meeting_id, "Test AI Pipeline", "standard", {})
    (store.meeting_dir / "transcript.txt").write_text(
        "[00:00:00 - 00:00:25]\nWe discussed the budget.\n\n", encoding="utf-8"
    )
    row = store.to_summary_row()
    row["status"] = "generating_notes"
    db.upsert_meeting(row)
    return store


def test_notes_generation_failed_leaves_pending_and_completed(isolated_storage, monkeypatch):
    """The already-handled path: every configured provider failed. Notes end
    up 'pending' (retryable), meeting status is 'completed' (the transcript
    itself is done — only notes are outstanding)."""
    meeting_id = "test-ai-all-providers-failed"
    store = _meeting_with_transcript(meeting_id)

    def _raise_generation_failed(**kwargs):
        raise ai_pipeline.NotesGenerationFailed("All AI providers failed — simulated")

    monkeypatch.setattr(ai_pipeline, "generate_notes", _raise_generation_failed)

    events = []
    ai_pipeline.run_ai_pipeline(meeting_id, ai_router=None, broadcast=events.append)

    reloaded = MeetingStore.load(store.meeting_dir)
    assert reloaded.metadata["status"] == "completed"
    assert reloaded.metadata["notes_status"] == "pending"

    row = db.get_meeting(meeting_id)
    assert row["notes_status"] == "pending"
    assert row["status"] == "completed"

    assert any(e["type"] == "notes_failed" for e in events)


def test_unexpected_exception_during_generation_does_not_strand_meeting(isolated_storage, monkeypatch):
    """A bug or unexpected failure that is NOT NotesGenerationFailed (e.g. a
    KeyError, an unexpected provider response shape) must still resolve to a
    well-defined, retryable notes_status — never left at 'not_started'
    forever with status stuck other than 'completed'.

    This is a regression test: previously only NotesGenerationFailed was
    caught, so any other exception propagated out of run_ai_pipeline,
    leaving notes_status at whatever it was before the attempt
    ('not_started') even though a generation attempt was actually made and
    failed.
    """
    meeting_id = "test-ai-unexpected-crash"
    store = _meeting_with_transcript(meeting_id)
    assert store.metadata["notes_status"] == "not_started"

    def _raise_unexpected(**kwargs):
        raise KeyError("title")  # simulates a real bug, not a provider failure

    monkeypatch.setattr(ai_pipeline, "generate_notes", _raise_unexpected)

    events = []
    # Must not raise — run_ai_pipeline is called from a background executor
    # thread (see main.py's finish_and_generate_notes) with no caller left
    # to observe an exception.
    ai_pipeline.run_ai_pipeline(meeting_id, ai_router=None, broadcast=events.append)

    reloaded = MeetingStore.load(store.meeting_dir)
    assert reloaded.metadata["status"] == "completed"
    assert reloaded.metadata["notes_status"] == "failed"
    assert reloaded.metadata["notes_status"] != "not_started"
    assert any("Unexpected error" in w for w in reloaded.metadata["validation_warnings"])

    row = db.get_meeting(meeting_id)
    assert row["notes_status"] == "failed"
    assert row["status"] == "completed"

    assert any(e["type"] == "notes_failed" for e in events)


def test_empty_transcript_is_reported_not_silently_dropped(isolated_storage):
    meeting_id = "test-ai-empty-transcript"
    store = MeetingStore.create(meeting_id, "Test Empty Transcript", "standard", {})
    row = store.to_summary_row()
    row["status"] = "generating_notes"
    db.upsert_meeting(row)

    events = []
    ai_pipeline.run_ai_pipeline(meeting_id, ai_router=None, broadcast=events.append)

    reloaded = MeetingStore.load(store.meeting_dir)
    assert reloaded.metadata["status"] == "completed"
    assert reloaded.metadata["notes_status"] == "failed"
    assert any(e["type"] == "notes_failed" for e in events)


def test_unknown_meeting_id_does_not_raise(isolated_storage):
    # Called from a background thread with no caller to observe an
    # exception — must degrade to a logged no-op, never raise.
    ai_pipeline.run_ai_pipeline("does-not-exist", ai_router=None, broadcast=lambda msg: None)
