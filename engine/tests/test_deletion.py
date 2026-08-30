import os
import shutil
import stat

import pytest
from fastapi.testclient import TestClient

import main
from main import app
from storage import db
from storage.meeting_store import MeetingStore
from storage.paths import meetings_root

client = TestClient(app)

def test_delete_meeting(isolated_storage):
    # Setup
    meeting_id = "test-delete-123"
    store = MeetingStore.create(meeting_id, "Test Deletion", "standard", {})
    
    # Verify creation
    assert store.meeting_dir.exists()
    
    # DB entry must exist for main.py to delete it
    row = store.to_summary_row()
    row["status"] = "completed"
    db.upsert_meeting(row)
    
    # Execute deletion
    resp = client.delete(f"/meetings/{meeting_id}")
    
    # Assert successful
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "meeting_id": meeting_id}
    
    # Assert directory and files are gone
    assert not store.meeting_dir.exists()
    
    # Assert DB is updated
    assert db.get_meeting(meeting_id) is None

@pytest.mark.parametrize(
    "status", ["preparing", "recording", "paused", "finalizing", "generating_notes"]
)
def test_delete_active_meeting(isolated_storage, status):
    """Every status during which a live MeetingSession or the background AI
    pipeline could still be touching the meeting's files must be rejected —
    not just "recording"/"paused". In particular, "finalizing" and
    "generating_notes" matter because the Completion page's Delete button
    has no status guard of its own; the backend is the only thing standing
    between a user clicking Delete mid-AI-generation and a race against
    ai_pipeline.run_ai_pipeline writing notes.md/notes.txt into the same
    directory being rmtree'd."""
    meeting_id = f"test-active-{status}"
    store = MeetingStore.create(meeting_id, "Test Active", "standard", {})

    row = store.to_summary_row()
    row["status"] = status
    db.upsert_meeting(row)

    resp = client.delete(f"/meetings/{meeting_id}")

    assert resp.status_code == 400
    # The frontend detects this case by checking for "active" in the message
    # (see desktop/src/pages/Completion.tsx) — keep that contract.
    assert "active" in resp.json()["detail"].lower()

    # Assert directory still exists
    assert store.meeting_dir.exists()
    # Assert DB still has it
    assert db.get_meeting(meeting_id) is not None


def test_delete_error_status_meeting_is_allowed(isolated_storage):
    """"error" is terminal (covers both a genuine failure and a
    recovery-abandoned meeting — see /meetings/{id}/abandon) and must remain
    deletable, unlike the still-active statuses above."""
    meeting_id = "test-error-status"
    store = MeetingStore.create(meeting_id, "Test Error Status", "standard", {})

    row = store.to_summary_row()
    row["status"] = "error"
    db.upsert_meeting(row)

    resp = client.delete(f"/meetings/{meeting_id}")

    assert resp.status_code == 200
    assert not store.meeting_dir.exists()
    assert db.get_meeting(meeting_id) is None

def test_delete_nonexistent_meeting(isolated_storage):
    resp = client.delete("/meetings/does-not-exist")
    assert resp.status_code == 404


def test_delete_meeting_when_directory_already_missing_still_succeeds(isolated_storage):
    """The meeting folder can already be gone (manually deleted outside the
    app, moved, etc.) — deletion should still clean up the now-orphaned
    database record rather than getting stuck, since there is nothing left
    on disk to fail to remove."""
    meeting_id = "test-already-missing-123"
    store = MeetingStore.create(meeting_id, "Test Already Missing", "standard", {})

    row = store.to_summary_row()
    row["status"] = "completed"
    db.upsert_meeting(row)

    shutil.rmtree(store.meeting_dir)
    assert not store.meeting_dir.exists()

    resp = client.delete(f"/meetings/{meeting_id}")

    assert resp.status_code == 200
    assert db.get_meeting(meeting_id) is None


def test_delete_meeting_with_readonly_file(isolated_storage):
    """A note file left read-only (e.g. still marked read-only by an editor
    or sync tool) must not block deletion — main.py's shutil.rmtree onerror
    handler clears the flag and retries. Regression test for a bug where the
    handler referenced `os.chmod` without `os` ever being imported, so it
    raised NameError, was silently swallowed, and the read-only file (and
    therefore the whole meeting directory) was never actually removed."""
    meeting_id = "test-readonly-123"
    store = MeetingStore.create(meeting_id, "Test Readonly", "standard", {})

    readonly_file = store.meeting_dir / "notes.md"
    readonly_file.write_text("notes", encoding="utf-8")
    os.chmod(readonly_file, stat.S_IREAD)

    row = store.to_summary_row()
    row["status"] = "completed"
    db.upsert_meeting(row)

    try:
        resp = client.delete(f"/meetings/{meeting_id}")
    finally:
        # Defensive cleanup in case the assertion below fails and the
        # directory (with its read-only file) is left behind on disk.
        if readonly_file.exists():
            os.chmod(readonly_file, stat.S_IWRITE)

    assert resp.status_code == 200
    assert not store.meeting_dir.exists()
    assert db.get_meeting(meeting_id) is None


