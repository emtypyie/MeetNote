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
# CLI presentation helpers
# ---------------------------------------------------------------------------

WIDTH = 62
BORDER = "=" * WIDTH
DIVIDER = "-" * WIDTH


def print_header(title: str) -> None:
    """Print a top-level section header with double-line borders."""
    print()
    print(BORDER)
    print(title.center(WIDTH))
    print(BORDER)


def print_section(title: str) -> None:
    """Print a section subtitle with no borders."""
    print()
    print(title)
    print(DIVIDER)


def print_divider() -> None:
    print(DIVIDER)


def mask_api_key(key: str) -> str:
    """Return a masked representation of an API key.

    Preserves a short recognisable prefix when one is present,
    and replaces the rest of the key with asterisks.
    The actual key is never returned or printed anywhere.
    """
    if not key:
        return ""
    # Known provider prefixes
    for prefix in ("gsk_", "AIza", "sk-"):
        if key.startswith(prefix):
            hidden_len = len(key) - len(prefix)
            return prefix + "*" * hidden_len
    # Unknown format: mask everything
    return "*" * len(key)


def print_provider_row(label: str, configured: bool, masked: str = "") -> None:
    """Print a single provider status row."""
    marker = "[OK]" if configured else "[--]"
    status = "Configured" if configured else "Not configured"
    detail = f"  {masked}" if configured and masked else ""
    print(f"  {marker} {label:<10} {status}{detail}")


def print_routing_summary(is_gemini: bool, is_groq: bool) -> None:
    """Print the AI routing summary line."""
    print()
    print("  AI ROUTING")
    if is_gemini and is_groq:
        print("  Gemini -> Groq fallback")
    elif is_gemini:
        print("  Gemini only - no fallback configured")
    elif is_groq:
        print("  Groq only - no fallback configured")
    else:
        print("  No AI provider configured")


def print_setup_complete(is_gemini: bool, is_groq: bool) -> None:
    """Print the final setup-complete block."""
    print()
    print_divider()
    print()
    print("  SETUP COMPLETE")
    print()

    if is_gemini or is_groq:
        print("  [OK] Environment configured successfully.")
        print()
        print("  AI provider:")
        if is_gemini and is_groq:
            print("  Gemini -> Groq fallback")
        elif is_gemini:
            print("  Gemini")
        else:
            print("  Groq")
    else:
        print("  [!] No AI provider configured.")
        print()
        print("  Local recording and transcription will still work.")
        print("  AI meeting notes require at least one API key.")
        print()
        print("  You can configure a provider later in:")
        print("      engine/.env")

    print()
    print("  Start MeetNote:")
    print("      python run_meetnote.py")
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
            # Using WMI via powershell to avoid relying on pypi wmi package
            cmd = ["powershell", "-Command", "Get-CimInstance -ClassName Win32_VideoController | Select-Object -ExpandProperty Name"]
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            return "NVIDIA" in out.upper()
        elif IS_LINUX:
            # lspci is standard on most linux distros
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
    print(f"\n  Installing from {req_file.name}...")
    cmd = [str(pip_exe), "install", "-r", str(req_file)]

    # We want real-time output for the user
    try:
        subprocess.check_call(cmd, cwd=str(ENGINE_DIR))
    except subprocess.CalledProcessError:
        print(f"\n  [ERROR] Failed to install {req_file.name}")
        sys.exit(1)


def configure_ai_providers() -> None:
    env_file = ENGINE_DIR / ".env"

    # Parse existing values
    existing_lines: list[str] = []
    groq_key = ""
    gemini_key = ""

    if env_file.exists():
        existing_lines = env_file.read_text(encoding="utf-8").splitlines()
        for line in existing_lines:
            line_stripped = line.strip()
            if line_stripped.startswith("GROQ_API_KEY="):
                groq_key = line_stripped.split("=", 1)[1].strip(" '\"")
            elif line_stripped.startswith("GEMINI_API_KEY="):
                gemini_key = line_stripped.split("=", 1)[1].strip(" '\"")

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    print_header("  MEETNOTE SETUP  ")

    print_section("  AI PROVIDER CONFIGURATION")
    print()
    print("  Configure Gemini, Groq, or both.")
    print("  If both are configured, Gemini is primary and")
    print("  Groq is used automatically as a fallback.")
    print("  Press Enter to skip a provider.")

    # -----------------------------------------------------------------------
    # API key prompts
    # -----------------------------------------------------------------------
    print_section("  API KEYS")
    print()

    new_groq = groq_key
    if groq_key:
        masked = mask_api_key(groq_key)
        print(f"  Groq API key [already configured]: {masked}")
    else:
        raw = getpass.getpass("  Groq API key [optional]: ").strip()
        new_groq = raw
        if raw:
            print(f"  Groq API key: {mask_api_key(raw)}")

    new_gemini = gemini_key
    if gemini_key:
        masked = mask_api_key(gemini_key)
        print(f"  Gemini API key [already configured]: {masked}")
    else:
        raw = getpass.getpass("  Gemini API key [optional]: ").strip()
        new_gemini = raw
        if raw:
            print(f"  Gemini API key: {mask_api_key(raw)}")

    # -----------------------------------------------------------------------
    # Write engine/.env (logic unchanged)
    # -----------------------------------------------------------------------
    groq_updated = False
    gemini_updated = False

    new_lines: list[str] = []
    for line in existing_lines:
        line_stripped = line.strip()
        if line_stripped.startswith("GROQ_API_KEY="):
            new_lines.append(f"GROQ_API_KEY={new_groq}")
            groq_updated = True
        elif line_stripped.startswith("GEMINI_API_KEY="):
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
        # Safe error display - never include key values
        print()
        print_divider()
        print("  [ERROR] Setup failed")
        print()
        print("  Could not write engine/.env.")
        print()
        print("  Reason:")
        # Only include the exception type, not repr which might contain args
        print(f"  {type(e).__name__}: {e.__class__.__module__}")
        print()
        print("  Please check file permissions and try again.")
        print_divider()
        return

    # -----------------------------------------------------------------------
    # Configuration summary
    # -----------------------------------------------------------------------
    is_groq_configured = bool(new_groq)
    is_gemini_configured = bool(new_gemini)

    print_section("  CONFIGURATION SUMMARY")
    print()
    print_provider_row(
        "Groq",
        is_groq_configured,
        mask_api_key(new_groq) if is_groq_configured else "",
    )
    print_provider_row(
        "Gemini",
        is_gemini_configured,
        mask_api_key(new_gemini) if is_gemini_configured else "",
    )
    print_routing_summary(is_gemini_configured, is_groq_configured)

    if not is_groq_configured and not is_gemini_configured:
        print()
        print("  No AI provider has been configured.")
        print("  MeetNote can still record and transcribe locally,")
        print("  but AI-generated meeting notes will not be available.")
        print()
        print("  You can add an API key later in:")
        print("      engine/.env")
        print()
        print("  At least one provider is recommended for AI notes.")


