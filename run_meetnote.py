#!/usr/bin/env python3
"""MeetNote — single entry point.

    python run_meetnote.py

Starts the whole desktop application: the Python engine (FastAPI/WebSocket,
audio capture, faster-whisper, AI notes — see engine/main.py) and the Tauri
desktop UI, in the right order, waits for the engine to actually be ready
before opening the UI, and shuts everything down cleanly when the UI closes.

This file is an ORCHESTRATOR, not the application. It does not detect
hardware, load Whisper, capture audio, or call any AI provider — the engine
already owns all of that (see docs/ARCHITECTURE.md). It only starts
processes, waits on a health check, and manages their lifecycle.

Uses the Python standard library only — no third-party dependency is
required to run the launcher itself, so there is nothing to install before
`python run_meetnote.py` can at least tell you what's missing.

Usage:
    python run_meetnote.py                 # auto: built app if present, else dev mode
    python run_meetnote.py --dev            # force Tauri dev mode (hot reload)
    python run_meetnote.py --prod           # force the built executable (error if absent)
    python run_meetnote.py --diagnostics    # environment/health report only, no UI
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# ANSI colour support — enabled on Windows 10+ via VTP, gracefully disabled
# when not writing to a real terminal (pipe, file redirect, etc.).
# ---------------------------------------------------------------------------

def _enable_windows_ansi() -> bool:
    if platform.system() != "Windows":
        return True
    try:
        import ctypes
        ENABLE_VTP = 0x0004
        handle = ctypes.windll.kernel32.GetStdHandle(-11)  # type: ignore[attr-defined]
        mode = ctypes.c_ulong()
        if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):  # type: ignore[attr-defined]
            ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | ENABLE_VTP)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


_ANSI_OK = _enable_windows_ansi()


class _C:
    """ANSI colour constants. Empty strings when colour is unavailable."""
    if _ANSI_OK and sys.stdout.isatty():
        RESET  = "\033[0m"
        BOLD   = "\033[1m"
        DIM    = "\033[2m"
        WHITE  = "\033[97m"
        CYAN   = "\033[96m"
        GREEN  = "\033[92m"
        YELLOW = "\033[93m"
        RED    = "\033[91m"
        BLUE   = "\033[94m"
        GRAY   = "\033[90m"
        PURPLE = "\033[95m"
    else:
        RESET = BOLD = DIM = WHITE = CYAN = GREEN = YELLOW = RED = BLUE = GRAY = PURPLE = ""


_W = 62
_BORDER  = _C.CYAN  + _C.BOLD + "=" * _W + _C.RESET
_DIVIDER = _C.GRAY  + "-" * _W + _C.RESET


def _banner(title: str) -> None:
    print()
    print(_BORDER)
    print(_C.CYAN + _C.BOLD + title.center(_W) + _C.RESET)
    print(_BORDER)


def _section(title: str) -> None:
    print()
    print(_C.BOLD + _C.WHITE + title + _C.RESET)
    print(_DIVIDER)


def _tag_ok()   -> str: return _C.GREEN  + _C.BOLD + "[OK]" + _C.RESET
def _tag_warn() -> str: return _C.YELLOW + _C.BOLD + "[WAIT]" + _C.RESET
def _tag_err()  -> str: return _C.RED    + _C.BOLD + "[ERROR]" + _C.RESET
def _tag_skip() -> str: return _C.GRAY   +           "[--]" + _C.RESET
def _tag_info() -> str: return _C.CYAN   + _C.BOLD + "[INFO]" + _C.RESET

def _kv(key: str, value: str, indent: int = 2) -> None:
    print(f"{' ' * indent}{key:<24} {value}")

def _ok(msg: str)   -> str: return _tag_ok() + "   " + msg
def _warn(msg: str) -> str: return _tag_warn() + " " + msg
def _err(msg: str)  -> str: return _tag_err() + " " + msg
def _skip(msg: str) -> str: return _tag_skip() + "   " + msg
def _info(msg: str) -> str: return _C.GRAY   + msg + _C.RESET

# ---------------------------------------------------------------------------
# Path resolution — everything is derived from this file's own location, not
# the caller's current working directory, so
#   cd C:\Users\SomeUser && python D:\Projects\MeetNote\run_meetnote.py
# resolves exactly the same paths as running it from inside the project.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
ENGINE_DIR = PROJECT_ROOT / "engine"
DESKTOP_DIR = PROJECT_ROOT / "desktop"
LOG_DIR = PROJECT_ROOT / "logs"

# The engine has always resolved its own .env relative to *its own* location
# (engine/main.py: `Path(__file__).parent / ".env"`), independent of this
# launcher or the caller's cwd. That file already exists and works — the
# launcher only checks for it here; it does not load, move, or parse it, and
# never touches the credentials inside it.
ENV_FILE = ENGINE_DIR / ".env"

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
IS_MACOS = platform.system() == "Darwin"

ENGINE_PYTHON = ENGINE_DIR / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
ENGINE_MAIN = ENGINE_DIR / "main.py"

# Must match ENGINE_PORT in desktop/src-tauri/src/lib.rs — both are fixed
# rather than negotiated, matching the existing (already-shipped) design.
ENGINE_PORT = 28765
ENGINE_HEALTH_URL = f"http://127.0.0.1:{ENGINE_PORT}/health"

READY_POLL_INTERVAL_SECONDS = 1.0
READY_TIMEOUT_SECONDS = 60.0  # covers FastAPI/hardware-detection startup, NOT Whisper loading
WHISPER_GRACE_WINDOW_SECONDS = 10.0  # best-effort extra wait just to report "Whisper ready" promptly
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 10.0
MAX_ENGINE_RESTARTS = 3
LIFECYCLE_POLL_INTERVAL_SECONDS = 1.0
DESKTOP_LAUNCH_GRACE_PERIOD_MS = 100  # extra time for port socket to fully stabilize after health check passes
HEALTH_CHECK_VALIDATION_ATTEMPTS = 3  # verify health multiple times before considering engine "ready"


# ---------------------------------------------------------------------------
# Logging — launcher.log is this script's own log; the engine keeps writing
# its own detailed structured log independently (default
# ~/MeetNote/logs/engine.log — see engine/logging_setup.py). This launcher
# additionally captures the engine subprocess's raw stdout/stderr to
# logs/engine.log at the project root, purely as a process-level record (not
# a replacement for the engine's own structured log).
# ---------------------------------------------------------------------------

logger = logging.getLogger("meetnote.launcher")


def setup_logging(verbose: bool = False) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler = logging.FileHandler(LOG_DIR / "launcher.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    
    if verbose:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(
            _C.GRAY + "  [log] " + _C.RESET + "%(message)s"
        ))
        logger.addHandler(console_handler)


# ---------------------------------------------------------------------------
# Environment validation — lightweight only: file/directory existence and
# package-directory presence checks. Never imports faster_whisper, never
# touches CUDA, never calls an AI provider.
# ---------------------------------------------------------------------------


class MissingDependencyError(RuntimeError):
    """Raised for a validation failure that should be shown to the user as a
    short, readable message — never as a raw traceback."""


class EngineStartError(RuntimeError):
    """Raised when the engine process cannot even be attempted (e.g. its
    port is already occupied) — shown to the user as a short message."""


@dataclass
class ValidationReport:
    ok: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)  # (name, ok, detail)
    desktop_mode: str = "unknown"  # "built" | "dev" | "unavailable"
    built_executable: Optional[Path] = None

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))
        if not ok:
            self.ok = False


def _engine_site_packages() -> Optional[Path]:
    if not ENGINE_PYTHON.exists():
        return None
    if IS_WINDOWS:
        return ENGINE_DIR / ".venv" / "Lib" / "site-packages"
    # Linux/macOS venvs nest under a versioned pythonX.Y directory.
    lib_dir = ENGINE_DIR / ".venv" / "lib"
    if not lib_dir.exists():
        return None
    for child in lib_dir.iterdir():
        candidate = child / "site-packages"
        if candidate.exists():
            return candidate
    return None


def find_built_desktop_executable() -> Optional[Path]:
    """Prefer a release build, then a debug build, on either platform.
    Matches what `cargo tauri build` / `cargo build` actually produce for
    this crate (binary name "desktop", from src-tauri/Cargo.toml)."""
    target_dir = DESKTOP_DIR / "src-tauri" / "target"
    binary_name = "desktop.exe" if IS_WINDOWS else "desktop"
    for profile in ("release", "debug"):
        candidate = target_dir / profile / binary_name
        if candidate.exists():
            return candidate
    return None


def validate_environment(require_desktop: bool = True) -> ValidationReport:
    report = ValidationReport(ok=True)

    report.add("Project root", PROJECT_ROOT.exists(), str(PROJECT_ROOT))
    report.add("Engine entry point (engine/main.py)", ENGINE_MAIN.exists(), str(ENGINE_MAIN))
    report.add("Engine Python environment (engine/.venv)", ENGINE_PYTHON.exists(), str(ENGINE_PYTHON))

    site_packages = _engine_site_packages()
    if site_packages is None:
        report.add("Engine dependencies installed", False, "engine/.venv has no site-packages directory")
    else:
        required_packages = ["fastapi", "uvicorn", "faster_whisper", "soundcard", "dotenv"]
        missing = [p for p in required_packages if not (site_packages / p).exists()]
        report.add(
            "Engine dependencies installed",
            not missing,
            "all present" if not missing else f"missing: {', '.join(missing)}",
        )

    env_exists = ENV_FILE.exists()
    report.add(
        ".env file (engine/.env)",
        True,  # never fatal — the app works fully offline without AI keys
        str(ENV_FILE) if env_exists else "not found (AI notes will be unavailable until added; recording/"
        "transcription work fully offline regardless)",
    )

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        probe = LOG_DIR / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        report.add("Logs directory writable", True, str(LOG_DIR))
    except OSError as exc:
        report.add("Logs directory writable", False, str(exc))

    desktop_package_json = DESKTOP_DIR / "package.json"
    report.add("Desktop project (desktop/package.json)", desktop_package_json.exists(), str(desktop_package_json))

    built_exe = find_built_desktop_executable()
    if built_exe is not None:
        report.desktop_mode = "built"
        report.built_executable = built_exe
        report.add("Desktop application", True, f"built executable found: {built_exe}")
    else:
        npm_path = shutil.which("npm")
        node_modules = DESKTOP_DIR / "node_modules"
        dev_available = bool(npm_path) and node_modules.exists()
        report.desktop_mode = "dev" if dev_available else "unavailable"
        detail = (
            "no built executable; will use `npm run tauri dev`"
            if dev_available
            else "no built executable, and dev mode isn't ready ("
            + ("npm not found" if not npm_path else "desktop/node_modules missing - run `npm install`")
            + ")"
        )
        # Only a hard requirement when we actually intend to launch the desktop UI
        # (--diagnostics doesn't need it).
        report.add("Desktop application", dev_available if require_desktop else True, detail)

    return report


def print_validation_failure(report: ValidationReport) -> None:
    print()
    print(_BORDER)
    print(_C.RED + _C.BOLD + "MEETNOTE ERROR".center(_W) + _C.RESET)
    print(_BORDER)
    print()
    print("  " + _err("Missing Requirements"))
    print()
    for name, chk_ok, detail in report.checks:
        if not chk_ok:
            _kv(name, _tag_err(), indent=4)
            if detail:
                print("      " + _C.GRAY + detail + _C.RESET)
    print()
    print(_DIVIDER)
    print("  Run the setup script to install dependencies:")
    print("    " + _C.GREEN + "python setup.py" + _C.RESET)
    print(_DIVIDER)
    print()


# ---------------------------------------------------------------------------
# Engine process lifecycle
# ---------------------------------------------------------------------------


class EngineState(str, Enum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"


class EngineManager:
    """Owns the engine subprocess: start, health-poll, graceful stop, and
    unexpected-exit detection. This is the launcher's only Whisper/CUDA/AI
    concern — it never inspects *how* the engine decided GPU vs CPU or
    whether a provider is configured beyond what /health already reports.
    """

    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.state: EngineState = EngineState.STOPPED
        self._log_file: Optional[object] = None
        self._shutdown_requested = False

    def start(self) -> None:
        if _port_already_in_use():
            pid, process_name = _get_port_holder_info()
            
            error_msg = f"""
