"""Regression tests for engine/hardware/detector.py's cross-platform CPU
name resolution.

Root cause under test: `platform.processor()` reliably returns an empty
string on most Linux distributions (it shells out to `uname -p`, which many
distros never populate), while it works fine on Windows. Before this fix,
every Ubuntu user would see "Unknown CPU" in the System Health panel even
though the machine and its CPU are perfectly healthy — a real cross-platform
accuracy gap, not a hardware problem."""

from __future__ import annotations

from unittest.mock import mock_open

from hardware.detector import _cpu_model_name

_FAKE_PROC_CPUINFO = (
    "processor\t: 0\n"
    "vendor_id\t: GenuineIntel\n"
    "model name\t: Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz\n"
    "cpu MHz\t\t: 2600.000\n"
)


def test_falls_back_to_proc_cpuinfo_when_platform_processor_is_empty_on_linux(monkeypatch):
    monkeypatch.setattr("platform.processor", lambda: "")
    monkeypatch.setattr("hardware.detector.sys.platform", "linux")
    monkeypatch.setattr("builtins.open", mock_open(read_data=_FAKE_PROC_CPUINFO))

    assert _cpu_model_name() == "Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz"


def test_uses_platform_processor_directly_when_available(monkeypatch):
    """Windows (and some Linux distros) already populate this — no need to
    touch /proc/cpuinfo at all when it's already correct."""
    monkeypatch.setattr("platform.processor", lambda: "Intel64 Family 6 Model 158")

    assert _cpu_model_name() == "Intel64 Family 6 Model 158"


def test_returns_unknown_cpu_when_nothing_is_available(monkeypatch):
    monkeypatch.setattr("platform.processor", lambda: "")
    monkeypatch.setattr("hardware.detector.sys.platform", "linux")

    def _raise_open(*args, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr("builtins.open", _raise_open)

    assert _cpu_model_name() == "Unknown CPU"


def test_does_not_read_proc_cpuinfo_on_windows(monkeypatch):
    """The /proc/cpuinfo fallback is Linux-only — on Windows, an empty
    platform.processor() should just report "Unknown CPU" rather than
    attempting to open a path that doesn't exist there."""
    monkeypatch.setattr("platform.processor", lambda: "")
    monkeypatch.setattr("hardware.detector.sys.platform", "win32")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("must not attempt to open /proc/cpuinfo on Windows")

    monkeypatch.setattr("builtins.open", _fail_if_called)

    assert _cpu_model_name() == "Unknown CPU"