def test_delete_meeting_genuinely_locked_file_reports_failure_and_preserves_record(
    isolated_storage, monkeypatch
):
    """A file that is genuinely undeletable (locked by another process, a
    permission error that survives the chmod retry, etc.) must never be
    reported as a successful deletion. `_purge_meeting_directory` is
    monkeypatched to simulate that outcome deterministically — real OS-level
    file locking is flaky to rely on in a unit test — but the deletion
    endpoint's contract (500, DB record preserved, directory untouched) is
    exactly what a real locked file would also trigger via the onerror
    handler's error collection."""
    meeting_id = "test-locked-123"
    store = MeetingStore.create(meeting_id, "Test Locked", "standard", {})
    (store.meeting_dir / "notes.md").write_text("notes", encoding="utf-8")

    row = store.to_summary_row()
    row["status"] = "completed"
    db.upsert_meeting(row)

    monkeypatch.setattr(
        main, "_purge_meeting_directory", lambda meeting_dir: [f"{meeting_dir / 'notes.md'}: simulated lock"]
    )

    resp = client.delete(f"/meetings/{meeting_id}")

    assert resp.status_code == 500
    # No silent success: the record must still be there so the user can see
    # the meeting still exists and retry deletion.
    assert db.get_meeting(meeting_id) is not None
    assert store.meeting_dir.exists()


def test_delete_meeting_failure_preserves_unrelated_meetings(isolated_storage, monkeypatch):
    """A failed deletion of one meeting must not affect any other meeting's
    database record or files."""
    locked_id = "test-locked-other-1"
    locked_store = MeetingStore.create(locked_id, "Locked Meeting", "standard", {})
    locked_row = locked_store.to_summary_row()
    locked_row["status"] = "completed"
    db.upsert_meeting(locked_row)

    safe_id = "test-unaffected-1"
    safe_store = MeetingStore.create(safe_id, "Unaffected Meeting", "standard", {})
    safe_row = safe_store.to_summary_row()
    safe_row["status"] = "completed"
    db.upsert_meeting(safe_row)

    monkeypatch.setattr(main, "_purge_meeting_directory", lambda meeting_dir: ["simulated lock"])

    resp = client.delete(f"/meetings/{locked_id}")
    assert resp.status_code == 500

    # The unrelated meeting must be completely unaffected.
    assert db.get_meeting(safe_id) is not None
    assert safe_store.meeting_dir.exists()
    assert (safe_store.meeting_dir / "metadata.json").exists()


def test_delete_meeting_rejects_path_outside_meetings_root(isolated_storage):
    """A meeting_dir pointing outside the meetings root must be rejected.

    This specifically exercises the case a raw `str(path).startswith(...)`
    containment check gets wrong: "<root>/meetings_backup" *string-prefix*
    matches "<root>/meetings", so a naive check would have let this through.
    `Path.is_relative_to()` correctly treats them as unrelated siblings.
    """
    outside_dir = meetings_root().parent / "meetings_backup" / "not-a-real-meeting"
    outside_dir.mkdir(parents=True)
    sentinel = outside_dir / "should-not-be-touched.txt"
    sentinel.write_text("do not delete me", encoding="utf-8")

    meeting_id = "test-traversal-123"
    db.upsert_meeting(
        {
            "meeting_id": meeting_id,
            "title": "Traversal Attempt",
            "meeting_dir": str(outside_dir),
            "template_id": "standard",
            "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": None,
            "duration_seconds": None,
            "status": "completed",
            "transcription_device": None,
            "ai_provider_used": None,
            "notes_status": "not_started",
        }
    )

    resp = client.delete(f"/meetings/{meeting_id}")

    assert resp.status_code == 400
    assert sentinel.exists()
    # The (invalid) record is intentionally left alone rather than silently
    # dropped — there is nothing safe to clean up automatically here.
    assert db.get_meeting(meeting_id) is not None


def test_delete_meeting_rejects_symlinked_meeting_dir(isolated_storage):
    """A meeting_dir that is a symlink is never created by the app itself
    (storage/paths.py:new_meeting_dir always makes a plain directory) —
    finding one means the filesystem entry was tampered with or replaced out
    of band. Deletion must refuse it rather than following it into
    shutil.rmtree."""
    real_target = meetings_root().parent / "real-target"
    real_target.mkdir(parents=True)
    (real_target / "sentinel.txt").write_text("do not delete me", encoding="utf-8")

    link_path = meetings_root() / "2026-01-01_0000_symlinked-meeting"
    try:
        os.symlink(real_target, link_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks is not permitted in this environment")

    meeting_id = "test-symlink-123"
    db.upsert_meeting(
        {
            "meeting_id": meeting_id,
            "title": "Symlink Attempt",
            "meeting_dir": str(link_path),
            "template_id": "standard",
            "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": None,
            "duration_seconds": None,
            "status": "completed",
            "transcription_device": None,
            "ai_provider_used": None,
            "notes_status": "not_started",
        }
    )

    resp = client.delete(f"/meetings/{meeting_id}")

    assert resp.status_code == 400
    assert (real_target / "sentinel.txt").exists()
