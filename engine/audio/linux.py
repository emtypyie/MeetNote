"""Linux (Ubuntu) audio capture.

Primary path: `soundcard`'s PulseAudio backend, which also works against
PipeWire's `pipewire-pulse` compatibility server — the standard setup on
modern Ubuntu (22.04+) — so no PipeWire-native bindings are required. The
default output device's monitor source is resolved the same way as Windows
loopback: `soundcard.get_microphone(id=<default speaker id>,
include_loopback=True)`.

Fallback path: some minimal/headless PipeWire setups don't advertise a
monitor source until one is requested, or `soundcard` can fail to enumerate
it. In that case we shell out to `pactl` (present on both PulseAudio and
PipeWire-pulse systems) to look for a `<sink>.monitor` source explicitly.
This fallback is implemented for completeness but — like the rest of the
Linux path — has not been exercised on a real Ubuntu machine in this
session (no Linux host was available); see docs/LINUX_TESTING.md for the
manual verification steps this needs before being trusted in production.
"""

from __future__ import annotations

import logging
import subprocess

from audio.soundcard_common import _SoundcardAudioCapture

logger = logging.getLogger("meetnote.audio.linux")


class LinuxAudioCapture(_SoundcardAudioCapture):
    def _resolve_source(self, source_kind: str):
        try:
            return super()._resolve_source(source_kind)
        except Exception as exc:
            if source_kind != "system_audio":
                raise
            logger.warning(
                "soundcard could not resolve a system-audio loopback device (%s); "
                "attempting pactl monitor-source fallback",
                exc,
            )
            return self._resolve_via_pactl()

    def _resolve_via_pactl(self):
        """Ask pactl directly for the monitor source of the default sink.

        NOT covered by any test in this session (requires a real Linux
        audio server) — implemented defensively so a soundcard quirk on an
        unusual PipeWire config degrades to a clear error instead of a
        silent hang, per the product spec's requirement to implement
        detection + graceful fallback rather than assume a device exists.
        """
        try:
            default_sink = subprocess.check_output(
                ["pactl", "get-default-sink"], text=True, timeout=3
            ).strip()
            monitor_name = f"{default_sink}.monitor"
            sources = subprocess.check_output(
                ["pactl", "list", "short", "sources"], text=True, timeout=3
            )
            if monitor_name not in sources:
                raise RuntimeError(f"pactl reports no monitor source named {monitor_name!r}")
            # soundcard can open a source by its Pulse name directly.
            return self._sc.get_microphone(id=monitor_name)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "pactl not found — install pulseaudio-utils (or the PipeWire "
                "equivalent) to enable system-audio capture on this system"
            ) from exc
