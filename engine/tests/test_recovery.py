"""Simulates a crash mid-meeting and verifies the recovery scan finds it,
and that nothing already-committed to disk is ever lost."""

from storage.meeting_store import MeetingStore
from recovery.checkpoint import scan_for_unfinished


def _chunk(index: int, text: str, status: str = "completed"):
    return {
        "chunk_index": index,
        "start_offset_seconds": index * 25.0,
        "end_offset_seconds": (index + 1) * 25.0,
        "text": text,
        "status": status,
        "device_used": "cpu",
        "mic_present": True,
        "system_audio_present": True,
        "error": None,
        "completed_at": 0.0,
    }


def test_recording_meeting_is_flagged_unfinished(isolated_storage):
    store = MeetingStore.create("m1", "Standup", "standard", {"device": "cpu", "model_size": "base"})
    store.set_status("recording")
    store.append_chunk_record(_chunk(0, "hello team"))
    store.append_chunk_record(_chunk(1, "let's get started"))

    unfinished = scan_for_unfinished()
    assert len(unfinished) == 1
    assert unfinished[0]["meeting_id"] == "m1"
    assert unfinished[0]["last_completed_chunk"] == 1


def test_completed_meeting_is_not_flagged(isolated_storage):
    store = MeetingStore.create("m2", "Retro", "standard", {"device": "cpu", "model_size": "base"})
    store.append_chunk_record(_chunk(0, "text"))
    store.finalize(duration_seconds=25.0)
    store.set_status("completed")

    unfinished = scan_for_unfinished()
    assert unfinished == []


def test_crash_after_two_chunks_preserves_both_on_disk(isolated_storage):
    store = MeetingStore.create("m3", "Planning", "standard", {"device": "cpu", "model_size": "base"})
    store.append_chunk_record(_chunk(0, "first chunk text"))
    store.append_chunk_record(_chunk(1, "second chunk text"))
    # Simulate the process dying right here, before chunk 2 or finalize().

    reloaded = MeetingStore.load(store.meeting_dir)
    chunks = reloaded.read_transcript_chunks()
    assert len(chunks) == 2
    assert chunks[0]["text"] == "first chunk text"
    assert chunks[1]["text"] == "second chunk text"
    assert reloaded.metadata["last_completed_chunk"] == 1
    assert "first chunk text" in reloaded.read_transcript_text()
    assert "second chunk text" in reloaded.read_transcript_text()


def test_failed_chunk_does_not_lose_neighboring_chunks(isolated_storage):
    store = MeetingStore.create("m4", "Sync", "standard", {"device": "cpu", "model_size": "base"})
    store.append_chunk_record(_chunk(0, "good chunk"))
    store.append_chunk_record(_chunk(1, "", status="failed"))
    store.append_chunk_record(_chunk(2, "another good chunk"))

    chunks = store.read_transcript_chunks()
    assert [c["status"] for c in chunks] == ["completed", "failed", "completed"]
    text = store.read_transcript_text()
    assert "good chunk" in text
    assert "another good chunk" in text
    assert "[transcription unavailable for this segment]" in text


def test_corrupt_metadata_is_skipped_not_fatal(isolated_storage):
    store = MeetingStore.create("m5", "Bad One", "standard", {"device": "cpu", "model_size": "base"})
    (store.meeting_dir / "metadata.json").write_text("{not valid json", encoding="utf-8")

    # Must not raise.
    unfinished = scan_for_unfinished()
    assert unfinished == []
