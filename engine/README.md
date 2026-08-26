# MeetNote Engine

Local Python service (FastAPI + WebSocket, `127.0.0.1` only) that does all
the real work: audio capture, hardware detection, `faster-whisper`
transcription, crash-safe persistence, and the Groq/Gemini AI notes
pipeline. See [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) for the
module map.

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\pip install -r requirements.txt
# Linux/macOS:
.venv/bin/pip install -r requirements.txt

cp .env.example .env   # then fill in GROQ_API_KEY / GEMINI_API_KEY (optional)
```

The Tauri app expects the venv at exactly `engine/.venv` and launches
`engine/main.py` from it automatically — see `desktop/src-tauri/src/lib.rs`.

## Run standalone (without the desktop app)

```bash
# Windows
.venv\Scripts\python main.py --port 8765
# Linux/macOS
.venv/bin/python main.py --port 8765
```

Then `curl http://127.0.0.1:8765/health`.

## Tests

```bash
.venv/Scripts/python -m pytest   # or .venv/bin/python on Linux/macOS
```

30 tests covering model-selection thresholds, the state machine, crash
recovery (simulated), deterministic notes validation, and AI provider
fallback/connectivity-status handling — see `tests/`. These don't need a
GPU, microphone, or API keys.

## GPU note (Windows)

If GPU transcription fails with `Could not locate cudnn_ops64_9.dll`, make
sure `pip install -r requirements.txt` fully completed — it includes
`nvidia-cudnn-cu12`/`nvidia-cublas-cu12`, which `cuda_env.py` needs on disk
to register. See ARCHITECTURE.md's "GPU/CUDA notes" for why this is needed
at all.
