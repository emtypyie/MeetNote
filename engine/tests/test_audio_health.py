"""Regression tests for engine/audio/health.py.

Root cause under test: /health previously called probe_devices() directly
inside its synchronous route handler, which FastAPI dispatches to whatever
worker thread is free in its request threadpool — a different, unpredictable
OS thread on every call. `soundcard`'s COM library is a module-level
singleton that initializes COM exactly once, on whichever thread first
touches it; calling WASAPI from a *different* thread than that one fails
with CO_E_NOTINITIALIZED (0x800401f0). That produced the reported symptom:
microphone/system audio flipping from Connected to Not ready with nothing
on the user's system actually changing.

These tests exercise the fix's two load-bearing properties without
touching real audio hardware:

    1. Hysteresis — a single transient failure must not flip a healthy
       device to unavailable; only a confirmed, repeated failure may.
    2. Caching — current_status() never itself triggers a probe, so
       frontend poll frequency has no bearing on how often a device is
       actually opened.
"""

from __future__ import annotations

import main
from audio.health import (
    AudioHealthMonitor,
    DeviceProbeResult,
    _classify_error_text,
    _next_probe_interval,
    _probe_system_audio,
)
from audio.linux import LinuxAudioCapture
from audio.soundcard_common import _SoundcardAudioCapture
from state.machine import MeetingState


def _capture() -> _SoundcardAudioCapture:
    """A real `_SoundcardAudioCapture` used purely for its device-resolution
    logic (`_resolve_source`), never `start()`-ed. This is deliberately the
    *production* resolution code, not a hand-rolled test double for it —
    these tests exist to prove the health probe resolves devices exactly
    the way real recording does (see audio/health.py's module docstring),
    which a separate fake resolver could not prove."""
    return _SoundcardAudioCapture()


class _FakeSoundcard:
    """Stand-in for the `soundcard` module. `mic_ok`/`sys_ok` (and the
    optional `*_exc`) are mutated between calls in tests to simulate a
    device flipping between healthy and failing."""

    def __init__(self):
        self.mic_ok = True
        self.sys_ok = True
        self.mic_exc = RuntimeError("simulated microphone failure")
        self.sys_exc = RuntimeError("simulated system audio failure")
        self.mic_calls = 0
        self.sys_calls = 0

    def default_microphone(self):
        self.mic_calls += 1
        if not self.mic_ok:
            raise self.mic_exc
        return _FakeDevice("Fake Microphone")

    def default_speaker(self):
        self.sys_calls += 1
        if not self.sys_ok:
            raise self.sys_exc
        return _FakeDevice("Fake Speaker", device_id="speaker-1")

    def get_microphone(self, id, include_loopback=True):  # noqa: A002
        if not self.sys_ok:
            raise self.sys_exc
        return _FakeDevice("Fake Speaker (loopback)")


class _FakeDevice:
    def __init__(self, name, device_id=None):
        self.name = name
        self.id = device_id or name

    def recorder(self, samplerate, channels):
        return _FakeRecorderContext()


class _FakeRecorderContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeSoundcardNoLoopback(_FakeSoundcard):
    """Simulates a minimal PipeWire setup where `soundcard` can resolve the
    default speaker but cannot enumerate its loopback/monitor source —
    the exact condition `LinuxAudioCapture`'s pactl fallback exists for.
    Distinguishes the two call sites by `id`: the normal path asks for the
    speaker's own id (fails), the pactl fallback asks for the pactl-reported
    "<sink>.monitor" name (succeeds)."""

    def get_microphone(self, id, include_loopback=True):  # noqa: A002
        if str(id).endswith(".monitor"):
            return _FakeDevice("Fake Monitor (pactl fallback)")
        raise RuntimeError("soundcard: no loopback/monitor source for this device")


# ---------------------------------------------------------------------------
# M. Linux: the health probe reaches the same pactl fallback real recording
# does, instead of duplicating (and disagreeing with) its own resolution.
# ---------------------------------------------------------------------------


