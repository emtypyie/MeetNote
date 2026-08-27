"""Glues AudioCapture -> WhisperTranscriber -> persistence together.

Audio chunks are handed off through a queue to a single dedicated worker
thread, so a slow transcription (GPU busy, CPU mode on a big chunk, etc.)
never blocks the audio-capture threads from continuing to record — nothing
about receiving the next chunk of audio depends on the previous chunk having
finished transcribing.

    Audio Chunk -> queue -> Whisper -> ChunkRecord -> on_result (persist + broadcast) -> next chunk
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from audio.base import AudioChunk
from transcription.whisper_engine import WhisperTranscriber

logger = logging.getLogger("meetnote.pipeline")


@dataclass
class ChunkRecord:
    chunk_index: int
    start_offset_seconds: float
    end_offset_seconds: float
    text: str
    status: str  # "completed" | "failed"
    device_used: str
    mic_present: bool
    system_audio_present: bool
    error: Optional[str] = None
    completed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "chunk_index": self.chunk_index,
            "start_offset_seconds": self.start_offset_seconds,
            "end_offset_seconds": self.end_offset_seconds,
            "text": self.text,
            "status": self.status,
            "device_used": self.device_used,
            "mic_present": self.mic_present,
            "system_audio_present": self.system_audio_present,
            "error": self.error,
            "completed_at": self.completed_at,
        }


class TranscriptionPipeline:
    def __init__(
        self,
        transcriber: WhisperTranscriber,
        on_result: Callable[[ChunkRecord], None],
        output_language: str = "en",
        start_index: int = 0,
    ):
        self._transcriber = transcriber
        self._on_result = on_result
        self._output_language = output_language
        self._queue: "queue.Queue[AudioChunk]" = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._next_index = start_index  # seeded past already-committed chunks on crash-recovery resume
        self._pending_chunks = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._run, daemon=True, name="transcription-worker")
        self._worker.start()

    def submit(self, chunk: AudioChunk) -> None:
        with self._lock:
            self._pending_chunks += 1
        self._queue.put(chunk)

    def pending_count(self) -> int:
        with self._lock:
            return self._pending_chunks

    def stop(self, drain: bool = True, timeout: float = 60.0) -> None:
        """Stop accepting is implicit (caller stops calling submit). If
        `drain`, wait for already-queued chunks to finish transcribing
        before returning, so the meeting's final seconds aren't lost."""
        if drain:
            deadline = time.monotonic() + timeout
            while self.pending_count() > 0 and time.monotonic() < deadline:
                time.sleep(0.25)
        self._stop_event.set()
        self._queue.put(None)  # type: ignore[arg-type]  # sentinel to unblock get()
        if self._worker is not None:
            self._worker.join(timeout=10.0)

    def _run(self) -> None:
        while True:
            chunk = self._queue.get()
            if chunk is None:  # stop() sentinel
                break
            try:
                self._process(chunk)
            except Exception:
                logger.exception("Unhandled error processing audio chunk")
            finally:
                with self._lock:
                    self._pending_chunks = max(0, self._pending_chunks - 1)

    def _process(self, chunk: AudioChunk) -> None:
        with self._lock:
            index = self._next_index
            self._next_index += 1

        result = self._transcriber.transcribe_chunk(
            chunk.samples, chunk.sample_rate, output_language=self._output_language
        )
        if result.ok:
            text = " ".join(seg.text for seg in result.segments).strip()
            record = ChunkRecord(
                chunk_index=index,
                start_offset_seconds=chunk.start_offset_seconds,
                end_offset_seconds=chunk.end_offset_seconds,
                text=text,
                status="completed",
                device_used=result.device_used,
                mic_present=chunk.mic_present,
                system_audio_present=chunk.system_audio_present,
            )
        else:
            logger.error("Chunk %d failed after retries: %s", index, result.error)
            record = ChunkRecord(
                chunk_index=index,
                start_offset_seconds=chunk.start_offset_seconds,
                end_offset_seconds=chunk.end_offset_seconds,
                text="",
                status="failed",
                device_used=result.device_used,
                mic_present=chunk.mic_present,
                system_audio_present=chunk.system_audio_present,
                error=result.error,
            )

        self._on_result(record)
