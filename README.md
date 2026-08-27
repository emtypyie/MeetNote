# MeetNote

MeetNote is a desktop meeting assistant for Windows (Ubuntu/Linux support is
implemented but not yet run on real Linux hardware — see
[Limitations](#current-limitations)). It captures microphone and system
audio locally, transcribes it locally with `faster-whisper` (using an NVIDIA
GPU automatically when one is usable, falling back to CPU otherwise), saves
the transcript incrementally as it goes, and after the meeting sends the
**transcript text** — never the raw audio — to Groq (primary) or Gemini
(fallback) to generate structured, natural meeting notes.

## Features

Implemented and exercised in this repository (see [Validation](#validation-what-was-actually-tested)
below for what's been run, versus only implemented):

- Windows desktop application (Tauri + React); Linux/macOS architecture in place, not run on real hardware
- Automatic OS detection, automatic GPU/CUDA detection, automatic GPU↔CPU transcription switching
- Local `faster-whisper` transcription (no audio ever leaves the machine)
- Simultaneous microphone + system-audio capture (WASAPI loopback on Windows)
- Chunked transcription (~25s) with immediate, crash-safe local persistence
- Crash recovery: an interrupted meeting is detected on next startup and can be resumed
- Pause / Resume, and a "Mark Important" timestamp marker
- Configurable meeting note templates
- Groq as the primary AI notes provider, Gemini as the automatic fallback
- Live AI provider connectivity validation (not just "is a key present" — see [AI provider behavior](#ai-provider-behavior))
- Structured notes generation (decisions vs. proposals kept distinct, action items, deadlines, open questions)
- TXT, Markdown, and DOCX notes export
- A single root-level launcher (`run_meetnote.py`) that starts the engine, waits for it to be genuinely ready, opens the desktop app, and shuts everything down cleanly on exit

## Architecture

```
Microphone + System Audio
            |
      Local Audio Capture
            |
      Hardware Detection
            |
       faster-whisper
        /            \
   NVIDIA GPU         CPU
        \            /
       Local Transcript
            |
      Local Persistence (per-chunk, crash-safe)
            |
       Meeting Ends
            |
          Groq  ---- fails? ---->  Gemini (fallback)
            |
    Structured Analysis (decisions / action items / deadlines / open questions)
            |
       Final Notes (validated, then exported)
```

**Raw meeting audio never leaves the machine.** Transcription is 100% local.
Only the resulting transcript text, meeting metadata (title, template,
timestamps of anything marked important), and derived analysis are sent to
Groq/Gemini — and only after the meeting ends, only if a key is configured,
and only to generate the notes.

## Local Data

Meeting transcripts, summaries, chat history, recordings, runtime databases, and logs are local application data and are not committed to Git.

By default, MeetNote stores user runtime data in `~/MeetNote/` on your local machine. This keeps your personal meeting history safely separated from the application source code.

Process-wise:

```
run_meetnote.py (root launcher)
        |
        +--> engine/ (Python, FastAPI + WebSocket, 127.0.0.1:8765)
        |     owns: OS/hardware detection, audio capture, faster-whisper,
        |     persistence, crash recovery, meeting state, AI providers
        |
        +--> desktop/ (Tauri + React)
              thin native shell + UI; talks to the engine over
              fetch/WebSocket, never duplicates its logic
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full module map
and implementation notes (including two real bugs found and fixed during
development: a Windows cuDNN DLL-loading crash, and a Tauri CORS-origin
mismatch that silently broke every API call from the built app).

## Project structure

```
MeetNote/
├── run_meetnote.py          Canonical launcher — orchestrates engine + desktop, all platforms
├── run_meetnote.bat         Windows wrapper — delegates to run_meetnote.py, no logic of its own
├── run_meetnote.sh          Linux/macOS wrapper — delegates to run_meetnote.py, no logic of its own
├── README.md
├── .gitignore
│
├── engine/                  Python engine (FastAPI + WebSocket) — see engine/README.md
│   ├── main.py                 Entrypoint, all HTTP/WS routes
│   ├── .env                    API keys (local only, gitignored — see below)
│   ├── .env.example
│   ├── requirements.txt        Python dependency source of truth
│   ├── audio/ hardware/ transcription/ storage/ intelligence/ ...  (see docs/ARCHITECTURE.md)
│   └── tests/                  pytest suite (30 tests)
│
├── desktop/                 Tauri + React + Vite frontend
│   ├── src/                    React app (pages/components/stores/services)
│   ├── src-tauri/               Rust shell (spawns/manages the engine when not launcher-managed)
│   └── package.json
│
├── docs/                    ARCHITECTURE.md, LINUX_TESTING.md
└── logs/                    run_meetnote.py's own logs (launcher.log, engine.log) — directory
                              tracked via logs/.gitkeep, log files themselves gitignored
```

Two things worth calling out explicitly because they differ from the most
obvious guess:

- **`.env` lives at `engine/.env`**, not the project root — that's where
  `engine/main.py` has always deterministically resolved it from
  (`Path(__file__).parent / ".env"`, independent of working directory), and
  moving it would only add risk for no benefit. `run_meetnote.py` checks for
  it at that path.
- **There is no `meetings/` directory in this repository.** Recorded
  meetings (transcripts, notes, metadata) are stored under the current
  user's home directory by default (`~/MeetNote/meetings/`), not inside the
  project — meeting content is private user data, not source. The storage
  location is configurable from Settings.

## Environment configuration

Copy the template and fill in your own keys:

```bash
cp engine/.env.example engine/.env
```

```
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key
```

- `.env` stays local and is gitignored — never commit it.
- Only the Python engine reads these values; they are never sent to or
  readable by the React frontend, never logged, and never printed. The UI
  only ever shows a connectivity *state* (see below), never the key itself.
- Neither key is required to record or transcribe a meeting — that's fully
  local. Without a key, AI notes generation is marked "pending" and can be
  retried later once one is added.

## GPU / CPU behavior

Hardware and model selection are fully automatic — there is no setting for
this.

```
CUDA usable  -->  GPU transcription (model/precision chosen from detected VRAM)
CUDA unavailable / not usable  -->  CPU transcription (int8)
```

The engine doesn't just check "is there an NVIDIA GPU" — it verifies CUDA
is genuinely usable (a GPU can be present while the runtime libraries
`faster-whisper`/`ctranslate2` need are missing or broken) before deciding
GPU mode, and falls back to CPU automatically if GPU initialization fails
for any reason. Verified in this repository on an RTX 4060 (8GB VRAM,
`medium` model, fp16). The VRAM thresholds that pick a model size
(`engine/hardware/model_profiles.json`) are a starting point, not
benchmarked hard requirements — they're a plain data file so they can be
retuned without touching code.

## AI provider behavior

```
Primary provider:  Groq
Fallback provider: Gemini
```

Fallback happens **per request** (one analysis call, one notes-generation
call), not by switching the whole app to "Gemini mode." Beyond just
checking whether a key is present, the engine runs a real, free,
read-only connectivity probe against each configured provider (at startup,
and on demand via Settings' "Recheck" / `POST /ai/recheck`), so the UI can
show one of:

```
Not configured        no key set
Checking               probe in flight
Configured              key present and confirmed to work
Auth failed              key present, provider rejected it
Unavailable               key present, provider unreachable right now
Model not found            key works, but the configured model id doesn't exist for it
```

instead of collapsing every failure into a misleading "Not configured."
Model ids are read from config (`engine/storage/config.py`), not hardcoded
into the provider-calling code, specifically because provider catalogs
change — the connectivity probe checks the configured model against each
provider's live model list and reports `Model not found` distinctly if a
model gets deprecated, rather than only failing silently at the end of a
real meeting.

**Local transcription and recording never depend on any of this** — a
meeting records and transcribes identically whether both providers, one, or
neither is configured/reachable.

## Crash recovery

Transcription happens in ~25 second chunks. Each completed chunk is written
to disk (transcript text + JSON + metadata, via atomic writes) before the
next chunk starts recording. If the application or engine stops
unexpectedly, already-committed chunks are not lost — on the next launch,
the engine scans for meetings left in a non-terminal state and the UI
offers to resume them, continuing chunk numbering and timestamps from where
they left off. This has been verified by force-killing the engine
mid-recording and confirming a clean resume with no lost or duplicated
chunks. This guarantees chunks that finished writing before an interruption
survive it — it is not a claim that literally no data loss is possible
under every conceivable hardware failure (e.g. disk failure mid-write).

## Development

Prerequisites: Node 18+, Python 3.10, Rust (`rustup`), and Tauri's platform
build tools (Windows: MSVC Build Tools + WebView2, usually already present
on Windows 11; Linux: see [`docs/LINUX_TESTING.md`](docs/LINUX_TESTING.md)).

```bash
# Python engine
# We use the hardware-aware setup script to automatically provision the environment
# and install GPU dependencies only if an NVIDIA GPU is detected.
python setup.py
cd engine
cp .env.example .env                                # then fill in your keys

# Desktop app dependencies
cd ../desktop
npm install
```

Commands actually used by this project (from `desktop/`, matching
`package.json`, unless noted):

```bash
npm run dev              # Vite dev server only (used internally by `tauri dev`)
npm run build             # tsc && vite build — production frontend bundle
npm run tauri dev          # full dev app (Vite + Rust + window), hot reload
npm run tauri build         # full production build + installers (MSI/NSIS on Windows)
```

Python engine tests (from `engine/`, no GPU/microphone/API keys required):

```bash
.venv/Scripts/python -m pytest      # Windows
# .venv/bin/python -m pytest        # Linux/macOS
```

Rust/Tauri compile check without a full installer build:

```bash
cargo build --manifest-path desktop/src-tauri/Cargo.toml
```

## Running MeetNote

From the project root, the launcher starts the whole application — engine
and desktop UI together, in the right order, waiting for real readiness in
between:

```bash
python run_meetnote.py          # Windows/Linux/macOS
run_meetnote.bat                 # Windows, double-click or run directly
./run_meetnote.sh                # Linux/macOS (chmod +x run_meetnote.sh first if needed)
```

```
python run_meetnote.py                # auto: built app if present, else dev mode
python run_meetnote.py --dev          # force dev mode (hot reload) even if a build exists
python run_meetnote.py --prod         # force the built executable; errors if none exists
python run_meetnote.py --diagnostics  # environment/hardware/AI status report, no UI
```

Both wrapper scripts do nothing but call `run_meetnote.py` — all
orchestration logic (path resolution, environment validation, starting the
engine, waiting for `/health`, starting the desktop app, graceful shutdown,
bounded auto-restart if the engine dies unexpectedly) lives in that one
file. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full
lifecycle and troubleshooting notes.

A properly built desktop app is required for `run_meetnote.py`'s default/
`--prod` modes to find something to launch — build one with
`cd desktop && npm run tauri build` (or `--debug`). **Do not** rely on a
bare `cargo build` output as if it were the app: without going through the
Tauri CLI, the resulting binary is not reliably configured to load the
bundled frontend, which was the root cause of a real blank/unreachable
window bug found and fixed during development (see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)).

## Validation: what was actually tested

Distinguishing "implemented" from "tested" honestly:

- **`pytest`**: 30/30 passing — hardware/model-selection thresholds, the
  meeting state machine, simulated crash recovery, deterministic notes
  validation, AI provider fallback and connectivity-status logic.
- **`tsc --noEmit`** and **`npm run build`**: clean.
- **`cargo build`** / **`npm run tauri build`**: clean; a real debug
  installer (MSI/NSIS) has been produced successfully.
- **Real desktop app, driven live**: launched via `run_meetnote.py` on
  Windows with a real RTX 4060 and real Groq/Gemini keys — engine reaches
  genuine readiness (hardware detected, GPU/CUDA confirmed usable, Whisper
  loaded, both AI providers confirmed `Configured` via live connectivity
  probes), desktop app opens, and the full meeting flow was exercised
  end-to-end and inspected directly (via WebView2's CDP, not a simulation):
  Dashboard loads -> New Meeting -> template selection -> Start Meeting ->
  real meeting UI renders (live elapsed timer, transcript panel, memory
  panel, status bar) -> Mark Important -> Pause -> Resume -> Stop ->
  Completion screen -> graceful engine shutdown on app close. AI notes
  generation was verified against the live Groq API with a real transcript,
  producing correctly-structured decisions/action-items/deadlines and
  notes passing all deterministic validation checks.
- **Crash recovery**: verified by force-killing the engine mid-recording
  and confirming the recovery prompt and a clean resume with zero lost
  chunks.
- **Not tested**: Linux/macOS (no such machine was available during
  development — the code follows the same patterns as the Windows paths
  that were tested, but is unverified), a full release installer's
  end-user install experience, and multi-meeting/long-running-session
  stability beyond the sessions actually run.

## Current limitations

- **Linux/Ubuntu**: audio capture, hardware detection, and the launcher's
  Linux code paths are implemented but have not been run on real Linux —
  see [`docs/LINUX_TESTING.md`](docs/LINUX_TESTING.md) for the specific
  checklist before trusting it in production.
- **No release installer has been produced or tested** — only debug
  MSI/NSIS builds, which still expect `engine/.venv` to exist next to the
  source tree rather than being a self-contained distributable. Packaging
  the engine as a standalone sidecar (e.g. via PyInstaller) is not done.
- **Live meeting memory is a placeholder, honestly labeled as one.**
  Decisions/action items/deadlines/open questions are generated from the
  full transcript after the meeting ends (prioritizing accuracy over faking
  real-time analysis mid-conversation), not incrementally during the
  meeting — the UI says this explicitly.
- **No speaker diarization.** Transcripts are unattributed; the app never
  claims a speaker identity it hasn't actually determined.
- **Settings has some non-functional controls, labeled as such**: manual
  audio device selection, input/output gain, and storage retention exist in
  config but aren't wired to real behavior yet.
- Search, "Ask this meeting", cross-meeting memory, analytics, and a
  custom template builder are not implemented (later-phase features).
