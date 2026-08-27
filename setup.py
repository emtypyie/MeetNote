#!/usr/bin/env python3
"""MeetNote Hardware-Aware Installer/Setup Script.

This script provisions the Python virtual environment and installs the
correct dependencies based on the hardware detected. It specifically avoids
installing large CUDA/NVIDIA runtime libraries on CPU-only machines.

Usage:
    python setup.py                # automatic hardware detection
    python setup.py --cpu-only     # force CPU-only installation
    python setup.py --gpu          # force GPU installation
"""

import argparse
import getpass
import platform
import subprocess
import sys
import venv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENGINE_DIR = PROJECT_ROOT / "engine"
DESKTOP_DIR = PROJECT_ROOT / "desktop"
VENV_DIR = ENGINE_DIR / ".venv"

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


# ---------------------------------------------------------------------------
# Colour / ANSI support — safe on Windows 10+, disabled gracefully if the
# terminal does not support escape codes.
# ---------------------------------------------------------------------------

def _enable_windows_ansi() -> bool:
    """Enable Virtual Terminal Processing on Windows so ANSI escape codes work."""
    if not IS_WINDOWS:
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # Enable ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x0004) on stdout handle
        ENABLE_VTP = 0x0004
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VTP)
        return True
    except Exception:
        return False


_ANSI_OK = _enable_windows_ansi()


class C:
    """ANSI colour constants. Falls back to empty strings when unsupported."""
    if _ANSI_OK and sys.stdout.isatty():
        RESET  = "\033[0m"
        BOLD   = "\033[1m"
        DIM    = "\033[2m"

        # Foreground colours
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


# ---------------------------------------------------------------------------
# CLI layout helpers
# ---------------------------------------------------------------------------

WIDTH = 62
BORDER  = C.CYAN  + C.BOLD + "=" * WIDTH + C.RESET
DIVIDER = C.GRAY  + "-" * WIDTH + C.RESET


def print_header(title: str) -> None:
    print()
    print(BORDER)
    centred = title.center(WIDTH)
    print(C.CYAN + C.BOLD + centred + C.RESET)
    print(BORDER)


def print_section(title: str) -> None:
    print()
    print(C.BOLD + C.WHITE + title + C.RESET)
    print(DIVIDER)


def print_divider() -> None:
    print(DIVIDER)


def ok(msg: str) -> str:
    return C.GREEN + C.BOLD + "[OK]" + C.RESET + " " + msg


def warn(msg: str) -> str:
    return C.YELLOW + C.BOLD + "[!] " + C.RESET + " " + msg


def err(msg: str) -> str:
    return C.RED + C.BOLD + "[ERROR]" + C.RESET + " " + msg


def skip(msg: str) -> str:
    return C.GRAY + "[--]" + C.RESET + " " + msg


# ---------------------------------------------------------------------------
# API key masking — actual key values never appear in output
# ---------------------------------------------------------------------------

def mask_api_key(key: str) -> str:
    """Return a masked representation. The actual key is never returned."""
    if not key:
        return ""
    for prefix in ("gsk_", "AIza", "sk-"):
        if key.startswith(prefix):
            hidden_len = len(key) - len(prefix)
            return (C.DIM + prefix + C.RESET +
                    C.YELLOW + "*" * hidden_len + C.RESET)
    return C.YELLOW + "*" * len(key) + C.RESET


# ---------------------------------------------------------------------------
# Provider display helpers
# ---------------------------------------------------------------------------

def print_provider_row(label: str, configured: bool, masked: str = "") -> None:
    marker = ok("") if configured else skip("")
    status = (C.GREEN + "Configured" + C.RESET) if configured else (C.GRAY + "Not configured" + C.RESET)
    detail = "  " + masked if configured and masked else ""
    print(f"  {marker}{C.BOLD}{label:<10}{C.RESET} {status}{detail}")