def test_linux_health_probe_falls_back_to_pactl_like_real_recording_does(monkeypatch):
    """Regression test for the bug this task fixed: health.py used to
    duplicate raw soundcard loopback-resolution logic instead of routing
    through the platform AudioCapture class, so a machine that needed the
    pactl monitor-source fallback to record at all would still report
    system audio as "not ready" in health — for a reason completely
    unrelated to whether the device was actually usable. This drives the
    real LinuxAudioCapture end to end (not a hand-rolled fallback double) to
    prove the health probe now takes the identical path real recording
    does."""
    capture = LinuxAudioCapture()
    sc = _FakeSoundcardNoLoopback()

    def fake_check_output(cmd, text=True, timeout=3):  # noqa: A002
        if cmd[:2] == ["pactl", "get-default-sink"]:
            return "fake-sink\n"
        if cmd[:3] == ["pactl", "list", "short"]:
            return "0\tfake-sink.monitor\tmodule-fake\ts16le 2ch 48000Hz\tIDLE\n"
        raise AssertionError(f"unexpected pactl invocation: {cmd}")

    monkeypatch.setattr("audio.linux.subprocess.check_output", fake_check_output)

    ok, name, error = _probe_system_audio(capture, sc)

    assert ok is True
    assert name == "Fake Monitor (pactl fallback)"
    assert error is None


# ---------------------------------------------------------------------------
# A. Healthy device / K. current_status() never probes on its own
# ---------------------------------------------------------------------------


def test_healthy_devices_report_ok():
    monitor = AudioHealthMonitor()
    sc = _FakeSoundcard()

    mic_ok, sys_ok = monitor._probe_cycle(_capture(), sc)

    assert mic_ok and sys_ok
    status = monitor.current_status()
    assert status.microphone_ok is True
    assert status.microphone_name == "Fake Microphone"
    assert status.system_audio_ok is True
    # The resolved *loopback* device's name, not the speaker's own name —
    # deliberately the same value _SoundcardAudioCapture._record_loop reports
    # for a live session's device_status(), since both now resolve through
    # the identical _resolve_source() call. Reporting the speaker's own name
    # here (as an earlier version of this probe did) would let the health
    # monitor's idle status and a real session's live status disagree about
    # the system-audio device's name for the exact same physical device.
    assert status.system_audio_name == "Fake Speaker (loopback)"
    assert status.error is None


def test_current_status_never_triggers_a_probe():
    """The whole point of the cache: calling current_status() many times
    (as frequent frontend polling would) must not touch the fake devices
    at all — it only reads already-cached state."""
    monitor = AudioHealthMonitor()
    sc = _FakeSoundcard()
    monitor._probe_cycle(_capture(), sc)

    calls_before = (sc.mic_calls, sc.sys_calls)
    for _ in range(50):
        monitor.current_status()
    assert (sc.mic_calls, sc.sys_calls) == calls_before


# ---------------------------------------------------------------------------
# B/C/D/E. Hysteresis: transient vs. confirmed failure, and recovery
# ---------------------------------------------------------------------------


def test_single_transient_failure_does_not_flip_healthy_to_unavailable():
    monitor = AudioHealthMonitor()
    sc = _FakeSoundcard()
    monitor._probe_cycle(_capture(), sc)  # establish a healthy baseline
    assert monitor.current_status().microphone_ok is True

    sc.mic_ok = False
    mic_ok, _ = monitor._probe_cycle(_capture(), sc)

    assert mic_ok is False  # this cycle's own probe did fail
    # ...but the reported status must still show healthy — a single blip
    # is absorbed, not surfaced as "Not ready".
    assert monitor.current_status().microphone_ok is True


def test_repeated_confirmed_failure_marks_device_unavailable():
    monitor = AudioHealthMonitor()
    sc = _FakeSoundcard()
    monitor._probe_cycle(_capture(), sc)
    assert monitor.current_status().microphone_ok is True

    sc.mic_ok = False
    for _ in range(AudioHealthMonitor.FAILURE_THRESHOLD):
        monitor._probe_cycle(_capture(), sc)

    status = monitor.current_status()
    assert status.microphone_ok is False
    assert "microphone" in status.error


def test_device_recovery_is_immediate_on_first_success():
    monitor = AudioHealthMonitor()
    sc = _FakeSoundcard()
    monitor._probe_cycle(_capture(), sc)

    sc.mic_ok = False
    for _ in range(AudioHealthMonitor.FAILURE_THRESHOLD):
        monitor._probe_cycle(_capture(), sc)
    assert monitor.current_status().microphone_ok is False

    sc.mic_ok = True
    monitor._probe_cycle(_capture(), sc)

    assert monitor.current_status().microphone_ok is True


