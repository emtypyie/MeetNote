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
    print(f"\nInstalling dependencies from {req_file.name}...")
    cmd = [str(pip_exe), "install", "-r", str(req_file)]
    
    # We want real-time output for the user
    try:
        subprocess.check_call(cmd, cwd=str(ENGINE_DIR))
    except subprocess.CalledProcessError:
        print(f"\n[Error] Failed to install {req_file.name}")
        sys.exit(1)


def configure_ai_providers() -> None:
    env_file = ENGINE_DIR / ".env"
    
    # Parse existing values
    existing_lines = []
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

    print("\n--- MeetNote AI Provider Setup ---")
    print("You can configure either Groq or Gemini.")
    print("If both are configured, Gemini is used first and Groq is used as fallback.\n")
    
    new_groq = groq_key
    if groq_key:
        print("Groq API key already configured")
    else:
        new_groq = getpass.getpass("Groq API key [optional]: ").strip()
        
    new_gemini = gemini_key
    if gemini_key:
        print("Gemini API key already configured")
    else:
        new_gemini = getpass.getpass("Gemini API key [optional]: ").strip()

    # Update or append keys
    groq_updated = False
    gemini_updated = False
    
    new_lines = []
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
        print(f"\n[Error] Could not save API configuration to {env_file}.")
        print("Your existing configuration was not intentionally overwritten.")
        return

    print("\nConfiguration Summary")
    print("====================")
    
    is_groq_configured = bool(new_groq)
    is_gemini_configured = bool(new_gemini)
    
    print(f"Groq:\n{'Configured' if is_groq_configured else 'Not configured'}\n")
    print(f"Gemini:\n{'Configured' if is_gemini_configured else 'Not configured'}\n")
    
    print("AI routing:")
    if is_gemini_configured and is_groq_configured:
        print("Gemini -> Groq fallback")
    elif is_gemini_configured:
        print("Gemini")
    elif is_groq_configured:
        print("Groq")
    else:
        print("Unavailable")
        print("\nNo AI provider key was configured.")
        print("MeetNote can still record and transcribe meetings locally.")
        print("AI note generation is currently unavailable.")
        print("\nTo enable AI notes later, add either a Groq or Gemini API key to:")
        print(str(env_file.resolve()))


def main():
    parser = argparse.ArgumentParser(description="MeetNote setup and dependency installation.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--cpu-only", action="store_true", help="Force CPU-only installation (skip GPU dependencies).")
    mode_group.add_argument("--gpu", action="store_true", help="Force GPU installation (install CUDA/NVIDIA dependencies).")
    args = parser.parse_args()

    print("--- MeetNote Environment Setup ---")

    # 1. Ensure venv exists
    if not VENV_DIR.exists():
        print("Creating Python virtual environment in engine/.venv...")
        venv.create(VENV_DIR, with_pip=True)
    else:
        print("Virtual environment already exists.")

    pip_exe = get_venv_pip()
    if not pip_exe.exists():
        print(f"[Error] pip not found at {pip_exe}. Virtual environment may be corrupted.")
        sys.exit(1)

    # 2. Hardware Detection
    print("\n--- Hardware Detection ---")
    if args.cpu_only:
        gpu_detected = False
        print("Installation mode: CPU-only (forced by --cpu-only)")
    elif args.gpu:
        gpu_detected = True
        print("Installation mode: GPU-capable (forced by --gpu)")
    else:
        print("Detecting NVIDIA GPU...")
        gpu_detected = has_nvidia_gpu()
        if gpu_detected:
            print("NVIDIA GPU: detected")
            print("Installation mode: GPU-capable")
        else:
            print("NVIDIA GPU: not detected")
            print("Installation mode: CPU-only")

    # 3. Base requirements
    base_req = ENGINE_DIR / "requirements-base.txt"
    run_pip_install(base_req)

    # 4. Hardware-specific requirements
    if gpu_detected:
        gpu_req = ENGINE_DIR / "requirements-gpu.txt"
        print("\nGPU dependencies: Installing")
        run_pip_install(gpu_req)
    else:
        cpu_req = ENGINE_DIR / "requirements-cpu.txt"
        print("\nGPU dependencies: Skipped")
        if cpu_req.exists() and cpu_req.read_text().strip() and not cpu_req.read_text().strip().startswith("#"):
             run_pip_install(cpu_req)

    # 5. Desktop dependencies
    print("\n--- Desktop Setup ---")
    if DESKTOP_DIR.exists() and (DESKTOP_DIR / "package.json").exists():
        print("Installing desktop dependencies (npm install)...")
        npm_cmd = "npm.cmd" if IS_WINDOWS else "npm"
        try:
            subprocess.check_call([npm_cmd, "install"], cwd=str(DESKTOP_DIR))
        except FileNotFoundError:
            print(f"\n[Warning] '{npm_cmd}' not found. Please install Node.js and run 'npm install' in {DESKTOP_DIR.name}/ manually.")
        except subprocess.CalledProcessError:
            print(f"\n[Error] Failed to install desktop dependencies. Please run 'npm install' in {DESKTOP_DIR.name}/ manually.")
    else:
        print(f"Skipped: {DESKTOP_DIR.name}/package.json not found.")

    configure_ai_providers()

    print("\n--- Setup Complete ---")
    print("Environment successfully provisioned.")
    print("You can now start MeetNote by running:")
    print("  python run_meetnote.py")

if __name__ == "__main__":
    main()
