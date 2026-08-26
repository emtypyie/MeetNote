"""Lightweight, non-invasive device probe for the health panel — checks
that a default microphone and a default output device (for system-audio
loopback) exist, without opening a recording stream the way a real
AudioCapture would. Cheap enough to call on every /health request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceProbeResult:
    microphone_ok: bool
    microphone_name: Optional[str]
    system_audio_ok: bool
    system_audio_name: Optional[str]
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "microphone_ok": self.microphone_ok,
            "microphone_name": self.microphone_name,
            "system_audio_ok": self.system_audio_ok,
            "system_audio_name": self.system_audio_name,
            "error": self.error,
        }


def probe_devices() -> DeviceProbeResult:
    try:
        import soundcard as sc
    except Exception as exc:
        return DeviceProbeResult(False, None, False, None, error=f"soundcard unavailable: {exc}")

    mic_ok, mic_name = False, None
    sys_ok, sys_name = False, None
    error = None

    try:
        mic = sc.default_microphone()
        mic_ok, mic_name = True, mic.name
    except Exception as exc:
        error = f"microphone: {exc}"

    try:
        speaker = sc.default_speaker()
        sc.get_microphone(id=str(speaker.id), include_loopback=True)
        sys_ok, sys_name = True, speaker.name
    except Exception as exc:
        error = f"{error}; system audio: {exc}" if error else f"system audio: {exc}"

    return DeviceProbeResult(mic_ok, mic_name, sys_ok, sys_name, error)