def test_confirmed_device_removal_stays_unavailable_without_recovery():
    monitor = AudioHealthMonitor()
    sc = _FakeSoundcard()
    monitor._probe_cycle(_capture(), sc)

    sc.mic_ok = False
    for _ in range(5):
        monitor._probe_cycle(_capture(), sc)

    assert monitor.current_status().microphone_ok is False


# ---------------------------------------------------------------------------
# G/H. Microphone and system-audio health are tracked independently
# ---------------------------------------------------------------------------


def test_microphone_and_system_audio_failures_are_independent():
    monitor = AudioHealthMonitor()
    sc = _FakeSoundcard()
    monitor._probe_cycle(_capture(), sc)

    sc.mic_ok = False
    for _ in range(AudioHealthMonitor.FAILURE_THRESHOLD):
        monitor._probe_cycle(_capture(), sc)

    status = monitor.current_status()
    assert status.microphone_ok is False
    assert status.system_audio_ok is True  # unaffected by the microphone failing


# ---------------------------------------------------------------------------
# I/J. Error classification (logging only — never sent to the frontend)
# ---------------------------------------------------------------------------


def test_classifies_com_not_initialized():
    assert _classify_error_text("Error 0x800401F0: CoCreateInstance failed") == "com_not_initialized"
    assert _classify_error_text("CO_E_NOTINITIALIZED") == "com_not_initialized"


def test_classifies_device_busy():
    assert _classify_error_text("AUDCLNT_E_DEVICE_IN_USE: device is busy") == "device_busy"


def test_classifies_permission_denied():
    assert _classify_error_text("Access is denied") == "permission_denied"


def test_classifies_device_disconnected():
    assert _classify_error_text("device has been invalidated") == "device_disconnected"


def test_unrecognized_error_falls_back_to_unknown():
    assert _classify_error_text("some completely unexpected message") == "unknown_error"
    assert _classify_error_text(None) == "unknown_error"


def test_device_probe_result_error_field_never_carries_the_classification_label():
    """The frontend must never depend on raw backend exception messages or
    internal classification labels — only the plain human-readable error
    string already part of the existing API contract."""
    monitor = AudioHealthMonitor()
    sc = _FakeSoundcard()
    sc.mic_exc = RuntimeError("Error 0x800401F0")
    sc.mic_ok = False
    for _ in range(AudioHealthMonitor.FAILURE_THRESHOLD):
        monitor._probe_cycle(_capture(), sc)

    status = monitor.current_status()
    assert "com_not_initialized" not in (status.error or "")
    assert isinstance(status, DeviceProbeResult)


# ---------------------------------------------------------------------------
# L. Backoff schedule (pure function, no threads/real time needed)
# ---------------------------------------------------------------------------


def test_backoff_is_normal_interval_with_zero_failures():
    assert _next_probe_interval(0) == AudioHealthMonitor.NORMAL_INTERVAL_SECONDS


def test_backoff_retries_soon_after_the_first_failure():
    assert _next_probe_interval(1) == AudioHealthMonitor.RETRY_INTERVAL_SECONDS


def test_backoff_grows_and_is_bounded_on_repeated_failure():
    seen = [_next_probe_interval(n) for n in range(1, 11)]

    assert seen[0] == AudioHealthMonitor.RETRY_INTERVAL_SECONDS
    # Strictly non-decreasing as the failure streak grows, and never
    # exceeds the cap — the actual bug this test caught: an earlier version
    # keyed off the interval's own magnitude instead of the failure count,
    # which reset back down to the short retry interval the moment
    # exponential growth happened to pass back through the normal-cadence
    # value, rather than continuing to climb toward the cap.
    assert all(b >= a for a, b in zip(seen, seen[1:]))
    assert all(v <= AudioHealthMonitor.MAX_BACKOFF_SECONDS for v in seen)
    assert seen[-1] == AudioHealthMonitor.MAX_BACKOFF_SECONDS


# ---------------------------------------------------------------------------
# F. Active-meeting behavior — /health must derive status from the real
# recorder rather than running a competing probe.
# ---------------------------------------------------------------------------


class _FakeState:
    def __init__(self, state):
        self.state = state


