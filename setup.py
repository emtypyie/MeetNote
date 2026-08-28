#!/usr/bin/env python3
"""MeetNote Complete Bootstrapper & Setup Script."""

import argparse
import getpass
import platform
import subprocess
import sys
import venv
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENGINE_DIR = PROJECT_ROOT / "engine"
DESKTOP_DIR = PROJECT_ROOT / "desktop"
VENV_DIR = ENGINE_DIR / ".venv"

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


# ---------------------------------------------------------------------------
# Colour / ANSI support
# ---------------------------------------------------------------------------

def _enable_windows_ansi() -> bool:
    if not IS_WINDOWS:
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        ENABLE_VTP = 0x0004
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VTP)
        return True
    except Exception:
        return False

_ANSI_OK = _enable_windows_ansi()

class C:
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
    return C.YELLOW + C.BOLD + "[WARN]" + C.RESET + " " + msg

def err(msg: str) -> str:
    return C.RED + C.BOLD + "[ERROR]" + C.RESET + " " + msg

def skip(msg: str) -> str:
    return C.GRAY + "[--]" + C.RESET + " " + msg
    
def missing(msg: str) -> str:
    return C.RED + C.BOLD + "[MISSING]" + C.RESET + " " + msg

def wait(msg: str) -> str:
    return C.YELLOW + C.BOLD + "[WAIT]" + C.RESET + " " + msg

def mask_api_key(key: str) -> str:
    if not key: return ""
    for prefix in ("gsk_", "AIza", "sk-"):
        if key.startswith(prefix):
            hidden_len = len(key) - len(prefix)
            return C.DIM + prefix + C.RESET + C.YELLOW + "*" * hidden_len + C.RESET
    return C.YELLOW + "*" * len(key) + C.RESET


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

def run_quiet(cmd: list[str]) -> bool:
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def check_python_version():
    major = sys.version_info.major
    minor = sys.version_info.minor
    if major == 3 and minor in (10, 11, 12):
        return f"{major}.{minor}.{sys.version_info.micro}", True
    return f"{major}.{minor}.{sys.version_info.micro}", False

def discover_python_interpreter() -> str | None:
    versions_to_try = ["3.12", "3.11", "3.10"]
    if IS_WINDOWS:
        for v in versions_to_try:
            try:
                cmd = ["py", f"-{v}", "-c", "import sys; print(sys.executable)"]
                out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
                if out.strip():
                    return out.strip()
            except Exception:
                pass
    else:
        for v in versions_to_try:
            path = shutil.which(f"python{v}")
            if path:
                return path
    return None

