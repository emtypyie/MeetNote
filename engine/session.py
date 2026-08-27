"""MeetingSession — ties AudioCapture, TranscriptionPipeline, MeetingStore
and the state machine together for one meeting at a time.

MeetNote records one meeting at a time (matches the product's "New
Meeting" flow), so there is exactly one active MeetingSession, owned by
EngineState in main.py.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from audio.base import AudioCapture, AudioChunk
from state.machine import MeetingState, MeetingStateMachine
from storage import db
from storage.meeting_store import MeetingStore
from transcription.pipeline import ChunkRecord, TranscriptionPipeline
from transcription.whisper_engine import WhisperTranscriber

logger = logging.getLogger("meetnote.session")

BroadcastFn = Callable[[dict], None]


class MeetingSession:
    def __init__(
        self,
        meeting_id: str,
        store: MeetingStore,
        transcriber: WhisperTranscriber,
        audio_capture: AudioCapture,
        chunk_seconds: float,
        broadcast: BroadcastFn,
        output_language: str = "en",
        start_index: int = 0,
        initial_elapsed_seconds: float = 0.0,
        initial_state: MeetingState = MeetingState.PREPARING,
    ):
        self.meeting_id = meeting_id
        self.store = store
        self.transcriber = transcriber
        self.audio_capture = audio_capture
        self.chunk_seconds = chunk_seconds
        self.broadcast = broadcast

        self.state = MeetingStateMachine(initial_state)
        self.pipeline = TranscriptionPipeline(
            transcriber, self._on_chunk_result, output_language=output_language, start_index=start_index
        )

        self._elapsed_at_last_pause = initial_elapsed_seconds  # seconds of recorded (non-paused) time so far
        self._segment_start_wall: Optional[float] = None  # time.monotonic() when current run started
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------

    def start_recording(self) -> None:
        self.pipeline.start()
        self.audio_capture.start(self._on_audio_chunk, chunk_seconds=self.chunk_seconds)
        self._segment_start_wall = time.monotonic()
        self.state.transition(MeetingState.RECORDING)
        self.store.set_status("recording")
        self._sync_db()
        self._emit_state()

    def pause(self) -> None:
        self.state.transition(MeetingState.PAUSED)
        self._elapsed_at_last_pause += self._current_segment_elapsed()
        self._segment_start_wall = None
        self.audio_capture.stop()  # release devices; resumed cleanly below
        self.store.set_status("paused")
        self._sync_db()
        self._emit_state()

    def resume(self) -> None:
        self.state.transition(MeetingState.RESUMED)
        self.audio_capture.start(
            self._on_audio_chunk,
            chunk_seconds=self.chunk_seconds,
            initial_offset_seconds=self._elapsed_at_last_pause,
        )
        self._segment_start_wall = time.monotonic()
        self.state.transition(MeetingState.RECORDING)
        self.store.set_status("recording")
        self._sync_db()
        self._emit_state()

    def stop(self) -> float:
        """Stop capture and drain the transcription queue. Returns total
        recorded duration in seconds. The caller (main.py) is responsible
        for triggering AI notes generation afterward — this method only
        guarantees the transcript itself is complete and safely on disk."""
        self.state.transition(MeetingState.FINALIZING)
        self.store.set_status("finalizing")
        self._sync_db()
        self._emit_state()

        self.audio_capture.stop()
        duration = self._elapsed_at_last_pause + self._current_segment_elapsed()
        self._segment_start_wall = None
        self.pipeline.stop(drain=True)  # waits for in-flight chunks so the tail isn't lost

        self.store.finalize(duration)
        self._sync_db()
        return duration

    def set_generating_notes(self) -> None:
        self.state.transition(MeetingState.GENERATING_NOTES)
        self.store.set_status("generating_notes")
        self._sync_db()
        self._emit_state()

    def mark_completed(self) -> None:
        self.state.transition(MeetingState.COMPLETED)
        self.store.set_status("completed")
        self._sync_db()
        self._emit_state()

    def mark_error(self, reason: str) -> None:
        logger.error("Meeting %s entered ERROR state: %s", self.meeting_id, reason)
        if self.state.can_transition(MeetingState.ERROR):
            self.state.transition(MeetingState.ERROR)
        self.store.set_status("error")
        self._sync_db()
        self.broadcast({"type": "error", "message": reason})

    def mark_important(self) -> float:
        offset = self._elapsed_at_last_pause + self._current_segment_elapsed()
        self.store.add_marker(offset, "important")
        self.broadcast({"type": "marker_added", "offset_seconds": offset})
        return offset

    # -- internals --------------------------------------------------------

    def _current_segment_elapsed(self) -> float:
        if self._segment_start_wall is None:
            return 0.0
        return time.monotonic() - self._segment_start_wall

    def _on_audio_chunk(self, chunk: AudioChunk) -> None:
        self.pipeline.submit(chunk)

    def _on_chunk_result(self, record: ChunkRecord) -> None:
        self.store.append_chunk_record(record.to_dict())
        self.broadcast({"type": "transcript_chunk", **record.to_dict()})

    def _emit_state(self) -> None:
        self.broadcast({"type": "state_changed", "state": self.state.state.value})

    def _sync_db(self) -> None:
        db.upsert_meeting(self.store.to_summary_row())

    def elapsed_seconds(self) -> float:
        return self._elapsed_at_last_pause + self._current_segment_elapsed()

    def device_status(self) -> dict:
        return self.audio_capture.status().to_dict()

    def created_at_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
