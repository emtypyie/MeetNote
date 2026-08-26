# MeetNote Architecture

## Overview

```
run_meetnote.py (root-level launcher — orchestrates, owns no product logic)
        │ spawns, waits for /health, then starts
        ▼
desktop/ (Tauri + React + Vite + TS)         engine/ (Python, FastAPI + WebSocket)
  React UI  <── fetch + WebSocket ──────────>  127.0.0.1:8765
  src-tauri spawns/kills its own engine ONLY when NOT launcher-managed
  (MEETNOTE_LAUNCHER_MANAGED unset — e.g. `npm run tauri dev` run directly)
```

The Rust/Tauri layer is deliberately thin: native window, spawning the
engine as a child process, and OS file-open actions (via
`@tauri-apps/plugin-opener`). Every product behavior — OS/hardware
detection, audio capture, transcription, persistence, crash recovery, AI
notes — lives in the Python engine, isolated from the UI so the webview
never blocks on it (product spec sections 28, 37, 38).

`run_meetnote.py` at the project root is the single command that starts the
whole application (`python run_meetnote.py`) — see the README's "Launcher
details" section for the full lifecycle. It owns *process orchestration*
only: it starts the engine, polls its real `/health` endpoint until ready,
starts the desktop app (built executable if one exists, else `npm run tauri
dev`), and shuts everything down when the desktop app closes. It sets
`MEETNOTE_LAUNCHER_MANAGED=1` in the desktop process's environment so
`src-tauri/src/lib.rs` knows not to spawn a second engine of its own —
running the desktop app directly (without the launcher) is unaffected and
behaves exactly as it always has, spawning and owning its own engine.

## Engine module map

```
engine/
├── main.py                 FastAPI app, lifespan startup, all HTTP/WS routes
├── session.py               MeetingSession: ties one meeting's capture+
│                             transcription+persistence+state machine together
├── ai_pipeline.py            Post-meeting AI notes orchestration, decoupled
│                             from any live session (works for retry-after-restart)
├── cuda_env.py                Registers pip-installed CUDA/cuDNN DLL dirs on
│                              Windows — see "GPU/CUDA notes" below
├── logging_setup.py            Structured logs to storage/logs/, never mixed
│                                with meeting transcript data
├── os_detect/                   detect_os() — the only OS branch point for
│                                 audio (audio/factory.py)
├── hardware/
│   ├── detector.py                CPU/RAM/GPU/VRAM + genuine CUDA-usability
│   │                               probe (not just "GPU exists")
│   ├── model_selector.py           HardwareProfile -> model/device/compute
│   │                                decision, driven by...
│   └── model_profiles.json          ...this data file (not hardcoded branches)
├── audio/
│   ├── base.py                    AudioCapture interface
│   ├── factory.py                  AudioCaptureFactory (Windows/Linux switch)
│   ├── soundcard_common.py          Shared `soundcard`-based implementation
│   ├── windows.py / linux.py         Thin OS-specific subclasses
│   └── health.py                     Non-invasive device probe for /health
├── transcription/
│   ├── whisper_engine.py            faster-whisper wrapper + GPU->CPU fallback
│   └── pipeline.py                   Audio chunk queue -> Whisper -> ChunkRecord
├── state/machine.py                Explicit MeetingState enum + transition table
├── recovery/checkpoint.py           Crash-recovery scan on startup
├── storage/
│   ├── paths.py / atomic.py           Filesystem layout + crash-safe writes
│   ├── meeting_store.py                Per-meeting metadata.json/transcript.*
│   ├── db.py                            SQLite index for the dashboard
│   └── config.py                         Settings (never stores API keys)
├── intelligence/
│   ├── providers/                      LLMProvider, GroqProvider, GeminiProvider
│   ├── router.py                        AIRouter: per-request fallback
│   ├── prompts/                         Analysis + notes-generation prompts
│   ├── analysis/service.py               Orchestrates analysis -> notes -> validate
│   ├── validation/checks.py               Deterministic QC (spec section 22)
│   └── templates.py                       User-configurable note templates
└── export/                              txt / md / docx writers
```

## Data flow (recording)

```
AudioCaptureFactory.create()
  -> mic + system-audio loopback, two background threads
  -> assembler thread mixes both into ~25s chunks
  -> TranscriptionPipeline queue (decouples capture from GPU/CPU work)
  -> WhisperTranscriber.transcribe_chunk()
  -> MeetingSession._on_chunk_result()
  -> MeetingStore.append_chunk_record()
       - transcript.json (atomic write)
       - transcript.txt (human-readable append)
       - metadata.json.last_completed_chunk (atomic write)
  -> broadcast over WebSocket to the UI
```

Every step between "chunk transcribed" and "chunk safely on disk" happens
before the next chunk starts, and `storage/atomic.py` guarantees a crash
mid-write never corrupts a file (write to `.tmp`, `fsync`, `os.replace`).

## Crash recovery

On engine startup, `recovery/checkpoint.py` scans every meeting folder's
`metadata.json` directly from disk (not just the SQLite cache) for a
non-terminal `status`. The frontend's `RecoveryModal` offers Resume (which
calls `POST /meetings/{id}/resume-after-restart`, reattaching a fresh
`MeetingSession` that continues chunk indices and timestamps from the last
committed chunk) or Start New Meeting (marks the old one abandoned without
deleting any data).

This was tested by starting a real recording, force-killing the engine
process mid-meeting, and confirming on restart that (a) the recovery scan
found it, (b) resuming continued cleanly, (c) no already-committed chunk
was lost or duplicated.