def print_routing_summary(is_gemini: bool, is_groq: bool) -> None:
    print()
    print("  " + C.BOLD + C.WHITE + "AI ROUTING" + C.RESET)
    if is_gemini and is_groq:
        print("  " + C.CYAN + "Gemini" + C.RESET + C.GRAY + " -> " + C.RESET +
              C.BLUE + "Groq fallback" + C.RESET)
    elif is_gemini:
        print("  " + C.CYAN + "Gemini only" + C.RESET +
              C.GRAY + " - no fallback configured" + C.RESET)
    elif is_groq:
        print("  " + C.BLUE + "Groq only" + C.RESET +
              C.GRAY + " - no fallback configured" + C.RESET)
    else:
        print("  " + C.YELLOW + "No AI provider configured" + C.RESET)


def print_setup_complete(is_gemini: bool, is_groq: bool) -> None:
    print()
    print_divider()
    print()
    print("  " + C.BOLD + C.WHITE + "SETUP COMPLETE" + C.RESET)
    print()

    if is_gemini or is_groq:
        print("  " + ok("Environment configured successfully."))
        print()
        print("  " + C.BOLD + "AI provider:" + C.RESET)
        if is_gemini and is_groq:
            print("  " + C.CYAN + "Gemini" + C.RESET + " -> " + C.BLUE + "Groq fallback" + C.RESET)
        elif is_gemini:
            print("  " + C.CYAN + "Gemini" + C.RESET)
        else:
            print("  " + C.BLUE + "Groq" + C.RESET)
    else:
        print("  " + warn("No AI provider configured."))
        print()
        print("  Local recording and transcription will still work.")
        print("  AI meeting notes require at least one API key.")
        print()
        print("  You can configure a provider later in:")
        print("  " + C.YELLOW + "  engine/.env" + C.RESET)

    print()
    print("  " + C.BOLD + "Start MeetNote:" + C.RESET)
    print("  " + C.GREEN + "  python run_meetnote.py" + C.RESET)
    print()
    print_divider()
    print()


# ---------------------------------------------------------------------------
# Core logic (unchanged)
# ---------------------------------------------------------------------------

def has_nvidia_gpu() -> bool:
    """Lightweight OS-level check for NVIDIA GPU presence.
    Must not import any CUDA/CTranslate2 dependencies.
    """
    try:
        if IS_WINDOWS:
            cmd = ["powershell", "-Command",
                   "Get-CimInstance -ClassName Win32_VideoController | Select-Object -ExpandProperty Name"]
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            return "NVIDIA" in out.upper()
        elif IS_LINUX:
            out = subprocess.check_output(["lspci"], text=True, stderr=subprocess.DEVNULL)
            return "NVIDIA" in out.upper()
    except Exception:
        pass
    return False


def get_venv_pip() -> Path:
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def run_pip_install(req_file: Path) -> None:
    pip_exe = get_venv_pip()
    print(f"\n  Installing from {C.BOLD}{req_file.name}{C.RESET}...")
    cmd = [str(pip_exe), "install", "-r", str(req_file)]
    try:
        subprocess.check_call(cmd, cwd=str(ENGINE_DIR))
    except subprocess.CalledProcessError:
        print(f"\n  {err(f'Failed to install {req_file.name}')}")
        sys.exit(1)


