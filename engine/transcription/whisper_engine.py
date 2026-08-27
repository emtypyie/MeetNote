"""faster-whisper wrapper with automatic GPU->CPU fallback.

This is deliberately separate from hardware/detector.py's pre-flight CUDA
check: that check decides the *initial* mode, but if GPU model loading
still fails for some reason not caught by the pre-flight probe (VRAM
exhausted by another app, driver hiccup, etc.), this class catches it at
load time and swaps to CPU automatically rather than crashing the meeting —
the "Automatic GPU-to-CPU fallback" requirement is implemented at both
layers on purpose (defense in depth).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from cuda_env import configure_cuda_dll_search_path

configure_cuda_dll_search_path()  # must run before faster_whisper/ctranslate2 touch the GPU

from faster_whisper import WhisperModel  # noqa: E402

logger = logging.getLogger("meetnote.transcription")

CPU_FALLBACK_COMPUTE_TYPE = "int8"


@dataclass
class TranscribedSegment:
    text: str
    start: float
    end: float


@dataclass
class ChunkTranscriptionResult:
    segments: list[TranscribedSegment]
    device_used: str
    ok: bool
    error: str | None = None


class WhisperTranscriber:
    def __init__(self, model_size: str, device: str, compute_type: str):
        self.requested_model_size = model_size
        self.requested_device = device
        self.requested_compute_type = compute_type

        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.gpu_fallback_reason: str | None = None

        self._model: WhisperModel | None = None

    def load(self) -> None:
        """Load the model, automatically falling back to CPU on any GPU
        initialization failure. Never raises for a GPU failure — only raises
        if CPU loading *also* fails, since at that point transcription is
        genuinely impossible."""
        if self.device == "cuda":
            try:
                self._model = WhisperModel(
                    self.model_size, device="cuda", compute_type=self.compute_type
                )
                logger.info(
                    "Whisper model '%s' loaded on GPU (compute_type=%s)",
                    self.model_size,
                    self.compute_type,
                )
                return
            except Exception as exc:
                self.gpu_fallback_reason = str(exc)
                logger.error(
                    "GPU model load failed (%s); switching to CPU mode", exc
                )
                self.device = "cpu"
                self.compute_type = CPU_FALLBACK_COMPUTE_TYPE

        self._model = WhisperModel(
            self.model_size, device=self.device, compute_type=self.compute_type
        )
        logger.info(
            "Whisper model '%s' loaded on CPU (compute_type=%s)",
            self.model_size,
            self.compute_type,
        )

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> None:
        """Unload the model and explicitly run garbage collection to free VRAM."""
        if self._model is not None:
            self._model = None
            import gc
            gc.collect()
            logger.info("Whisper model unloaded from %s", self.device)

    def transcribe_chunk(
        self, samples: np.ndarray, sample_rate: int, retries: int = 1
    ) -> ChunkTranscriptionResult:
        """Transcribe one audio chunk. On failure, retries once (per the
        product spec's chunk-failure handling); if it still fails the caller
        is expected to mark the chunk pending and keep recording rather than
        aborting the meeting."""
        if self._model is None:
            return ChunkTranscriptionResult([], self.device, False, "Model not loaded")

        last_error: str | None = None
        for attempt in range(retries + 1):
            try:
                segments_iter, _info = self._model.transcribe(
                    samples,
                    language=None,  # auto-detect
                    vad_filter=True,
                    beam_size=5,
                )
                segments = [
                    TranscribedSegment(text=s.text.strip(), start=s.start, end=s.end)
                    for s in segments_iter
                    if s.text and s.text.strip()
                ]
                return ChunkTranscriptionResult(segments, self.device, True)
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Transcription attempt %d/%d failed: %s", attempt + 1, retries + 1, exc
                )
                time.sleep(0.5)

        return ChunkTranscriptionResult([], self.device, False, last_error)

    def status(self) -> dict:
        return {
            "model_size": self.model_size,
            "device": self.device,
            "compute_type": self.compute_type,
            "loaded": self.is_loaded,
            "gpu_fallback_reason": self.gpu_fallback_reason,
        }