def has_nvidia_gpu() -> tuple[bool, str]:
    try:
        if IS_WINDOWS:
            cmd = ["powershell", "-Command", "Get-CimInstance -ClassName Win32_VideoController | Select-Object -ExpandProperty Name"]
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if "NVIDIA" in line.upper():
                    return True, line.strip()
        elif IS_LINUX:
            out = subprocess.check_output(["lspci"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if "NVIDIA" in line.upper() and ("VGA" in line or "3D" in line):
                    return True, line.split(":")[-1].strip()
    except Exception:
        pass
    return False, ""

def validate_prerequisites() -> str:
    print_section("  SYSTEM REQUIREMENTS")
    print()
    
    all_ok = True
    
    py_ver, py_ok = check_python_version()
    discovered_python = sys.executable if py_ok else discover_python_interpreter()

    if discovered_python:
        if py_ok:
            print(f"  {'Python':<22} {ok(py_ver)}")
        else:
            print(f"  {'Python':<22} {C.YELLOW}Unsupported {py_ver}. Using {discovered_python}{C.RESET}")
        py_ok = True
    else:
        print(f"  {'Python':<22} {err(py_ver)}")
        py_ok = False
        
    if not py_ok:
        all_ok = False
        
    has_node = shutil.which("node") is not None
    print(f"  {'Node.js':<22} {ok('') if has_node else missing('')}")
    
    has_npm = shutil.which("npm") is not None
    print(f"  {'npm':<22} {ok('') if has_npm else missing('')}")
    
    if not has_node or not has_npm:
        all_ok = False
        
    has_git = shutil.which("git") is not None
    print(f"  {'Git':<22} {ok('') if has_git else skip('Not installed (Optional)')}")
    
    has_rust = shutil.which("rustc") is not None
    print(f"  {'Rust':<22} {ok('') if has_rust else missing('')}")
    
    has_cargo = shutil.which("cargo") is not None
    print(f"  {'Cargo':<22} {ok('') if has_cargo else missing('')}")
    
    if not has_rust or not has_cargo:
        all_ok = False
        
    tauri_ok = True
    if IS_LINUX:
        has_pkg_config = shutil.which("pkg-config") is not None
        if not has_pkg_config:
            tauri_ok = False
        else:
            # Check for tauri dependencies
            tauri_ok = run_quiet(["pkg-config", "--exists", "webkit2gtk-4.1", "gtk+-3.0", "ayatana-appindicator3-0.1"])
        print(f"  {'Tauri prerequisites':<22} {ok('') if tauri_ok else missing('Missing dev packages')}")
        if not tauri_ok:
            all_ok = False

    print()
    print_divider()
    
    if not all_ok:
        print()
        print("  " + C.RED + C.BOLD + "Missing Prerequisites Detected" + C.RESET)
        print()
        
        if not py_ok:
            print(f"  Python 3.10-3.12 is required. You have {py_ver}.")
            print("  We could not find a compatible Python installation on your system.")
            print("  Please install Python 3.12 from https://www.python.org/")
            print()
            
        if not has_node or not has_npm:
            print("  Node.js and npm are required to build the frontend.")
            print("  Please install Node.js (v22+ recommended) from https://nodejs.org/")
            print()
            
        if not has_rust or not has_cargo:
            print("  Rust and Cargo are required to build the desktop application.")
            if IS_LINUX:
                print("  Install Rust by running:")
                print("    " + C.CYAN + "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh" + C.RESET)
            else:
                print("  Install Rust from https://rustup.rs/")
            print()
            
        if IS_LINUX and not tauri_ok:
            print("  Linux requires development packages to build Tauri apps.")
            print("  Please install them by running:")
            print("    " + C.CYAN + "sudo apt update && sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file libssl-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev" + C.RESET)
            print()
            
        print("  " + C.GRAY + "Setup stopped. Please install the missing prerequisites and run setup.py again." + C.RESET)
        print()
        sys.exit(1)
        
    return discovered_python


def get_venv_pip() -> Path:
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"
    
def get_venv_python() -> Path:
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"

def check_venv_python_version() -> tuple[bool, str]:
    venv_py = get_venv_python()
    if not venv_py.exists():
        return False, "Not found"
    try:
        cmd = [str(venv_py), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        parts = out.split('.')
        major = int(parts[0])
        minor = int(parts[1])
        if major == 3 and minor in (10, 11, 12):
            return True, out
        return False, out
    except Exception:
        return False, "Unknown"

def run_pip_cmd(args: list[str], description: str) -> None:
    pip_exe = get_venv_pip()
    print(f"  {C.GRAY}Running: pip {' '.join(args)}...{C.RESET}")
    cmd = [str(pip_exe)] + args
    try:
        subprocess.check_call(cmd, cwd=str(ENGINE_DIR))
    except subprocess.CalledProcessError:
        print(f"\n  {err(f'Failed during: {description}')}")
        sys.exit(1)


def configure_ai_providers() -> tuple[str, str]:
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

    print_section("  AI PROVIDER CONFIGURATION")
    print()
    print("  Configure " + C.CYAN + "Gemini" + C.RESET + ", " + C.BLUE + "Groq" + C.RESET + ", or both.")
    print("  If both are configured, " + C.CYAN + "Gemini" + C.RESET + " is primary.")
    print("  " + C.GRAY + "Press Enter to skip a provider." + C.RESET)
    print()

    new_groq = groq_key
    if groq_key:
        print("  " + C.GRAY + f"Groq API key [already configured]: " + C.RESET + mask_api_key(groq_key))
    else:
        raw = getpass.getpass("  Groq API key [optional]: ").strip()
        new_groq = raw
        if raw:
            print("  " + C.GRAY + "Groq API key: " + C.RESET + mask_api_key(raw))

    new_gemini = gemini_key
    if gemini_key:
        print("  " + C.GRAY + f"Gemini API key [already configured]: " + C.RESET + mask_api_key(gemini_key))
    else:
        raw = getpass.getpass("  Gemini API key [optional]: ").strip()
        new_gemini = raw
        if raw:
            print("  " + C.GRAY + "Gemini API key: " + C.RESET + mask_api_key(raw))

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
        print("\n  " + err(f"Could not write engine/.env: {e}"))
        sys.exit(1)
        
    return new_gemini, new_groq

def check_built_binary() -> bool:
    target_dir = DESKTOP_DIR / "src-tauri" / "target"
    binary_name = "desktop.exe" if IS_WINDOWS else "desktop"
    for profile in ("release", "debug"):
        candidate = target_dir / profile / binary_name
        if candidate.exists():
            return True
    return False

def main():
    parser = argparse.ArgumentParser(description="MeetNote setup and dependency installation.")
    parser.add_argument("--cpu-only", action="store_true", help="Force CPU-only installation.")
    parser.add_argument("--gpu", action="store_true", help="Force GPU installation.")
    args = parser.parse_args()

    print_header("  MEETNOTE SETUP  ")
    
    python_exe = validate_prerequisites()

    print_section("  PYTHON ENVIRONMENT")
    print()
    if VENV_DIR.exists():
        ok_ver, ver_str = check_venv_python_version()
        if not ok_ver:
            print(f"  {warn(f'Existing virtual environment has incompatible Python {ver_str}.')}")
            print(f"  {C.GRAY}Removing incompatible environment...{C.RESET}")
            shutil.rmtree(VENV_DIR, ignore_errors=True)
        else:
            print("  " + ok(f"Virtual environment already exists (Python {ver_str})."))

    if not VENV_DIR.exists():
        print("  Creating Python virtual environment in engine/.venv...")
        if python_exe == sys.executable:
            venv.create(VENV_DIR, with_pip=True)
        else:
            subprocess.check_call([python_exe, "-m", "venv", str(VENV_DIR)])

    pip_exe = get_venv_pip()
    if not pip_exe.exists():
        print("  " + err(f"pip not found at {pip_exe}. Virtual environment corrupted."))
        sys.exit(1)
        
    # Upgrade pip
    run_pip_cmd(["install", "--upgrade", "pip"], "pip upgrade")

    print_section("  HARDWARE DETECTION")
    print()
    has_gpu, gpu_name = has_nvidia_gpu()
    gpu_detected = False
    
    if args.cpu_only:
        print("  " + skip("Mode: CPU-only (forced by --cpu-only)"))
    elif args.gpu:
        gpu_detected = True
        print("  " + ok("Mode: GPU-capable (forced by --gpu)"))
    else:
        print("  " + C.GRAY + "Detecting NVIDIA GPU..." + C.RESET)
        if has_gpu:
            print("  " + ok(f"NVIDIA GPU detected: {gpu_name}"))
            print("  " + ok("Mode: GPU-capable"))
            gpu_detected = True
        else:
            print("  " + skip("NVIDIA GPU not detected"))
            print("  " + skip("Mode: CPU-only"))
            
    print_section("  PYTHON DEPENDENCIES")
    run_pip_cmd(["install", "-r", "requirements-base.txt"], "installing requirements-base.txt")
    
    if gpu_detected:
        print("\n  " + C.PURPLE + "Installing GPU dependencies..." + C.RESET)
        run_pip_cmd(["install", "-r", "requirements-gpu.txt"], "installing requirements-gpu.txt")
    else:
        cpu_req = ENGINE_DIR / "requirements-cpu.txt"
        print("\n  " + skip("GPU dependencies skipped (CPU-only mode)"))
        if cpu_req.exists() and cpu_req.read_text().strip() and not cpu_req.read_text().strip().startswith("#"):
            run_pip_cmd(["install", "-r", "requirements-cpu.txt"], "installing requirements-cpu.txt")
            
    print("\n  " + C.GRAY + "Validating dependency graph (pip check)..." + C.RESET)
    try:
        subprocess.check_call([str(pip_exe), "check"], cwd=str(ENGINE_DIR))
        print("  " + ok("Python dependencies validated."))
    except subprocess.CalledProcessError:
        print("  " + err("pip check failed! Dependency conflicts detected."))
        sys.exit(1)

    print("\n  " + C.GRAY + "Validating runtime bindings (import faster_whisper, ctranslate2)..." + C.RESET)
    try:
        py_venv = get_venv_python()
        subprocess.check_call(
            [str(py_venv), "-c", "import faster_whisper; import ctranslate2"], 
            cwd=str(ENGINE_DIR)
        )
        print("  " + ok("Runtime bindings validated successfully."))
    except subprocess.CalledProcessError:
        print("  " + err("Runtime binding validation failed! Python version or native extensions may be incompatible."))
        sys.exit(1)

    print_section("  DESKTOP SETUP")
    print()
    npm_cmd = shutil.which("npm")
    
    print("  " + C.GRAY + "Installing desktop dependencies (npm install)..." + C.RESET)
    try:
        subprocess.check_call([npm_cmd, "install"], cwd=str(DESKTOP_DIR))
        print("  " + ok("Desktop dependencies installed."))
    except subprocess.CalledProcessError:
        print("  " + err("Failed to install desktop dependencies (npm install failed)."))
        sys.exit(1)
        
    print("\n  " + C.GRAY + "Building desktop executable (npm run tauri build -- --no-bundle)..." + C.RESET)
    print("  " + wait("This may take a few minutes to compile Rust dependencies."))
    try:
        subprocess.check_call([npm_cmd, "run", "tauri", "build", "--", "--no-bundle"], cwd=str(DESKTOP_DIR))
    except subprocess.CalledProcessError:
        print("\n  " + err("Tauri build failed."))
        sys.exit(1)
        
    if check_built_binary():
        print("\n  " + ok("Desktop executable built successfully."))
    else:
        print("\n  " + err("Tauri build completed, but executable was not found in target/release."))
        sys.exit(1)
        
    gemini_key, groq_key = configure_ai_providers()

    print()
    print_divider()
    print()
    print("  " + C.BOLD + C.WHITE + "SETUP COMPLETE" + C.RESET)
    print()
    
    print(f"  {'Python environment':<20} {ok('')}")
    print(f"  {'Python dependencies':<20} {ok('')}")
    print(f"  {'Node dependencies':<20} {ok('')}")
    print(f"  {'Rust/Cargo':<20} {ok('')}")
    print(f"  {'Tauri build':<20} {ok('')}")
    print(f"  {'Whisper environment':<20} {ok('')}")
    print(f"  {'.env':<20} {ok('')}")
    
    print()
    print("  " + C.BOLD + "AI Providers" + C.RESET)
    print(f"    {'Gemini':<18} {'Configured' if gemini_key else 'Not configured'}")
    print(f"    {'Groq':<18} {'Configured' if groq_key else 'Not configured'}")
    
    print()
    print("  " + C.BOLD + "AI Routing" + C.RESET)
    if gemini_key and groq_key:
        print("    Gemini -> Groq fallback")
    elif gemini_key:
        print("    Gemini")
    elif groq_key:
        print("    Groq")
    else:
        print("    Unavailable")
        print("    Local recording and transcription still work.")
        
    print()
    print("  " + C.BOLD + "Hardware" + C.RESET)
    if gpu_detected:
        print(f"    {'NVIDIA GPU':<18} {gpu_name if gpu_name else 'Detected'}")
        print(f"    {'Transcription':<18} CUDA / medium")
    else:
        print(f"    {'Transcription':<18} CPU / medium")
    
    print()
    print_divider()
    print()
    print("  " + C.BOLD + "Start MeetNote with:" + C.RESET)
    print("  " + C.GREEN + "  python run_meetnote.py" + C.RESET)
    print()

if __name__ == "__main__":
    main()
