"""Backend audio-health monitoring.

Two things live here:

    DeviceProbeResult   the plain value object /health returns — unchanged
                        in shape from before this module was reworked.
    AudioHealthMonitor  the one authoritative device-health prober.

`AudioHealthMonitor` runs on its own dedicated background thread for the
whole lifetime of the engine process, so it is always the *same* OS thread
touching `soundcard`/WASAPI. That matters more than it looks: `soundcard`'s
COM library (`soundcard/mediafoundation.py`'s `_COMLibrary`) is a
module-level singleton that calls `CoInitializeEx`/`CoInitialize` exactly
once, on whichever thread first imports/uses `soundcard` — and COM objects
are apartment-threaded, so calling them from a *different* thread than the
one COM was initialized on fails with `CO_E_NOTINITIALIZED` (0x800401f0).

Previously, `/health`'s synchronous route handler called `probe_devices()`
directly, which FastAPI dispatches to whatever worker thread is free in its
request threadpool — a different, unpredictable OS thread on every single
call, since the frontend polls `/health` every couple of seconds. That is
the actual mechanism behind "microphone shows Connected, then a few seconds
later flips to Not ready with nothing on the user's system having changed":
it was never about the physical device — it was about which thread
happened to handle that particular request, and whether COM had ever been
initialized *on that thread*.

`/health` now always reads a cached `DeviceProbeResult`
(`AudioHealthMonitor.current_status()`) and never opens a device itself.
The monitor thread refreshes that cache on its own schedule, decoupled from
how often the frontend polls, and applies hysteresis (`_DeviceHealth`) so a
single transient failure never flips a healthy device to "unavailable".

This module has no OS-specific code of its own. The probe thread resolves
devices through `AudioCaptureFactory.create()` (see `_run`) — the exact same
`AudioCapture` implementation, Windows or Linux, that a real meeting would
use — so health probing can never disagree with real recording about how a
device is found. On Linux in particular, that means the health probe also
gets `LinuxAudioCapture`'s pactl monitor-source fallback for free; a
dedicated, duplicated probe implementation could not open a device the real
recorder can, and vice versa.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger("meetnote.audio.health")


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


def _classify_error_text(message: Optional[str]) -> str:
    """Best-effort bucket for LOGGING only — this label is never sent to
    the frontend (which never sees more than the existing plain `error`
    string, same as before), so an exception shape we didn't anticipate
    just falls back to "unknown_error" rather than breaking anything."""
    if not message:
        return "unknown_error"
    lower = message.lower()
    if "0x800401f0" in lower or "co_e_notinitialized" in lower or "not initialized" in lower:
        return "com_not_initialized"
    if "0x80070005" in lower or "access is denied" in lower or "permission" in lower:
        return "permission_denied"
    if "0x88890004" in lower or "invalidated" in lower or "disconnected" in lower:
        return "device_disconnected"
    if "0x88890019" in lower or "in use" in lower or "busy" in lower:
        return "device_busy"
    if "no default" in lower or "no such" in lower or "not found" in lower:
        return "device_unavailable"
    return "unknown_error"


def _probe_microphone(capture, sc) -> tuple[bool, Optional[str], Optional[str]]:
    """One raw probe of the default microphone. Returns (ok, name, error).
    Module-level (not a method) so tests can monkeypatch it directly
    without touching real hardware.

    `capture` is the same platform `AudioCapture` instance
    (`AudioCaptureFactory.create()`) that a real meeting would use, and
    resolution is delegated to its `_resolve_source()` — this probe must
    never duplicate platform-specific device-resolution logic. That
    duplication used to exist here directly (raw `sc.default_microphone()`
    / `sc.get_microphone(..., include_loopback=True)` calls), which meant
    Linux's health check had no access to `LinuxAudioCapture`'s pactl
    monitor-source fallback that real recording already benefits from —
    a machine where recording worked via the fallback could still show a
    false "system audio not ready" in health, for a completely different
    reason than a real device problem."""
    try:
        device = capture._resolve_source(sc, "microphone")
        name = device.name
        # Shared (non-exclusive) mode is the default for `.recorder()` and
        # deliberately not overridden: this probe must never demand
        # exclusive device access, which would itself be a form of the
        # contention this module exists to avoid.
        with device.recorder(samplerate=16000, channels=1):
            pass
        return True, name, None
    except Exception as exc:  # noqa: BLE001 - classified and logged, never raised further
        return False, None, str(exc)


def _probe_system_audio(capture, sc) -> tuple[bool, Optional[str], Optional[str]]:
    """One raw probe of the default output device's loopback/monitor
    source. Returns (ok, name, error). See `_probe_microphone` for why
    resolution goes through `capture` instead of being duplicated here."""
    try:
        device = capture._resolve_source(sc, "system_audio")
        name = device.name
        with device.recorder(samplerate=16000, channels=1):
            pass
        return True, name, None
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)


class _DeviceHealth:
    """Hysteresis state for one device (microphone or system audio).

    A single failed probe is recorded but does NOT flip `ok` on its own —
    only `failure_threshold` *consecutive* failures do. Any single success
    immediately clears the failure streak and restores `ok`, so recovery
    from a genuine transient is fast (no restart, no manual reload) while
    going *unhealthy* requires real, repeated confirmation. The very first
    probe ever is the one exception: with no prior healthy state to
    preserve, a failure there is reported immediately rather than
    optimistically assumed — this is a truthful "not yet confirmed
    working", never a "false green".
    """

    def __init__(self, failure_threshold: int):
        self._failure_threshold = failure_threshold
        self._probed_once = False
        self.ok = True
        self.name: Optional[str] = None
        self.consecutive_failures = 0
        self.last_error: Optional[str] = None
        self.last_error_kind: Optional[str] = None
        self.last_probe_at: Optional[float] = None
        self.last_success_at: Optional[float] = None
        self.last_failure_at: Optional[float] = None

    def record_success(self, name: Optional[str]) -> None:
        now = time.monotonic()
        self.ok = True
        self.name = name
        self.consecutive_failures = 0
        self.last_error = None
        self.last_error_kind = None
        self.last_probe_at = now
        self.last_success_at = now
        self._probed_once = True

    def record_failure(self, error: Optional[str], kind: str) -> None:
        now = time.monotonic()
        self.consecutive_failures += 1
        self.last_error = error
        self.last_error_kind = kind
        self.last_probe_at = now
        self.last_failure_at = now
        if not self._probed_once or self.consecutive_failures >= self._failure_threshold:
            self.ok = False
        self._probed_once = True

    def describe(self) -> str:
        if self.ok:
            return f"connected ({self.name})" if self.name else "connected"
        if self.consecutive_failures < self._failure_threshold:
            return f"transient failure {self.consecutive_failures}/{self._failure_threshold} ({self.last_error_kind}), retaining previous state"
        return f"unavailable after {self.consecutive_failures} consecutive failures ({self.last_error_kind})"


def _next_probe_interval(consecutive_failures: int) -> float:
    """Backoff schedule keyed off the actual failure streak (not the
    previous interval's raw value — inferring "did we just fail" from the
    interval's magnitude breaks the moment exponential growth happens to
    pass back through the normal-cadence value). Zero failures means the
    normal cadence; each additional consecutive failure retries sooner
    (resolving genuine transients fast) then backs off exponentially up to
    a cap, so a device that is genuinely gone isn't hammered with probes
    forever. Pure function so it can be tested without real threading or
    elapsed time."""
    if consecutive_failures <= 0:
        return AudioHealthMonitor.NORMAL_INTERVAL_SECONDS
    interval = AudioHealthMonitor.RETRY_INTERVAL_SECONDS * (2 ** (consecutive_failures - 1))
    return min(interval, AudioHealthMonitor.MAX_BACKOFF_SECONDS)


class AudioHealthMonitor:
    """Owns the one background thread allowed to touch `soundcard` for
    health-check purposes. Call `start()` once at engine startup and
    `stop()` at shutdown. `current_status()` is safe to call from any
    thread (including FastAPI's request threadpool) since it only reads a
    lock-protected cache — it never opens a device itself, so how often the
    frontend polls /health has no bearing on how often a device is
    actually touched.
    """

    NORMAL_INTERVAL_SECONDS = 8.0
    RETRY_INTERVAL_SECONDS = 2.0
    MAX_BACKOFF_SECONDS = 30.0
    FAILURE_THRESHOLD = 2  # consecutive failures required before reporting "unavailable"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mic = _DeviceHealth(self.FAILURE_THRESHOLD)
        self._sys = _DeviceHealth(self.FAILURE_THRESHOLD)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_meeting_active: Callable[[], bool] = lambda: False

    def start(self, is_meeting_active: Callable[[], bool]) -> None:
        self._is_meeting_active = is_meeting_active
        self._thread = threading.Thread(target=self._run, daemon=True, name="audio-health-probe")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def current_status(self) -> DeviceProbeResult:
        with self._lock:
            error = None
            if not self._mic.ok:
                error = f"microphone: {self._mic.last_error}"
            if not self._sys.ok:
                sys_msg = f"system audio: {self._sys.last_error}"
                error = f"{error}; {sys_msg}" if error else sys_msg
            return DeviceProbeResult(
                microphone_ok=self._mic.ok,
                microphone_name=self._mic.name,
                system_audio_ok=self._sys.ok,
                system_audio_name=self._sys.name,
                error=error,
            )

    def _probe_cycle(self, capture, sc) -> tuple[bool, bool]:
        """Runs exactly one probe of both devices and updates the cached
        health state. Returns (mic_ok, sys_ok). Split out from `_run`'s
        infinite loop so tests can drive individual cycles deterministically
        without real threads or elapsed time.

        `capture` is a platform `AudioCapture` instance (never started —
        only its device-resolution logic is used) so probing always
        resolves devices exactly the way a real meeting would on this OS,
        including Linux's pactl fallback. See `_probe_microphone`."""
        mic_ok, mic_name, mic_err = _probe_microphone(capture, sc)
        with self._lock:
            if mic_ok:
                self._mic.record_success(mic_name)
            else:
                self._mic.record_failure(mic_err, _classify_error_text(mic_err))

        sys_ok, sys_name, sys_err = _probe_system_audio(capture, sc)
        with self._lock:
            if sys_ok:
                self._sys.record_success(sys_name)
            else:
                self._sys.record_failure(sys_err, _classify_error_text(sys_err))

        logger.info(
            "Audio probe: microphone=%s system_audio=%s",
            self._mic.describe(),
            self._sys.describe(),
        )
        return mic_ok, sys_ok

    def _run(self) -> None:
        try:
            import soundcard as sc

            # The same AudioCaptureFactory a real meeting uses — Windows or
            # Linux — so probing always resolves devices identically to
            # actual recording (pactl fallback included on Linux). This
            # instance is never start()-ed; only its _resolve_source() is
            # used, and that takes `sc` as an explicit argument, so no
            # per-platform branching is needed here at all.
            from audio.factory import AudioCaptureFactory

            capture = AudioCaptureFactory.create()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Audio probe: soundcard library unavailable (%s); "
                "microphone/system audio will report unavailable",
                exc,
            )
            with self._lock:
                self._mic.record_failure(str(exc), "library_unavailable")
                self._sys.record_failure(str(exc), "library_unavailable")
            return

        while not self._stop_event.is_set():
            if self._is_meeting_active():
                # A live MeetingSession already owns the microphone/loopback
                # streams for the whole meeting. Opening a second,
                # independent probe stream against the same default device
                # here would be exactly the competing-recorder contention
                # this monitor exists to avoid — skip probing entirely.
                # /health derives status from the real capture state
                # instead while a session is active (see main.py).
                self._stop_event.wait(self.NORMAL_INTERVAL_SECONDS)
                continue

            self._probe_cycle(capture, sc)
            with self._lock:
                worst_streak = max(self._mic.consecutive_failures, self._sys.consecutive_failures)
            self._stop_event.wait(_next_probe_interval(worst_streak))
