# MeetNote

MeetNote is a desktop meeting assistant that records your meeting audio, transcribes it locally, and generates structured meeting notes using AI.

Transcription runs entirely on your machine, so your raw audio never leaves your device. After the meeting, only the transcript text is sent to an AI provider of your choice to generate the final notes.

## What MeetNote Does

- Records microphone and system (speaker/output) audio at the same time
- Transcribes speech locally using faster-whisper (no audio sent to any server)
- Detects the spoken language automatically and translates non-English speech into English
- Uses your NVIDIA GPU when available, or runs on CPU
- Generates meeting notes with Gemini and/or Groq
- Saves meetings locally with crash-safe transcript persistence and recovery after a restart
- Lets you copy the summary, open the notes file, and delete meetings you no longer need

## Requirements

- Python 3.10-3.12 (3.13+ is not currently supported)
- Node.js 18+ and npm
- Rust and Cargo (for building the desktop app)
- An NVIDIA GPU is optional but speeds up transcription

**Windows**: no extra system packages are needed.

**Ubuntu/Linux (22.04+)**: install the Tauri and audio system packages before running setup:

```bash
sudo apt update && sudo apt install -y \
    libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev \
    librsvg2-dev build-essential curl wget file libssl-dev \
    pulseaudio-utils
```

MeetNote uses your system's PulseAudio or PipeWire (via its PulseAudio compatibility layer) for microphone and system-audio capture, so one of the two needs to be running, which is the default on Ubuntu 22.04 and 24.04.

## Setup

```bash
git clone <repository-url>
cd MeetNote
python setup.py
```

`setup.py` prepares everything: it creates the Python environment, installs the correct CPU or GPU dependencies for your hardware, installs frontend dependencies, builds the desktop application, asks for your optional Gemini/Groq API keys, and writes `engine/.env` for you. You do not need to create or edit `.env` by hand.

Re-run `python setup.py` any time to update MeetNote after pulling new changes; it will not overwrite your existing settings or API keys.

## Run

```bash
python run_meetnote.py
```

On Windows you can also double-click `run_meetnote.bat`. On Linux you can also run `./run_meetnote.sh`. Both are thin wrappers around `run_meetnote.py`, which starts the engine, waits until it is ready, then opens the desktop application, and shuts everything down cleanly when you close the window.

## AI Providers

- Gemini only: notes are generated with Gemini
- Groq only: notes are generated with Groq
- Both configured: Gemini is used first, Groq is used automatically if a request to Gemini fails
- Neither configured: recording, transcription, and local storage still work; AI notes are simply unavailable until a key is added

Get a free API key from [Google AI Studio](https://aistudio.google.com/app/apikey) (Gemini) or the [Groq Console](https://console.groq.com/keys) (Groq).

## CPU / GPU

- **Automatic**: uses your NVIDIA GPU if one is usable, otherwise CPU
- **NVIDIA GPU**: requires a usable GPU; does not silently fall back to CPU
- **CPU only**: always runs on CPU, even if a GPU is present

Changing the hardware mode in Settings requires restarting MeetNote for it to take effect.

## Language

English speech is transcribed as English. Speech in other supported languages is translated into English before it reaches the transcript, so meeting notes are always generated from an English transcript regardless of the language spoken.

## Data and Privacy

- Recordings, transcripts, and notes stay on your machine, under `~/MeetNote/` by default (configurable in Settings)
- API keys live only in `engine/.env` on your machine and are never committed to Git
- Meeting data, logs, and the local database are excluded from Git by `.gitignore`
- Deleting a meeting removes all of its local data

## Troubleshooting

**Setup failed**: re-read the error printed by `setup.py`; it names the specific missing tool (Python, Node, Rust, or a Linux system package) and how to install it.

**Python version issue**: MeetNote needs Python 3.10, 3.11, or 3.12. `setup.py` looks for a compatible interpreter automatically; if none is found, install one from [python.org](https://www.python.org/) (Windows) or your distribution's package manager (Linux).

**Engine won't start**: check `logs/engine.log` and `logs/launcher.log` in the project root. A common cause is another process already using port 28765; close it and try again.

**Audio unavailable**: on Windows, check your microphone/output permissions and default devices. On Linux, confirm PulseAudio or PipeWire is running and that `pulseaudio-utils` is installed; MeetNote needs a working default microphone and a monitor/loopback source for the default output device.

**AI provider unavailable**: run `python setup.py` again to add or update a Gemini/Groq API key; recording and transcription work without one.

**Linux audio dependency issue**: if system-audio capture fails to find a loopback/monitor device, install `pulseaudio-utils` and confirm `pactl get-default-sink` returns a value; see `docs/LINUX_TESTING.md` for details.

## Development

```bash
cd engine && .venv/Scripts/python -m pytest   # backend tests (Windows)
cd engine && .venv/bin/python -m pytest       # backend tests (Linux/macOS)

cd desktop && npm run build                   # build the frontend
cd desktop && npm run tauri build             # build the desktop application
```

See `docs/TECH_STACK.md` for an overview of the technology and architecture, and `docs/ARCHITECTURE.md` for deeper implementation notes.

## Known Limitations

- Speaker diarization is not implemented
- Some advanced settings (manual device selection, input/output gain, storage retention) are shown in Settings but not yet wired into behavior
- Packaging a distributable installer (rather than running from source) is not implemented yet

## Project Structure

```text
MeetNote/
├── desktop/          Tauri + React desktop application
├── docs/             Technical documentation
├── engine/           Python backend (FastAPI, audio, transcription, AI, storage)
├── setup.py          One-time setup and dependency installation
├── run_meetnote.py   Starts the engine and desktop app together
├── run_meetnote.bat  Windows convenience wrapper
├── run_meetnote.sh   Linux/macOS convenience wrapper
└── README.md
```

## Contributing

Bug reports, improvements, and pull requests are welcome. Please keep API keys, meeting data, logs, and generated runtime files out of commits.