def main():
    parser = argparse.ArgumentParser(description="MeetNote setup and dependency installation.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--cpu-only", action="store_true", help="Force CPU-only installation (skip GPU dependencies).")
    mode_group.add_argument("--gpu", action="store_true", help="Force GPU installation (install CUDA/NVIDIA dependencies).")
    args = parser.parse_args()

    print_header("  MEETNOTE ENVIRONMENT SETUP  ")

    # 1. Ensure venv exists
    print_section("  PYTHON ENVIRONMENT")
    print()
    if not VENV_DIR.exists():
        print("  Creating Python virtual environment in engine/.venv...")
        venv.create(VENV_DIR, with_pip=True)
    else:
        print("  [OK] Virtual environment already exists.")

    pip_exe = get_venv_pip()
    if not pip_exe.exists():
        print(f"  [ERROR] pip not found at {pip_exe}. Virtual environment may be corrupted.")
        sys.exit(1)

    # 2. Hardware Detection
    print_section("  HARDWARE DETECTION")
    print()
    if args.cpu_only:
        gpu_detected = False
        print("  Mode: CPU-only (forced by --cpu-only)")
    elif args.gpu:
        gpu_detected = True
        print("  Mode: GPU-capable (forced by --gpu)")
    else:
        print("  Detecting NVIDIA GPU...")
        gpu_detected = has_nvidia_gpu()
        if gpu_detected:
            print("  [OK] NVIDIA GPU detected")
            print("  Mode: GPU-capable")
        else:
            print("  [--] NVIDIA GPU not detected")
            print("  Mode: CPU-only")

    # 3. Base requirements
    print_section("  PYTHON DEPENDENCIES")
    base_req = ENGINE_DIR / "requirements-base.txt"
    run_pip_install(base_req)

    # 4. Hardware-specific requirements
    if gpu_detected:
        gpu_req = ENGINE_DIR / "requirements-gpu.txt"
        print("\n  Installing GPU dependencies...")
        run_pip_install(gpu_req)
    else:
        cpu_req = ENGINE_DIR / "requirements-cpu.txt"
        print("\n  [--] GPU dependencies skipped (CPU-only mode)")
        if cpu_req.exists() and cpu_req.read_text().strip() and not cpu_req.read_text().strip().startswith("#"):
            run_pip_install(cpu_req)

    # 5. Desktop dependencies
    print_section("  DESKTOP SETUP")
    print()
    if DESKTOP_DIR.exists() and (DESKTOP_DIR / "package.json").exists():
        print("  Installing desktop dependencies (npm install)...")
        npm_cmd = "npm.cmd" if IS_WINDOWS else "npm"
        try:
            subprocess.check_call([npm_cmd, "install"], cwd=str(DESKTOP_DIR))
        except FileNotFoundError:
            print(f"\n  [!] '{npm_cmd}' not found.")
            print("  Please install Node.js from https://nodejs.org/")
            print(f"  Then run 'npm install' in {DESKTOP_DIR.name}/ manually.")
        except subprocess.CalledProcessError:
            print(f"\n  [ERROR] Failed to install desktop dependencies.")
            print(f"  Please run 'npm install' in {DESKTOP_DIR.name}/ manually.")
    else:
        print(f"  [--] Skipped: {DESKTOP_DIR.name}/package.json not found.")

    # 6. AI provider configuration
    configure_ai_providers()

    # 7. Completion block
    # Read back the final state from what configure_ai_providers() wrote
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
