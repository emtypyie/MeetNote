"""Shared capture implementation backed by the `soundcard` library.

`soundcard` wraps WASAPI on Windows and PulseAudio (including PipeWire's
pulse-compatible server, which is what "modern PipeWire" desktops expose)
on Linux behind one API, and in both cases exposes the default output
device's loopback/monitor stream via the same call:
`soundcard.get_microphone(id=<speaker.id>, include_loopback=True)`. That is
precisely the abstraction this product needs, so both platform
implementations subclass this one class and differ only in
platform-specific fallback behaviour (see windows.py / linux.py).

Design notes:
  - Mic and system audio are recorded on two independent background
    threads, each requesting resampling to SAMPLE_RATE directly from
    soundcard (avoids pulling in a separate resampling dependency).
  - A third "assembler" thread merges whatever frames arrived from each
    source over the last `chunk_seconds` window into one mixed mono chunk.
    If one source was silent or disconnected for the whole window, the
    other source's audio still ships on schedule (zero-filled for the
    missing side) — a mic dropout must not stall system-audio transcription
    and vice versa.
  - A source thread whose device disappears (unplugged headset, device
    switch) catches the resulting exception, marks that source
    disconnected, and retries with exponential backoff — it never tears
    down the other source or the meeting.
  - Raw audio is never buffered beyond the current in-flight chunk: once a
    chunk is handed to `on_chunk`, its samples are dropped from memory here.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import numpy as np

from audio.base import AudioCapture, AudioChunk, AudioChunkCallback, AudioDeviceStatus

logger = logging.getLogger("meetnote.audio")

SAMPLE_RATE = 16000  # what faster-whisper expects
BLOCK_SECONDS = 0.1
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_SECONDS)
MAX_BACKOFF_SECONDS = 10.0


class _SourceState:
    def __init__(self, name: str):
        self.name = name
        self.frames: list[np.ndarray] = []
        self.connected = False
        self.device_name: Optional[str] = None
        self.last_error: Optional[str] = None
        self.lock = threading.Lock()

    def push(self, frame: np.ndarray) -> None:
        with self.lock:
            self.frames.append(frame)

    def drain(self) -> np.ndarray:
        with self.lock:
            frames, self.frames = self.frames, []
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames)


class _SoundcardAudioCapture(AudioCapture):
    def __init__(self):
        self._mic_state = _SourceState("microphone")
        self._sys_state = _SourceState("system_audio")
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._on_chunk: Optional[AudioChunkCallback] = None
        self._chunk_seconds = 25.0
        self._session_start: float = 0.0
        self._initial_offset_seconds = 0.0
        self._status_lock = threading.Lock()

    # -- AudioCapture interface -------------------------------------------------

    def start(
        self,
        on_chunk: AudioChunkCallback,
        chunk_seconds: float = 25.0,
        initial_offset_seconds: float = 0.0,
    ) -> None:
        import soundcard as sc  # imported lazily so hardware detection etc. never
        # requires an audio backend to be importable on machines just running tests

        self._sc = sc
        self._on_chunk = on_chunk
        self._chunk_seconds = chunk_seconds
        self._initial_offset_seconds = initial_offset_seconds
        self._stop_event.clear()
        self._session_start = time.monotonic()

        mic_thread = threading.Thread(
            target=self._record_loop, args=("microphone",), daemon=True, name="audio-mic"
        )
        sys_thread = threading.Thread(
            target=self._record_loop, args=("system_audio",), daemon=True, name="audio-system"
        )
        assembler_thread = threading.Thread(
            target=self._assembler_loop, daemon=True, name="audio-assembler"
        )
        self._threads = [mic_thread, sys_thread, assembler_thread]
        for t in self._threads:
            t.start()
        logger.info("Audio capture started (chunk_seconds=%s)", chunk_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=5.0)
        self._threads = []
        logger.info("Audio capture stopped")

    def status(self) -> AudioDeviceStatus:
        with self._status_lock:
            return AudioDeviceStatus(
                microphone_connected=self._mic_state.connected,
                microphone_name=self._mic_state.device_name,
                system_audio_connected=self._sys_state.connected,
                system_audio_name=self._sys_state.device_name,
                last_error=self._mic_state.last_error or self._sys_state.last_error,
            )

    def refresh_devices(self) -> None:
        # Recording loops already re-resolve the default device on every
        # reconnect attempt, so a manual refresh just clears cached errors
        # to force an immediate retry rather than waiting for backoff.
        self._mic_state.last_error = None
        self._sys_state.last_error = None

    # -- internals ----------------------------------------------------------

    def _resolve_source(self, sc, source_kind: str):
        """Resolve the actual `soundcard` device for `source_kind`.

        Takes the `soundcard` module as an explicit parameter (rather than
        reading `self._sc`, which is only ever set by `start()`) so this same
        resolution logic — including the Linux pactl fallback in the
        `LinuxAudioCapture` override — can also be reused by
        `audio/health.py`'s background probe, which never calls `start()` at
        all. Without this, health-check probing and real recording could
        silently disagree about how to find the system-audio device on a
        given machine, which is exactly the kind of inconsistency that would
        make Linux's health status untrustworthy relative to what actually
        happens when a meeting starts.
        """
        if source_kind == "microphone":
            return sc.default_microphone()
        speaker = sc.default_speaker()
        return sc.get_microphone(id=str(speaker.id), include_loopback=True)

    def _set_connected(self, source_kind: str, connected: bool, name: Optional[str], error: Optional[str] = None):
        state = self._mic_state if source_kind == "microphone" else self._sys_state
        with self._status_lock:
            state.connected = connected
            if name is not None:
                state.device_name = name
            state.last_error = error

    def _record_loop(self, source_kind: str) -> None:
        state = self._mic_state if source_kind == "microphone" else self._sys_state
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                device = self._resolve_source(self._sc, source_kind)
                with device.recorder(samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK_SIZE) as rec:
                    self._set_connected(source_kind, True, device.name)
                    backoff = 1.0
                    while not self._stop_event.is_set():
                        data = rec.record(numframes=BLOCK_SIZE)
                        frame = np.asarray(data)[:, 0].astype(np.float32)
                        state.push(frame)
            except Exception as exc:  # device unplugged, switched, permission error, etc.
                self._set_connected(source_kind, False, None, error=str(exc))
                logger.warning("%s capture error, retrying in %.1fs: %s", source_kind, backoff, exc)
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    def _assembler_loop(self) -> None:
        expected_samples = int(self._chunk_seconds * SAMPLE_RATE)
        next_boundary = self._session_start + self._chunk_seconds
        chunk_start_offset = self._initial_offset_seconds

        while not self._stop_event.is_set():
            now = time.monotonic()
            sleep_for = max(0.0, next_boundary - now)
            if self._stop_event.wait(min(sleep_for, 0.5)):
                break
            if time.monotonic() < next_boundary:
                continue

            mic_present = self._mic_state.connected
            sys_present = self._sys_state.connected
            mic_audio = self._mic_state.drain()
            sys_audio = self._sys_state.drain()

            mixed = _mix(mic_audio, sys_audio, expected_samples)
            chunk_end_offset = chunk_start_offset + self._chunk_seconds

            if self._on_chunk is not None:
                try:
                    self._on_chunk(
                        AudioChunk(
                            samples=mixed,
                            sample_rate=SAMPLE_RATE,
                            start_offset_seconds=chunk_start_offset,
                            end_offset_seconds=chunk_end_offset,
                            mic_present=mic_present,
                            system_audio_present=sys_present,
                        )
                    )
                except Exception:
                    logger.exception("on_chunk callback raised; continuing capture")

            chunk_start_offset = chunk_end_offset
            next_boundary += self._chunk_seconds

        # Flush whatever partial audio remains when stopping mid-chunk so the
        # tail of the meeting isn't silently dropped.
        mic_audio = self._mic_state.drain()
        sys_audio = self._sys_state.drain()
        if (mic_audio.size or sys_audio.size) and self._on_chunk is not None:
            tail_len = max(mic_audio.size, sys_audio.size)
            mixed = _mix(mic_audio, sys_audio, tail_len)
            try:
                self._on_chunk(
                    AudioChunk(
                        samples=mixed,
                        sample_rate=SAMPLE_RATE,
                        start_offset_seconds=chunk_start_offset,
                        end_offset_seconds=chunk_start_offset + tail_len / SAMPLE_RATE,
                        mic_present=self._mic_state.connected,
                        system_audio_present=self._sys_state.connected,
                    )
                )
            except Exception:
                logger.exception("on_chunk callback raised while flushing final chunk")


def _mix(a: np.ndarray, b: np.ndarray, target_len: int) -> np.ndarray:
    a = _pad_or_trim(a, target_len)
    b = _pad_or_trim(b, target_len)
    return np.clip(a + b, -1.0, 1.0).astype(np.float32)


def _pad_or_trim(arr: np.ndarray, target_len: int) -> np.ndarray:
    if arr.size == target_len:
        return arr
    if arr.size > target_len:
        return arr[:target_len]
    return np.pad(arr, (0, target_len - arr.size))