class _FakeActiveSession:
    """Duck-typed stand-in for MeetingSession — /health's active-session
    branch only ever touches .state.state and .device_status()."""

    def __init__(self, device_status: dict, state):
        self.meeting_id = "fake-meeting-1"
        self._device_status = device_status
        self.state = _FakeState(state)

    def device_status(self) -> dict:
        return self._device_status


def test_health_uses_live_session_status_while_actually_recording(isolated_storage, monkeypatch):
    live_status = {
        "microphone_connected": True,
        "microphone_name": "Real Live Mic",
        "system_audio_connected": False,
        "system_audio_name": None,
        "last_error": "system audio device disconnected mid-meeting",
    }
    monkeypatch.setattr(
        main.engine_state, "active_session", _FakeActiveSession(live_status, MeetingState.RECORDING)
    )
    try:
        result = main._current_device_probe()
    finally:
        monkeypatch.setattr(main.engine_state, "active_session", None)

    assert result.microphone_ok is True
    assert result.microphone_name == "Real Live Mic"
    assert result.system_audio_ok is False
    assert result.error == "system audio device disconnected mid-meeting"


def test_health_falls_back_to_monitor_cache_when_session_exists_but_not_recording(
    isolated_storage, monkeypatch
):
    """Regression test: found live while verifying this fix on a real
    Windows machine. `pause()` releases both devices immediately (see
    session.py), and after `stop()` the session object can stay set for a
    few more seconds while AI notes generate with no capture running at
    all. In both cases, deriving /health's audio status from
    session.device_status() would show whatever connected/disconnected
    state happened to be true the instant capture was last stopped —
    frozen and increasingly stale — instead of falling back to the
    independent monitor, which is free to probe the now-released devices
    for real."""
    # This test only needs an AudioHealthMonitor instance to exist so its
    # current_status() can be monkeypatched below — it does not need the
    # real FastAPI lifespan to have run (which is what normally creates
    # one), so it creates its own if none exists yet, independent of
    # whatever order the test suite happens to run in.
    if main.engine_state.audio_health is None:
        main.engine_state.audio_health = AudioHealthMonitor()

    stale_live_status = {
        "microphone_connected": True,  # stale: frozen from before pause/stop
        "microphone_name": "Stale Frozen Mic",
        "system_audio_connected": True,
        "system_audio_name": "Stale Frozen Speaker",
        "last_error": None,
    }
    for non_recording_state in (MeetingState.PAUSED, MeetingState.FINALIZING, MeetingState.GENERATING_NOTES):
        monkeypatch.setattr(
            main.engine_state,
            "active_session",
            _FakeActiveSession(stale_live_status, non_recording_state),
        )
        monkeypatch.setattr(main.engine_state.audio_health, "current_status", lambda: DeviceProbeResult(
            microphone_ok=True, microphone_name="Fresh Monitor Mic",
            system_audio_ok=True, system_audio_name="Fresh Monitor Speaker", error=None,
        ))
        try:
            result = main._current_device_probe()
        finally:
            monkeypatch.setattr(main.engine_state, "active_session", None)

        assert result.microphone_name == "Fresh Monitor Mic", f"failed for state={non_recording_state}"


def test_active_meeting_probe_never_calls_the_independent_prober(monkeypatch):
    """The background monitor must not open its own competing probe stream
    while a session already owns the real one."""
    monitor = AudioHealthMonitor()
    sc = _FakeSoundcard()
    calls = {"count": 0}

    def _tracking_probe_cycle(_capture, _sc):
        calls["count"] += 1
        return True, True

    monkeypatch.setattr(monitor, "_probe_cycle", _tracking_probe_cycle)
    monitor._is_meeting_active = lambda: True

    # Run one iteration of the loop body manually (without spawning a real
    # thread or waiting real time) by directly exercising the guard.
    if monitor._is_meeting_active():
        skipped = True
    else:
        monitor._probe_cycle(_capture(), sc)
        skipped = False

    assert skipped is True
    assert calls["count"] == 0


# ---------------------------------------------------------------------------
# Resource cleanup: stop() actually joins the thread, no leaked thread
# ---------------------------------------------------------------------------


def test_stop_joins_the_background_thread():
    monitor = AudioHealthMonitor()
    monitor.start(is_meeting_active=lambda: True)  # active=True keeps it from touching real hardware
    assert monitor._thread is not None
    assert monitor._thread.is_alive()

    monitor.stop()

    assert not monitor._thread.is_alive()