============================================================
                      MEETNOTE ERROR
============================================================

  [ERROR] Port {ENGINE_PORT} is already in use.

  Another application is using the MeetNote engine port.
  (PID: {pid if pid is not None else 'Unknown'}, Process: {process_name})

  Close the application using port {ENGINE_PORT} and try again.

  The process was not terminated automatically.

------------------------------------------------------------
"""
            raise EngineStartError(error_msg)

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / "engine.log"
        # Fresh handle per start() (including restarts) but append across
        # restarts within one launcher session, so a restart's cause is
        # visible right after the previous run's tail.
        self._log_file = open(log_path, "a", encoding="utf-8")
        self._log_file.write(f"\n----- engine starting at {time.strftime('%Y-%m-%d %H:%M:%S')} -----\n")
        self._log_file.flush()

        cmd = [str(ENGINE_PYTHON), str(ENGINE_MAIN), "--port", str(ENGINE_PORT)]
        popen_kwargs: dict = dict(
            cwd=str(ENGINE_DIR),
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        if IS_WINDOWS:
            # Required so we can later send CTRL_BREAK_EVENT for a graceful
            # shutdown instead of only having a hard TerminateProcess available.
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        self.process = subprocess.Popen(cmd, **popen_kwargs)
        self.state = EngineState.STARTING
        self._shutdown_requested = False
        logger.info("Engine process started (pid=%s), log: %s", self.process.pid, log_path)

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def exit_code(self) -> Optional[int]:
        return self.process.poll() if self.process else None

    def wait_until_ready(self, timeout: float = READY_TIMEOUT_SECONDS) -> bool:
        import sys
        deadline = time.monotonic() + timeout
        logger.info("Waiting for engine health endpoint (%s)...", ENGINE_HEALTH_URL)
        consecutive_valid_checks = 0
        
        while time.monotonic() < deadline:
            if not self.is_alive():
                sys.stdout.write(f"\r  {'Health endpoint':<24} {_tag_err()} Failed      \n")
                logger.error("Engine process exited before becoming ready (exit code %s)", self.exit_code())
                self.state = EngineState.FAILED
                return False
            
            sys.stdout.write(f"\r  {'Health endpoint':<24} {_tag_warn()} Starting... ")
            sys.stdout.flush()
            
            health = _try_fetch_health()
            if health is not None and _verify_port_ready():
                # Validate multiple consecutive times to ensure stability
                consecutive_valid_checks += 1
                logger.debug(f"Health check passed ({consecutive_valid_checks}/{HEALTH_CHECK_VALIDATION_ATTEMPTS})")
                
                if consecutive_valid_checks >= HEALTH_CHECK_VALIDATION_ATTEMPTS:
                    sys.stdout.write(f"\r  {'Health endpoint':<24} {_tag_ok()}   Ready       \n")
                    self.state = EngineState.READY
                    logger.info("Engine health endpoint verified ready after %d consecutive checks", 
                               HEALTH_CHECK_VALIDATION_ATTEMPTS)
                    
                    # Allow extra time for port socket to fully stabilize on all OS platforms
                    grace_period_s = DESKTOP_LAUNCH_GRACE_PERIOD_MS / 1000.0
                    logger.debug(f"Grace period: waiting {grace_period_s}s before desktop launch")
                    time.sleep(grace_period_s)
                    
                    self._log_hardware_summary(health)
                    self._wait_briefly_for_whisper()
                    return True
            else:
                # Reset counter if check fails
                consecutive_valid_checks = 0
            
            time.sleep(READY_POLL_INTERVAL_SECONDS)
        
        sys.stdout.write(f"\r  {'Health endpoint':<24} {_tag_err()} Timeout     \n")
        logger.error("Timed out after %.0fs waiting for engine to become ready", timeout)
        self.state = EngineState.FAILED
        return False

    def _log_hardware_summary(self, health: dict) -> None:
        hw = health.get("hardware") or {}
        mode = health.get("transcription_mode") or {}
        logger.info(
            "Hardware: %s | GPU: %s | CUDA usable: %s | Transcription mode: %s/%s",
            hw.get("os", "?"),
            hw.get("gpu_name") or "none detected",
            hw.get("cuda_usable"),
            mode.get("device", "?"),
            mode.get("model_size", "?"),
        )

    def _wait_briefly_for_whisper(self) -> None:
        import sys
        """Best-effort only: log when Whisper finishes loading if it happens
        quickly. Never blocks desktop startup on this — a slow CPU load is
        not a failure (see module docstring / product spec section 9)."""
        deadline = time.monotonic() + WHISPER_GRACE_WINDOW_SECONDS
        while time.monotonic() < deadline:
            sys.stdout.write(f"\r  {'Whisper':<24} {_tag_warn()} Loading...  ")
            sys.stdout.flush()
            health = _try_fetch_health()
            if health is None:
                sys.stdout.write(f"\r  {'Whisper':<24} {_tag_err()} Unreachable \n")
                return
            whisper = health.get("whisper") or {}
            if whisper.get("loaded"):
                status = whisper.get("status") or {}
                sys.stdout.write(f"\r  {'Whisper':<24} {_tag_ok()}   Ready       \n")
                logger.info(
                    "Whisper ready (device=%s, model=%s, compute=%s)",
                    status.get("device"),
                    status.get("model_size"),
                    status.get("compute_type"),
                )
                return
            if whisper.get("error"):
                sys.stdout.write(f"\r  {'Whisper':<24} {_tag_err()} Failed      \n")
                self.state = EngineState.DEGRADED
                logger.warning("Whisper failed to load on GPU or CPU: %s", whisper["error"])
                logger.warning("Engine is DEGRADED: transcription unavailable, other features still work.")
                return
            time.sleep(1.0)
        sys.stdout.write(f"\r  {'Whisper':<24} {_tag_warn()} Still loading\n")
        logger.info("Whisper is still loading in the background; continuing without waiting further.")

    def stop(self, reason: str = "launcher requested shutdown") -> None:
        if not self.is_alive():
            self.state = EngineState.STOPPED
            return
        self.state = EngineState.STOPPING
        self._shutdown_requested = True
        logger.info("Stopping engine (%s)...", reason)

        assert self.process is not None
        try:
            if IS_WINDOWS:
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.terminate()  # SIGTERM — uvicorn handles this gracefully
        except (OSError, ValueError) as exc:
            logger.warning("Graceful signal failed (%s); will force-terminate", exc)

        try:
            self.process.wait(timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)
            logger.info("Engine stopped gracefully (exit code %s). Reason: %s", self.process.returncode, reason)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Engine did not exit within %.0fs of a graceful stop request; force-terminating.",
                GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
            )
            self.process.kill()
            self.process.wait(timeout=10)
            logger.warning("Engine force-terminated (exit code %s).", self.process.returncode)

        self.state = EngineState.STOPPED
        if self._log_file:
            self._log_file.flush()


def _port_already_in_use() -> bool:
    """True if something is already listening on ENGINE_PORT.

    Without this check, if a previous MeetNote engine (or anything else)
    were still bound to the port, `wait_until_ready()` would happily report
    "ready" against *that* process instead of the one we just spawned — our
    own subprocess would have failed to bind and exited, but we'd never
    notice, and later think we'd gracefully shut down an engine we never
    actually controlled while the real one keeps running orphaned. Checked
    once, immediately before we spawn (a python-not-yet-started stale
    process can't reasonably become "not stale" between the check and the
    spawn attempt a few milliseconds later)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", ENGINE_PORT)) == 0


