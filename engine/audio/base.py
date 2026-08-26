"""Platform-agnostic audio capture interface.

Nothing outside this package (and factory.py in particular) should ever
branch on OS. Concrete implementations live in windows.py / linux.py and are
selected by factory.py's AudioCaptureFactory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np


@dataclass
class AudioChunk:
    """One ~20-30s window of mixed mono 16kHz audio ready for transcription."""

    samples: np.ndarray  # float32, mono, `sample_rate` Hz
    sample_rate: int
    start_offset_seconds: float  # relative to meeting/session start
    end_offset_seconds: float
    mic_present: bool
    system_audio_present: bool


@dataclass
class AudioDeviceStatus:
    microphone_connected: bool = False
    microphone_name: Optional[str] = None
    system_audio_connected: bool = False
    system_audio_name: Optional[str] = None
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "microphone_connected": self.microphone_connected,
            "microphone_name": self.microphone_name,
            "system_audio_connected": self.system_audio_connected,
            "system_audio_name": self.system_audio_name,
            "last_error": self.last_error,
        }


AudioChunkCallback = Callable[[AudioChunk], None]


class AudioCapture(ABC):
    """What the rest of the app is allowed to know about audio capture.

    Users never see "WASAPI", "loopback", "monitor source", or "PipeWire" —
    the UI only ever renders `status()` as two simple indicators
    (Microphone / System Audio, connected or not). Advanced/manual device
    selection is a settings-layer concern built on top of this interface,
    not a reason to widen it.
    """

    @abstractmethod
    def start(
        self,
        on_chunk: AudioChunkCallback,
        chunk_seconds: float = 25.0,
        initial_offset_seconds: float = 0.0,
    ) -> None:
        """Begin capturing mic + system audio concurrently. `on_chunk` is
        invoked from a background thread every `chunk_seconds` with a mixed,
        ready-to-transcribe audio chunk. Must not block the caller.
        `initial_offset_seconds` lets a resumed-after-pause capture keep
        producing chunk timestamps that continue from where the meeting
        left off, instead of restarting the clock at zero."""

    @abstractmethod
    def stop(self) -> None:
        """Stop capture and release all devices."""

    @abstractmethod
    def status(self) -> AudioDeviceStatus:
        """Current connection status for the health panel / status bar."""

    @abstractmethod
    def refresh_devices(self) -> None:
        """Re-resolve default devices (e.g. after the user swaps
        headphones/mic mid-meeting). Implementations should prefer this over
        restarting the whole capture pipeline."""
