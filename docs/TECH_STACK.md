# MeetNote Technical Stack

This document explains the technology choices and the important architectural decisions in MeetNote. It is written for developers who want to understand the system, not as a full manual. For deeper implementation notes (module map, process-lifecycle detail, GPU/CUDA quirks) see `docs/ARCHITECTURE.md`. For the Linux verification checklist see `docs/LINUX_TESTING.md`.

## Frontend

- **React 19 + TypeScript**: the UI. TypeScript catches a large class of bugs at compile time, which matters more here than usual because the frontend talks to a separate backend process over HTTP/WebSocket with no shared types unless we define them ourselves (`desktop/src/types/engine.ts`).
- **Vite**: dev server and bundler. Fast rebuilds during development, and produces the static `dist/` bundle Tauri serves in the built app.
- **Zustand**: small, hook-based state store (`desktop/src/stores`) for UI-only state (current page, toasts). Meeting/session state lives in the engine and is fetched, not duplicated in a client-side store.
- **Tailwind CSS v4**: utility classes plus a small set of CSS custom properties (`--color-*`, spacing, radii) used as design tokens, so the whole app's look can be changed from one place without hunting through components.
- **lucide-react**: the one icon set used throughout, for visual consistency.

## Desktop

- **Tauri v2 (Rust)**: the native shell. Chosen over Electron for a much smaller binary and lower idle memory, since the app is otherwise just a webview showing the React UI. Tauri is deliberately kept thin (`desktop/src-tauri/src/lib.rs`): it launches the Python engine as a child process, guarantees that process is killed when the app closes (so a device is never left held open by an orphaned process), and exposes a handful of native commands the browser sandbox cannot do itself:
  - `open_path`: opens a file or folder with the OS's native file manager / default application (`explorer.exe` on Windows, `xdg-open` on Linux, `open` on macOS)
  - `open_in_notepad`: opens a plain-text file in a plain-text editor specifically, regardless of file associations
  - clipboard access, via the official `tauri-plugin-clipboard-manager` (not the browser `navigator.clipboard` API, whose permission behavior is inconsistent between Tauri's WebView2 and WebKitGTK backends)
  - `restart_app` / `engine_port`: process control and configuration for the frontend
- The frontend talks to the engine directly over `http://127.0.0.1:28765` (HTTP + WebSocket) rather than through Tauri IPC, because the API surface (meetings, transcripts, settings) is naturally a REST/WebSocket API and this keeps the Rust layer free of product logic entirely.

## Backend

- **Python + FastAPI**: the engine (`engine/main.py`). Python was the practical choice because faster-whisper, the AI provider SDKs, and `soundcard` are all Python-first, and this way the whole transcription/AI pipeline is one process without a cross-language boundary in the hot path. FastAPI gives async routes, WebSocket support, and request validation with very little boilerplate.
- The engine and the desktop app are two separate local processes talking over loopback HTTP, not a library embedded into Rust. This keeps the engine independently testable (`pytest`, no Tauri or webview needed) and means engine crashes or restarts don't take the UI process down with them.

## Audio

- **`soundcard`** is the one audio library used on both platforms. It wraps WASAPI on Windows and PulseAudio (including PipeWire's PulseAudio-compatible server, the default on modern Ubuntu) on Linux behind one API, so `engine/audio/soundcard_common.py`'s capture logic, chunking, and reconnect/backoff behavior is shared, unmodified, across both operating systems. `engine/audio/windows.py` and `engine/audio/linux.py` are thin subclasses that exist for OS-specific fallback behavior only, selected once by `AudioCaptureFactory` (`engine/audio/factory.py`) based on `os_detect.detect_os()` — no other module is allowed to branch on OS for audio.
- **System audio** (what you hear, not the microphone again) is captured via the default output device's loopback/monitor stream: `soundcard.get_microphone(id=<speaker id>, include_loopback=True)`. On Linux, if a minimal PipeWire setup hasn't advertised a monitor source yet, `LinuxAudioCapture` falls back to asking `pactl` directly for the default sink's `<sink>.monitor` source.
- **`AudioHealthMonitor`** (`engine/audio/health.py`) is a separate concern from capture itself: a single dedicated background thread that periodically probes device availability for the System Health panel, independent of whether a meeting is recording. It exists because:
  - Opening a device from `/health`'s request handler directly used to run on a different OS thread on every call (FastAPI's request threadpool), which broke Windows' COM apartment-threading assumption and caused devices to flicker between "Connected" and "Not ready" with nothing actually wrong.
  - Probing on every `/health` poll also meant contending with a real recording session for the same device.
  - The fix: one dedicated thread owns all probing, a lock-protected cache serves `/health` (never triggering a probe itself), hysteresis requires two consecutive failures before reporting a device unavailable (so a single transient blip doesn't flip the UI red), and the monitor stops probing entirely while a meeting is actively recording, deferring instead to the real recorder's own live status. This same probe reuses the platform `AudioCapture`'s device-resolution logic (including the Linux pactl fallback), so health status can never disagree with what a real meeting would actually experience.

## Transcription

- **faster-whisper** (built on **CTranslate2**) for local speech-to-text, chosen for meaningfully faster inference than the reference `openai-whisper` implementation at the same accuracy, on both CPU and GPU.
- Whisper's own language detection identifies the spoken language per chunk; English speech is transcribed as-is, and supported non-English speech is translated directly into English (Whisper's built-in translate task), so downstream AI note generation always works from an English transcript.
- **CPU / GPU modes**: `engine/hardware/detector.py` detects an NVIDIA GPU and, critically, verifies CUDA is actually *usable* by the installed CTranslate2 build (a GPU can be present while the CUDA/cuDNN runtime it needs is missing) rather than assuming GPU-present means GPU-usable. On Windows, `engine/cuda_env.py` additionally registers the pip-installed cuDNN/cuBLAS DLL directories, which Windows does not search by default; this is a no-op on Linux, where the equivalent shared libraries are found automatically.

## AI

- **Gemini** and **Groq** are the two supported note-generation providers (`engine/intelligence/providers/`), behind a common `LLMProvider` interface.
- **`AIRouter`** (`engine/intelligence/router.py`) picks the active provider(s) per request, not per meeting or globally: if both are configured, Gemini is tried first and Groq is used automatically only if that specific request fails. If only one is configured, it is used alone. If neither is configured, meeting recording, transcription, and local storage all still work; only AI-generated notes are unavailable until a key is added.

## Storage

- **SQLite** (`engine/storage/db.py`) is a lightweight index (title, dates, status) used to render the dashboard quickly without reading every meeting folder's metadata from disk.
- The **source of truth** for a meeting is its own folder under `~/MeetNote/meetings/<date>_<slug>/`, containing `metadata.json`, `transcript.json`/`.txt`, and `notes.md`/`.txt`. Every write to these files is atomic (write to a temp file, `fsync`, then rename) so a crash mid-write can never corrupt them.

## Configuration

- `engine/.env` holds API keys only, created and updated by `setup.py`; it is excluded from Git.
- `~/MeetNote/config.json` holds everything else (hardware mode, template selection, storage location), managed by `engine/storage/config.py`.
- API keys are deliberately kept out of Git and out of the SQLite database or config.json, in a single well-known file the user can inspect or edit directly if needed.

## Process Architecture

```
run_meetnote.py
    |
    +--> Python engine (127.0.0.1:28765)
    |       |
    |       +--> audio capture (soundcard, platform-specific fallback only)
    |       +--> faster-whisper transcription
    |       +--> AI note generation (Gemini / Groq)
    |       +--> local storage (SQLite + meeting files)
    |
    +--> Tauri desktop app
            |
            +--> React UI (talks to the engine directly over HTTP/WebSocket)
```

`run_meetnote.py` is a pure orchestrator: it starts the engine, waits for a real `/health` response, starts the desktop app, and shuts both down together. It contains no product logic of its own (no audio, no Whisper, no AI calls).

## Startup Flow

```
launcher -> engine process starts -> poll /health until ready -> Tauri window opens -> React UI loads and connects
```

The desktop app is never shown before the engine can actually answer `/health`, so the UI never has to guess whether the backend is available yet.

## Hardware Selection

Three modes, chosen in Settings: Automatic (GPU if usable, else CPU), NVIDIA GPU (required; does not silently fall back), and CPU only. Whisper is loaded once at engine startup according to the selected mode, so changing the mode requires restarting the engine to take effect. This is a deliberate simplification: reloading a multi-gigabyte model mid-session, on a possibly different device, is a bigger source of instability than asking for a restart.

## Recovery

Every transcribed chunk is written to disk before the next chunk starts, so an interrupted meeting never loses more than the current in-flight chunk. On engine startup, `engine/recovery/checkpoint.py` scans every meeting folder's `metadata.json` for a non-terminal status; the UI then offers to resume (continuing chunk numbering and timestamps from the last committed chunk) or mark the meeting abandoned without deleting its data. Audio capture itself is never restarted retroactively for a meeting that has already ended: recovery only reattaches a *new* capture session going forward, since resuming the exact old audio stream after a process restart is not meaningful.

## Security / Privacy

- Meeting audio and transcripts never leave the machine; only transcript text is sent to the configured AI provider for note generation.
- API keys live in one file (`engine/.env`), never in the database, config, or logs.
- All "open a path" operations are validated (must exist) before being handed to the OS, and always go through the OS's own file-open mechanism (`explorer.exe`, `xdg-open`, `open`) as a single argument, never through a shell (`cmd /C`, `shell=True`) — there is no shell-injection surface.
- `.gitignore` excludes `.env`, meeting data, logs, the SQLite database, and build output from version control.

## Platform Support

| Feature | Windows | Ubuntu |
|---|---|---|
| Setup (`setup.py`) | tested | implemented, untested on real hardware |
| Launcher (`run_meetnote.py` / `.sh`) | tested | implemented, untested on real hardware |
| Tauri desktop app | tested | implemented, untested on real hardware |
| Microphone capture | tested | implemented, untested on real hardware |
| System audio capture | tested | implemented, untested on real hardware |
| Audio health monitoring | tested | implemented, untested on real hardware |
| Whisper (CPU) | tested | implemented, untested on real hardware |
| Whisper (GPU) | tested | implemented, untested (no Ubuntu NVIDIA hardware available) |
| Gemini / Groq | tested | implemented (platform-agnostic Python; no OS-specific code path) |
| Copy Summary / Open Notes / Open folder | tested | implemented, untested on real hardware |

"Implemented, untested" means the code follows the same platform-agnostic interfaces and has unit-test coverage with simulated hardware, but no Ubuntu machine or VM was available in this development environment to run it against real audio devices, a real Tauri build, or a real filesystem end to end. See `docs/LINUX_TESTING.md` for the exact steps to verify this before relying on it in production.