def configure_ai_providers() -> None:
    env_file = ENGINE_DIR / ".env"

    existing_lines: list[str] = []
    groq_key = ""
    gemini_key = ""

    if env_file.exists():
        existing_lines = env_file.read_text(encoding="utf-8").splitlines()
        for line in existing_lines:
            ls = line.strip()
            if ls.startswith("GROQ_API_KEY="):
                groq_key = ls.split("=", 1)[1].strip(" '\"")
            elif ls.startswith("GEMINI_API_KEY="):
                gemini_key = ls.split("=", 1)[1].strip(" '\"")

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    print_header("  MEETNOTE SETUP  ")

    print_section("  AI PROVIDER CONFIGURATION")
    print()
    print("  Configure " + C.CYAN + "Gemini" + C.RESET + ", " +
          C.BLUE + "Groq" + C.RESET + ", or both.")
    print("  If both are configured, " + C.CYAN + "Gemini" + C.RESET +
          " is primary and")
    print("  " + C.BLUE + "Groq" + C.RESET + " is used automatically as a fallback.")
    print("  " + C.GRAY + "Press Enter to skip a provider." + C.RESET)

    # ------------------------------------------------------------------
    # API key prompts
    # ------------------------------------------------------------------
    print_section("  API KEYS")
    print()

    new_groq = groq_key
    if groq_key:
        print("  " + C.GRAY + f"Groq API key [already configured]: " + C.RESET +
              mask_api_key(groq_key))
    else:
        raw = getpass.getpass("  Groq API key [optional]: ").strip()
        new_groq = raw
        if raw:
            print("  " + C.GRAY + "Groq API key: " + C.RESET + mask_api_key(raw))

    new_gemini = gemini_key
    if gemini_key:
        print("  " + C.GRAY + f"Gemini API key [already configured]: " + C.RESET +
              mask_api_key(gemini_key))
    else:
        raw = getpass.getpass("  Gemini API key [optional]: ").strip()
        new_gemini = raw
        if raw:
            print("  " + C.GRAY + "Gemini API key: " + C.RESET + mask_api_key(raw))

    # ------------------------------------------------------------------
    # Write engine/.env (logic unchanged)
    # ------------------------------------------------------------------
    groq_updated = False
    gemini_updated = False
    new_lines: list[str] = []

    for line in existing_lines:
        ls = line.strip()
        if ls.startswith("GROQ_API_KEY="):
            new_lines.append(f"GROQ_API_KEY={new_groq}")
            groq_updated = True
        elif ls.startswith("GEMINI_API_KEY="):
            new_lines.append(f"GEMINI_API_KEY={new_gemini}")
            gemini_updated = True
        else:
            new_lines.append(line)

    if not groq_updated:
        new_lines.append(f"GROQ_API_KEY={new_groq}")
    if not gemini_updated:
        new_lines.append(f"GEMINI_API_KEY={new_gemini}")

    try:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        if not IS_WINDOWS:
            env_file.chmod(0o600)
    except Exception as e:
        print()
        print_divider()
        print("  " + err("Setup failed"))
        print()
        print("  Could not write " + C.YELLOW + "engine/.env" + C.RESET + ".")
        print()
        print("  Reason:")
        print("  " + C.RED + f"{type(e).__name__}" + C.RESET)
        print()
        print("  Please check file permissions and try again.")
        print_divider()
        return

    # ------------------------------------------------------------------
    # Configuration summary
    # ------------------------------------------------------------------
    is_groq_configured = bool(new_groq)
    is_gemini_configured = bool(new_gemini)

    print_section("  CONFIGURATION SUMMARY")
    print()
    print_provider_row("Groq",   is_groq_configured,   mask_api_key(new_groq)   if is_groq_configured   else "")
    print_provider_row("Gemini", is_gemini_configured, mask_api_key(new_gemini) if is_gemini_configured else "")
    print_routing_summary(is_gemini_configured, is_groq_configured)

    if not is_groq_configured and not is_gemini_configured:
        print()
        print("  " + C.YELLOW + "No AI provider has been configured." + C.RESET)
        print("  MeetNote can still record and transcribe locally,")
        print("  but AI-generated meeting notes will not be available.")
        print()
        print("  Add a key later in: " + C.YELLOW + "engine/.env" + C.RESET)
        print("  At least one provider is recommended for AI notes.")