## Process lifecycle notes (launcher)

`run_meetnote.py` needs to tell the difference between "the engine exited
because we asked it to" and "the engine died on its own" (product spec
section 23), and needs a *graceful* stop, not a hard kill, so FastAPI's
lifespan shutdown code actually runs. Two Windows-specific things worth
knowing if you're debugging this:

- **Graceful stop on Windows uses `CTRL_BREAK_EVENT`, not `terminate()`.**
  Windows has no SIGTERM for arbitrary processes; `Popen.terminate()` there
  calls `TerminateProcess` (a hard kill). The launcher instead spawns the
  engine with `CREATE_NEW_PROCESS_GROUP` and sends `signal.CTRL_BREAK_EVENT`
  to request a graceful stop — uvicorn handles this and runs the full
  `lifespan` shutdown sequence (`Shutting down` -> `Waiting for application
  shutdown` -> `Application shutdown complete` in engine.log), confirmed by
  actually reading that log after a launcher-initiated stop, not assumed.
  On Linux/macOS this is a plain `terminate()` (SIGTERM), which uvicorn
  already handles the same way.
- **A venv's `python.exe` can itself have a child process on Windows.**
  Depending on how the venv was created, `engine/.venv/Scripts/python.exe`
  can be a small launcher stub that re-execs the real base interpreter as
  its *own child process* rather than patching `sys.prefix` in place (there
  is no true `exec()` on Windows, so any redirection has to be a spawn).
  You may see two `python.exe` processes for one logical engine — a stub
  (parent) and the real interpreter running `main.py` (child), both in the
  same process group. This is normal Python/Windows behavior, not a
  double-started engine; `Get-CimInstance Win32_Process` and checking
  `ParentProcessId` is the fastest way to confirm this if a process listing
  looks like there are two engines running.

## GPU/CUDA notes (read before assuming GPU mode "just doesn't work")

`ctranslate2`'s GPU path needs cuBLAS/cuDNN at runtime. On Windows, Python
no longer searches `PATH` for a C extension's DLL dependencies by default,
and — this was hit and fixed during development — cuDNN 9's *own internal
plugin loader* (`cudnn64_9.dll` loading `cudnn_ops64_9.dll` etc.) does a
classic `LoadLibrary` call that only honors `PATH`, not
`os.add_dll_directory`. Without both fixes, GPU transcription doesn't fail
gracefully — it hard-crashes the whole process with an uncatchable native
fault the moment the first real chunk is transcribed (not at model load
time, which is why a naive try/except around model loading isn't enough).

`engine/cuda_env.py` fixes this by registering the `nvidia-cudnn-cu12` /
`nvidia-cublas-cu12` pip packages' DLL directories with both
`os.add_dll_directory` *and* by prepending them to `PATH`, called before any
GPU-touching import. This was verified end-to-end on an RTX 4060 laptop GPU
(8GB VRAM): real GPU transcription, `medium` model, fp16, confirmed stable
across multiple chunks, pause/resume, and a simulated mid-meeting crash.

If you see `Could not locate cudnn_ops64_9.dll` despite this fix, check
that `pip install -r requirements.txt` actually completed (the cuDNN wheel
is large) and that `engine/cuda_env.py` is being imported before any other
module that touches `ctranslate2` (main.py imports it first for this
reason).

## Known architectural limitations (see also the top-level README)

- **Packaging**: the Rust shell spawns the engine from `engine/.venv` in
  dev-mode source layout. A distributable build needs the engine frozen
  into a standalone executable (e.g. PyInstaller) wired in as a Tauri
  "externalBin" sidecar — not implemented yet (see `lib.rs`'s
  `resolve_engine_paths` docstring).
- **Linux audio path**: implemented behind the same `AudioCapture`
  interface as Windows (`soundcard`'s PulseAudio/PipeWire-Pulse backend,
  with a `pactl` monitor-source fallback), but this development session had
  no Linux machine to verify it on. See `docs/LINUX_TESTING.md`.
- **GPU pre-flight check isn't crash-proof**: `hardware/detector.py`'s CUDA
  usability probe calls into `ctranslate2` directly rather than in an
  isolated subprocess. The `cuda_env.py` fix resolves the specific failure
  mode found during testing, but a *different* native GPU fault could in
  principle still crash the whole engine process rather than degrading to
  CPU. Isolating that probe in a subprocess would close this gap; it's a
  reasonable next hardening step, not done in this pass.
- Manual audio device selection, input/output gain, and storage retention
  are represented in config but not wired into actual behavior yet — the
  Settings UI says so explicitly rather than presenting non-functional
  controls as if they worked.
- **`run_meetnote.py` refuses to start if port 8765 is already occupied**,
  by design (see README "Launcher details" / Troubleshooting) — it cannot
  safely tell "a previous MeetNote engine that didn't shut down" apart from
  "something unrelated," so it asks the user to close whatever's there
  rather than guessing. It does not attempt to detect or reuse an existing
  MeetNote engine.
- `run_meetnote.py` has the same packaging assumption as the Rust shell: it
  expects `engine/.venv` next to the source tree and a built Tauri
  executable (if any) under `desktop/src-tauri/target/`, not an installed/
  bundled layout — it's a development/local-run launcher, not an installer.
- `run_meetnote.py`'s Linux/macOS code paths (SIGTERM-based graceful
  shutdown, extensionless binary lookup) follow the same pattern as the
  Windows paths but were not exercised on a real Linux/macOS machine this
  session — only Windows was actually tested.
