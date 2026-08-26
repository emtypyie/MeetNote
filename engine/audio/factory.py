"""AudioCaptureFactory — the one place in the app allowed to know which OS
it's running on for audio purposes.

    audio_capture = AudioCaptureFactory.create()

Everything downstream only ever sees the `AudioCapture` interface.
"""

from __future__ import annotations

from audio.base import AudioCapture
from os_detect import OperatingSystem, detect_os


class UnsupportedPlatformError(RuntimeError):
    pass


class AudioCaptureFactory:
    @staticmethod
    def create() -> AudioCapture:
        os_kind = detect_os()
        if os_kind is OperatingSystem.WINDOWS:
            from audio.windows import WindowsAudioCapture

            return WindowsAudioCapture()
        if os_kind is OperatingSystem.LINUX:
            from audio.linux import LinuxAudioCapture

            return LinuxAudioCapture()
        raise UnsupportedPlatformError(
            f"MeetNote supports Windows and Ubuntu Linux; detected {os_kind.value}"
        )