def main():
    parser = argparse.ArgumentParser(description="MeetNote setup and dependency installation.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--cpu-only", action="store_true",
                            help="Force CPU-only installation (skip GPU dependencies).")
    mode_group.add_argument("--gpu", action="store_true",
                            help="Force GPU installation (install CUDA/NVIDIA dependencies).")
    args = parser.parse_args()

    print_header("  MEETNOTE ENVIRONMENT SETUP  ")

    # 1. Ensure venv exists
    print_section("  PYTHON ENVIRONMENT")
    print()
    if not VENV_DIR.exists():
        print("  Creating Python virtual environment in engine/.venv...")
        venv.create(VENV_DIR, with_pip=True)
    else:
        print("  " + ok("Virtual environment already exists."))

    pip_exe = get_venv_pip()
    if not pip_exe.exists():
        print("  " + err(f"pip not found at {pip_exe}. Virtual environment may be corrupted."))
        sys.exit(1)

    # 2. Hardware Detection
    print_section("  HARDWARE DETECTION")
    print()
    if args.cpu_only:
        gpu_detected = False
        print("  " + skip("Mode: CPU-only (forced by --cpu-only)"))
    elif args.gpu:
        gpu_detected = True
        print("  " + ok("Mode: GPU-capable (forced by --gpu)"))
    else:
        print("  " + C.GRAY + "Detecting NVIDIA GPU..." + C.RESET)
        gpu_detected = has_nvidia_gpu()
        if gpu_detected:
            print("  " + ok("NVIDIA GPU detected"))
            print("  " + ok("Mode: GPU-capable"))
        else:
            print("  " + skip("NVIDIA GPU not detected"))
            print("  " + skip("Mode: CPU-only"))

    # 3. Base requirements
    print_section("  PYTHON DEPENDENCIES")
    base_req = ENGINE_DIR / "requirements-base.txt"
    run_pip_install(base_req)

    # 4. Hardware-specific requirements
    if gpu_detected:
        gpu_req = ENGINE_DIR / "requirements-gpu.txt"
        print("\n  " + C.PURPLE + "Installing GPU dependencies..." + C.RESET)
        run_pip_install(gpu_req)
    else:
        cpu_req = ENGINE_DIR / "requirements-cpu.txt"
        print("\n  " + skip("GPU dependencies skipped (CPU-only mode)"))
        if (cpu_req.exists() and cpu_req.read_text().strip()
                and not cpu_req.read_text().strip().startswith("#")):
            run_pip_install(cpu_req)

    # 5. Desktop dependencies
    print_section("  DESKTOP SETUP")
    print()
    if DESKTOP_DIR.exists() and (DESKTOP_DIR / "package.json").exists():
        print("  " + C.GRAY + "Installing desktop dependencies (npm install)..." + C.RESET)
        npm_cmd = "npm.cmd" if IS_WINDOWS else "npm"
        try:
            subprocess.check_call([npm_cmd, "install"], cwd=str(DESKTOP_DIR))
            print("  " + ok("Desktop dependencies installed."))
        except FileNotFoundError:
            print("  " + warn(f"'{npm_cmd}' not found."))
            print("  Please install Node.js from " + C.CYAN + "https://nodejs.org/" + C.RESET)
            print(f"  Then run 'npm install' in {DESKTOP_DIR.name}/ manually.")
        except subprocess.CalledProcessError:
            print("  " + err("Failed to install desktop dependencies."))
            print(f"  Please run 'npm install' in {DESKTOP_DIR.name}/ manually.")
    else:
        print("  " + skip(f"Skipped: {DESKTOP_DIR.name}/package.json not found."))

    # 6. AI provider configuration
    configure_ai_providers()

    # 7. Completion block — read back the final written state
    final_groq = ""
    final_gemini = ""
    env_file = ENGINE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            ls = line.strip()
            if ls.startswith("GROQ_API_KEY="):
                final_groq = ls.split("=", 1)[1].strip(" '\"")
            elif ls.startswith("GEMINI_API_KEY="):
                final_gemini = ls.split("=", 1)[1].strip(" '\"")

    print_setup_complete(bool(final_gemini), bool(final_groq))


if __name__ == "__main__":
    main()
