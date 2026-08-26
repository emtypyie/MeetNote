"""Automatic OS detection.

The rest of the engine must never branch on `platform.system()` directly —
everything that needs to differ per-OS (audio capture above all) is hidden
behind a factory that consults this module once. See audio/factory.py.
"""

from __future__ import annotations

import platform
import sys
from enum import Enum


class OperatingSystem(str, Enum):
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"


def detect_os() -> OperatingSystem:
    system = platform.system().lower()
    if system == "windows":
        return OperatingSystem.WINDOWS
    if system == "linux":
        return OperatingSystem.LINUX
    if system == "darwin":
        return OperatingSystem.MACOS
    return OperatingSystem.UNKNOWN


def os_display_name() -> str:
    """Human-readable OS string for the system health panel, e.g. 'Windows 11'."""
    os_kind = detect_os()
    if os_kind is OperatingSystem.WINDOWS:
        # platform.release() reports "10" for Windows 11 too (a long-standing
        # Python quirk — Windows 11 kept major version 10 internally), so the
        # build number is what actually distinguishes them.
        try:
            build = sys.getwindowsversion().build
        except AttributeError:  # pragma: no cover - only unavailable off-Windows
            build = 0
        release = "11" if build >= 22000 else platform.release()
        return f"Windows {release} (build {build})" if build else f"Windows {release}"
    if os_kind is OperatingSystem.LINUX:
        try:
            import distro  # optional, not a hard dependency

            return f"{distro.name()} {distro.version()}".strip()
        except Exception:
            return f"Linux {platform.release()}"
    if os_kind is OperatingSystem.MACOS:
        return f"macOS {platform.mac_ver()[0]}"
    return platform.system() or "Unknown OS"
