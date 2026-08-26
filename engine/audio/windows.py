"""Windows audio capture.

Uses `soundcard`'s WASAPI backend. System audio is captured via WASAPI
loopback on the default render (output) device — `soundcard.get_microphone(
id=<default speaker id>, include_loopback=True)` — which is the standard,
supported way to record "what you hear" on Windows without a virtual audio
cable. No custom COM/WASAPI bindings are needed.
"""

from __future__ import annotations

from audio.soundcard_common import _SoundcardAudioCapture


class WindowsAudioCapture(_SoundcardAudioCapture):
    """No Windows-specific overrides needed today — soundcard's WASAPI
    backend already resolves the default microphone and default output
    device's loopback stream correctly. This subclass exists so the
    architecture matches the product spec's OS-isolation requirement and
    gives us a seam for Windows-only quirks later (e.g. exclusive-mode
    device handling) without touching shared code."""