def _get_port_holder_info() -> tuple[Optional[int], str]:
    """Find the PID and process name listening on ENGINE_PORT without killing it."""
    pid: Optional[int] = None
    process_name = "Unknown"

    try:
        if IS_WINDOWS:
            # netstat -ano output: Proto  Local  Foreign  State  PID
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                parts = line.split()
                # Match lines like: TCP  127.0.0.1:8765  ...  LISTENING  <pid>
                if len(parts) >= 5 and f":{ENGINE_PORT}" in parts[1] and parts[3] == "LISTENING":
                    try:
                        pid = int(parts[4])
                    except ValueError:
                        pass
                    break
            
            if pid is not None:
                try:
                    out = subprocess.check_output(
                        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    )
                    # Output is like: "python.exe","1234","Console","1","25,124 K"
                    if out.strip() and not out.strip().startswith("INFO:"):
                        process_name = out.split(",")[0].strip('"')
                except Exception:
                    pass

        else:
            # lsof is available on macOS and most Linux distros.
            out = subprocess.check_output(
                ["lsof", "-t", "-i", f"TCP:{ENGINE_PORT}", "-s", "TCP:LISTEN"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            first_line = out.strip().splitlines()[0] if out.strip() else ""
            pid = int(first_line) if first_line.isdigit() else None
            
            if pid is not None:
                try:
                    out = subprocess.check_output(
                        ["ps", "-p", str(pid), "-o", "comm="],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    )
                    if out.strip():
                        process_name = out.strip()
                except Exception:
                    pass

    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not determine PID for port %s: %s", ENGINE_PORT, exc)

    return pid, process_name


def _try_fetch_health() -> Optional[dict]:
    """Fetch and validate the engine health endpoint.
    
    Returns the health dict if the response is valid and contains expected fields.
    Returns None if the request fails, times out, or the response is invalid.
    """
    try:
        with urllib.request.urlopen(ENGINE_HEALTH_URL, timeout=2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                # Validate that response has expected structure (at minimum, hardware and status fields)
                # This guards against a partial/malformed response being accepted as "ready"
                if isinstance(data, dict) and "hardware" in data and data.get("service") == "meetnote-engine":
                    return data
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def _verify_port_ready() -> bool:
    """Verify the engine port is actually accepting connections from external perspective.
    
    Even if a process is listening, the socket may not be fully established.
    This check ensures the port is truly ready for client connections.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            result = s.connect_ex(("127.0.0.1", ENGINE_PORT))
            # 0 = connected successfully, port is ready
            # non-0 = connection refused or timeout
            return result == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Desktop process lifecycle
# ---------------------------------------------------------------------------


def start_desktop(mode: str, built_exe: Optional[Path]) -> subprocess.Popen:
    env = os.environ.copy()
    # Tells the Rust shell not to spawn (or try to kill) its own engine
    # process — this launcher already owns that. See desktop/src-tauri/src/lib.rs.
    env["MEETNOTE_LAUNCHER_MANAGED"] = "1"

    if mode == "built":
        assert built_exe is not None
        logger.info("Starting built desktop application: %s", built_exe)
        return subprocess.Popen([str(built_exe)], cwd=str(built_exe.parent), env=env)

    npm = shutil.which("npm")
    if not npm:
        raise MissingDependencyError("npm was not found on PATH; cannot start the desktop app in dev mode.")
    logger.info("Starting desktop application in dev mode (`npm run tauri dev`)...")
    return subprocess.Popen([npm, "run", "tauri", "dev"], cwd=str(DESKTOP_DIR), env=env)


def stop_desktop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    logger.info("Stopping desktop process (pid=%s)...", process.pid)
    try:
        # The desktop app has no persistence of its own to flush (all of
        # that lives in the engine, shut down separately and gracefully) —
        # only reached here when the *launcher* is initiating shutdown
        # (Ctrl+C, an unexpected launcher error), not on a normal window
        # close, which is instead detected via poll() in the main loop.
        process.terminate()
        process.wait(timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def _status_word(configured: bool, status: str) -> str:
    if status == "configured":
        return "Configured"
    if status == "not_configured":
        return "Not configured"
    if status == "auth_failed":
        return "Configured (authentication failed)"
    if status == "model_not_found":
        return "Configured (model unavailable)"
    if status == "checking":
        return "Checking..."
    return "Unavailable" if configured else "Not configured"


def run_diagnostics() -> int:
    _banner("MEETNOTE DIAGNOSTICS")

    _section("SYSTEM")
    print()
    _kv("OS", f"{_C.CYAN}{platform.system()} {platform.release()}{_C.RESET}")
    _kv("Python", f"{_C.CYAN}{platform.python_version()}{_C.RESET}")
    _kv("Root", f"{_C.GRAY}{PROJECT_ROOT}{_C.RESET}")

    report = validate_environment(require_desktop=False)

    _section("ENVIRONMENT CHECKS")
    print()
    e_ok  = _tag_ok()
    e_bad = _tag_err()
    _kv("Engine main.py", e_ok if ENGINE_MAIN.exists() else e_bad)
    _kv("Desktop package.json", e_ok if (DESKTOP_DIR / 'package.json').exists() else e_bad)
    _kv("engine/.env", e_ok if ENV_FILE.exists() else _tag_skip())

    missing = [name for name, chk_ok, _ in report.checks if not chk_ok]
    if missing:
        print()
        for name, chk_ok, detail in report.checks:
            if not chk_ok:
                print("  " + _err(name))
                if detail:
                    print("  " + _C.GRAY + f"    {detail}" + _C.RESET)
        print()
        print("  Cannot start the engine until the above issues are resolved.")
        print()
        return 1

    engine = EngineManager()
    print()
    print("  " + _info("Starting engine briefly to gather live status..."))
    try:
        engine.start()
    except EngineStartError as exc:
        print("  " + _err(str(exc)))
        return 1
    ready = engine.wait_until_ready(timeout=READY_TIMEOUT_SECONDS)
    if not ready:
        print("  " + _err("Engine did not become ready."))
        print("  " + _info("Check logs/engine.log and logs/launcher.log."))
        engine.stop(reason="diagnostics run finished (engine failed to start)")
        return 1

    health = _try_fetch_health() or {}
    hw     = health.get("hardware") or {}
    mode   = health.get("transcription_mode") or {}
    whisper = health.get("whisper") or {}
    ai      = health.get("ai_providers") or {}
    primary = ai.get("primary") or {}
    fallback = ai.get("fallback") or {}

    _section("HARDWARE")
    print()
    if hw.get("os"):
        _kv("OS (engine)", f"{_C.CYAN}{hw['os']}{_C.RESET}")
    gpu_name = hw.get("gpu_name")
    if gpu_name:
        _kv("GPU", f"{_C.GREEN}{gpu_name}{_C.RESET}")
        if hw.get("cuda_usable"):
            _kv("CUDA", f"{_C.GREEN}Installed and usable{_C.RESET}")
        else:
            reason = hw.get("cuda_failure_reason") or "Missing dependencies"
            _kv("CUDA", f"{_C.YELLOW}Unavailable ({reason}){_C.RESET}")
            print(f"  {_info('Hint: run python setup.py --gpu to install GPU support.')}")
    else:
        _kv("GPU", f"{_C.GRAY}Not detected{_C.RESET}")

    if whisper.get("loaded"):
        _kv("Whisper", f"{_C.GREEN}Available ({mode.get('device', '?')}, {mode.get('model_size', '?')}){_C.RESET}")
    elif whisper.get("loading"):
        _kv("Whisper", f"{_C.YELLOW}Still loading{_C.RESET}")
    else:
        _kv("Whisper", f"{_C.RED}Unavailable ({whisper.get('error') or 'unknown reason'}){_C.RESET}")

    _section("AI PROVIDERS")
    print()
    
    gemini_data = ai.get("gemini") or {}
    groq_data = ai.get("groq") or {}
    
    gemini_status = _status_word(gemini_data.get("configured", False), gemini_data.get("status", "unknown"))
    groq_status = _status_word(groq_data.get("configured", False), groq_data.get("status", "unknown"))
    
    _kv("Gemini API", f"{_tag_ok() if gemini_data.get('configured') else _tag_skip()}   {gemini_status}")
    _kv("Groq API", f"{_tag_ok() if groq_data.get('configured') else _tag_skip()}   {groq_status}")
    
    primary_name = ai.get("primary")
    fallback_name = ai.get("fallback")
    
    if primary_name:
        route = primary_name.capitalize()
        if fallback_name:
            route += f" -> {fallback_name.capitalize()} fallback"
        _kv("Routing", route)
    else:
        _kv("Routing", f"{_C.GRAY}AI unavailable{_C.RESET}")
        
    print()

    engine.stop(reason="diagnostics run finished")
    return 0


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def choose_desktop_mode(args: argparse.Namespace, report: ValidationReport) -> str:
    if args.prod:
        if report.built_executable is None:
            raise MissingDependencyError(
                "--prod was requested but no built desktop executable was found. Build one first:\n"
                "  cd desktop && npm run tauri build"
            )
        return "built"
    if args.dev:
        return "dev"
    # Auto: prefer a built executable; fall back to dev mode. Never rebuild
    # automatically — that's a deliberate, explicit action, not a launcher default.
    return "built" if report.built_executable is not None else "dev"


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the MeetNote desktop application.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dev", action="store_true", help="Force Tauri dev mode (hot reload).")
    mode_group.add_argument(
        "--prod", action="store_true", help="Force the built executable; error if none exists."
    )
    parser.add_argument(
        "--diagnostics", action="store_true", help="Print environment/health report and exit (no UI)."
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show raw engine logs in the console."
    )
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    if args.diagnostics:
        return run_diagnostics()

    print()
    print(_BORDER)
    print(_C.CYAN + _C.BOLD + "MEETNOTE".center(_W) + _C.RESET)
    print(_C.CYAN + "Desktop Meeting Assistant".center(_W) + _C.RESET)
    print(_BORDER)

    logger.info("Detecting system...")
    logger.info("OS: %s %s | Project root: %s", platform.system(), platform.release(), PROJECT_ROOT)

    _section("SYSTEM CHECK")
    print()
    logger.info("Checking environment...")
    try:
        report = validate_environment(require_desktop=True)
    except Exception:
        logger.exception("Unexpected error during environment validation")
        print("  " + _err("Unexpected error during validation. See logs/launcher.log."))
        return 1

    if not report.ok:
        print_validation_failure(report)
        for name, chk_ok, detail in report.checks:
            logger.info("Check: %-40s %-6s %s", name, "OK" if chk_ok else "FAIL", detail)
        return 1
        
    for name, chk_ok, detail in report.checks:
        logger.info("Check: %-40s %-6s %s", name, "OK" if chk_ok else "FAIL", detail)
        # Keep names relatively short for presentation
        disp_name = name.split(' (')[0]
        _kv(disp_name, _tag_ok())
        if "root" in disp_name.lower() or "file" in disp_name.lower() or "directory" in disp_name.lower():
            if detail and str(detail) not in ("all present", "True"):
                # Indent paths so they don't wrap long lines
                print("      " + _C.GRAY + str(detail) + _C.RESET)

    try:
        desktop_mode = choose_desktop_mode(args, report)
    except MissingDependencyError as exc:
        print("  " + _err(str(exc)))
        logger.error("%s", exc)
        return 1

    logger.info("Desktop launch mode: %s", desktop_mode)
    print()

    engine = EngineManager()
    desktop_process: Optional[subprocess.Popen] = None
    restart_count = 0
    exit_code = 0

    def shutdown(reason: str) -> None:
        _section("SHUTDOWN")
        print()
        if desktop_process is not None and desktop_process.poll() is None:
            stop_desktop(desktop_process)
            _kv("Desktop application", _tag_ok() + "   Stopped")
        else:
            _kv("Desktop application", _tag_skip() + "   Already stopped")
            
        if engine.is_alive():
            engine.stop(reason=reason)
            _kv("Engine", _tag_ok() + "   Stopped")
        else:
            _kv("Engine", _tag_skip() + "   Already stopped")
            
        _kv("Launcher", _tag_ok() + "   Closed")
        print()
        print("  MeetNote shut down cleanly.")
        print()
        logger.info("Launcher shutting down.")

    def handle_signal(signum, _frame) -> None:
        logger.info("Received signal %s - shutting down.", signum)
        shutdown("launcher received interrupt signal")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    if not IS_WINDOWS:
        signal.signal(signal.SIGTERM, handle_signal)

    try:
        while True:
            _section("ENGINE STARTUP")
            print()
            logger.info("Starting engine...")
            engine.start()
            _kv("Engine", f"{_tag_ok()}   Running   {_C.GRAY}PID {engine.process.pid}{_C.RESET}")
            
            if not engine.wait_until_ready():
                print()
                print(_BORDER)
                print(_C.RED + _C.BOLD + "MEETNOTE ERROR".center(_W) + _C.RESET)
                print(_BORDER)
                print()
                print("  " + _err("Engine did not become ready in time."))
                print("  " + _info("Check logs/engine.log and logs/launcher.log for details."))
                print()
                engine.stop(reason="engine failed to become ready")
                return 1

            logger.info("Engine ready.")
            print()
            
            # Log detailed readiness confirmation
            logger.info("Engine readiness verified: health check succeeded, port is connectable")
            
            # Print Hardware Block
            health = _try_fetch_health() or {}
            hw = health.get("hardware") or {}
            mode = health.get("transcription_mode") or {}
            print("  Hardware")
            _kv("  OS", hw.get("os", "?"), indent=4)
            gpu_name = hw.get("gpu_name")
            if gpu_name:
                _kv("  GPU", gpu_name, indent=4)
                _kv("  CUDA", "Available" if hw.get("cuda_usable") else "Unavailable", indent=4)
            else:
                _kv("  GPU", "Not available", indent=4)
                _kv("  CUDA", "Not available", indent=4)
                
            trans_mode = f"{mode.get('device', '?').upper()} / {mode.get('model_size', '?')}"
            _kv("  Transcription", trans_mode, indent=4)
            print()

            _section("DESKTOP APPLICATION")
            print()
            _kv("Launch mode", desktop_mode.capitalize())
            
            logger.info("Starting MeetNote desktop application with MEETNOTE_LAUNCHER_MANAGED=1")
            desktop_process = start_desktop(desktop_mode, report.built_executable)
            logger.info(
                "Desktop process started successfully (pid=%s). Engine and desktop both running. MeetNote is ready.",
                desktop_process.pid,
            )
            _kv("Application", f"{_tag_ok()}   Running   {_C.GRAY}PID {desktop_process.pid}{_C.RESET}")
            print()
            print(_BORDER)
            print(_C.GREEN + _C.BOLD + "MEETNOTE RUNNING".center(_W) + _C.RESET)
            print(_BORDER)
            print()
            print("  MeetNote is ready.")
            print()
            print("  Close the desktop window to quit.")
            print()

            # Main lifecycle loop: watch both processes concurrently.
            restarts_exhausted = False
            desktop_requested_restart = False
            while True:
                time.sleep(LIFECYCLE_POLL_INTERVAL_SECONDS)

                desktop_rc = desktop_process.poll()
                if desktop_rc is not None:
                    if desktop_rc == 42:
                        logger.info("Desktop application requested restart (exit code 42).")
                        engine.stop(reason="restarting application")
                        desktop_requested_restart = True
                        break
                    else:
                        logger.info("Desktop application exited (exit code %s).", desktop_rc)
                        engine.stop(reason="MeetNote desktop application closed")
                        break

                if restarts_exhausted:
                    # Already gave up on restarting; keep the desktop app running
                    # (it shows the engine as unavailable via its own health
                    # checks) without re-logging the same conclusion every second.
                    continue

                if not engine.is_alive():
                    exit_code_seen = engine.exit_code()
                    logger.error(
                        "Engine exited unexpectedly (exit code %s) while the desktop app is still running.",
                        exit_code_seen,
                    )
                    if restart_count >= MAX_ENGINE_RESTARTS:
                        logger.error(
                            "MeetNote engine could not be restarted after %d attempts. "
                            "Your existing local meeting data has been preserved.",
                            MAX_ENGINE_RESTARTS,
                        )
                        restarts_exhausted = True
                        continue
                    restart_count += 1
                    logger.warning("Attempting engine restart %d/%d...", restart_count, MAX_ENGINE_RESTARTS)
                    try:
                        engine.start()
                        if not engine.wait_until_ready():
                            logger.error("Engine restart %d failed to become ready.", restart_count)
                    except EngineStartError as exc:
                        logger.error("Engine restart %d could not even be attempted: %s", restart_count, exc)
            
            if desktop_requested_restart:
                logger.info("Restarting application...")
                restart_count = 0
                continue
            else:
                break

    except KeyboardInterrupt:
        logger.info("Interrupted - shutting down.")
        shutdown("keyboard interrupt")
    except EngineStartError as exc:
        logger.error("%s", exc)
        print()
        print(_BORDER)
        print(_C.RED + _C.BOLD + "MEETNOTE ERROR".center(_W) + _C.RESET)
        print(_BORDER)
        print()
        print("  " + _err(str(exc)))
        print()
        exit_code = 1
        shutdown("engine could not be started")
    except Exception:
        logger.exception("Unexpected launcher error")
        print()
        print(_BORDER)
        print(_C.RED + _C.BOLD + "MEETNOTE ERROR".center(_W) + _C.RESET)
        print(_BORDER)
        print()
        print("  " + _err("Unexpected error. See logs/launcher.log for details."))
        print()
        exit_code = 1
        shutdown("unexpected launcher error")
    # Normal exit (desktop app closed) already stopped the engine inside the
    # lifecycle loop above, with the correct "closed normally" reason logged
    # — nothing further to do here.

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
