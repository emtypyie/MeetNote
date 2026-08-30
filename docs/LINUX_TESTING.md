# Linux Verification Checklist

The Linux audio path (`engine/audio/linux.py`) was written against the same
`AudioCapture` interface as Windows and follows the documented behavior of
the `soundcard` library on PulseAudio / PipeWire-Pulse, but **no Linux
machine or VM has been available in any development session so far, so it
has not actually been run against real hardware.** Everything else
(hardware detection, Whisper/CPU transcription, persistence, crash
recovery, the AI pipeline, the whole frontend) is platform-agnostic
Python/TypeScript and should work identically — audio capture is the one
piece with real OS-specific system calls underneath it.

`engine/audio/health.py`'s background probe (used for the System Health
panel) resolves devices through the exact same `AudioCapture` class real
recording uses, including `LinuxAudioCapture`'s pactl fallback — this was
verified with unit tests against a fake `soundcard` module (see
`engine/tests/test_audio_health.py`), which is not a substitute for #5
below on real hardware.

Before trusting this in production on Ubuntu, run through:

## Setup

The canonical way to set this up is `python3 setup.py` from the project
root (see the README) — it creates the venv, installs the right
requirements files, and writes `engine/.env` for you. To run the engine
directly without the launcher, for probing a specific issue:

```bash
sudo apt-get install python3-venv pulseaudio-utils
cd engine
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-base.txt -r requirements-cpu.txt   # or requirements-gpu.txt on an NVIDIA machine
cp .env.example .env   # fill in keys if testing AI notes
python main.py --port 28765
```

Note: `soundcard` talks to PulseAudio/PipeWire-Pulse directly via `ctypes`
bindings to `libpulse` (already present on any desktop with audio working
at all) — it does not use PortAudio, so no PortAudio development package is
needed.

No `nvidia-cudnn-cu12`/`cuda_env.py` DLL dance is needed on Linux — CUDA
shared libraries are found normally there. If you have an NVIDIA GPU,
`curl localhost:28765/health` should report `cuda_usable: true`; if not,
confirm it correctly falls back to CPU mode rather than erroring.

## Things to actually verify

1. **`GET /health`** reports `microphone_ok: true` and `system_audio_ok:
   true` with real device names — confirms `soundcard.default_microphone()`
   and the loopback-monitor resolution both work on your PipeWire/Pulse
   setup.
2. **Start a real meeting**, speak into the mic, play some audio through
   speakers/headphones at the same time, and confirm both are picked up
   (check `transcript.json` chunk `mic_present`/`system_audio_present`
   flags and that the transcribed text reflects both sources).
3. **Kill `-9` the engine process mid-meeting**, restart it, confirm
   `GET /meetings/unfinished` finds it and `resume-after-restart` continues
   cleanly — the crash-recovery logic itself is OS-agnostic, but this
   exercises the Linux capture teardown/re-init path.
4. **Unplug/switch the default audio device mid-meeting** and confirm the
   capture thread's reconnect-with-backoff logic (`soundcard_common.py`)
   recovers rather than silently going dead.
5. **If `soundcard` fails to find a monitor source** (some minimal PipeWire
   configs don't advertise one until requested), confirm the `pactl`
   fallback in `audio/linux.py` actually kicks in — check
   `engine/logs/engine.log` for the "attempting pactl monitor-source
   fallback" warning, and verify `pactl get-default-sink` /
   `pactl list short sources` behave as the fallback code assumes.
6. **Tauri build on Linux**: install the Tauri Linux prerequisites
   (`libwebkit2gtk-4.1-dev`, `libgtk-3-dev`, `libayatana-appindicator3-dev`,
   `librsvg2-dev` — see https://tauri.app/start/prerequisites/#linux) and
   confirm `python setup.py` (or `npm run tauri build`) succeeds; no session
   so far has built anything but the Windows target.
7. **"Copy Summary" and "Copy" (dashboard) use the OS clipboard correctly**:
   click both, then paste into another application (a terminal, a text
   editor). Both go through Tauri's `clipboard-manager` plugin rather than
   the browser `navigator.clipboard` API specifically because WebKitGTK
   (Linux's webview) has been known to handle the browser API's permission
   model differently than WebView2 (Windows) — this is exactly the kind of
   thing that can silently work on Windows and silently fail on Linux.
8. **"Open Notes" and both "Open" buttons (transcript storage location,
   meetings directory)** open the expected file/folder in your default
   file manager or text editor via `xdg-open` — confirm the correct
   application actually opens (whatever `xdg-mime` has configured as the
   default for plain text / directories on your desktop environment), not
   just that no error was shown.

If any of these fail, the fix almost certainly belongs in
`audio/soundcard_common.py` or `audio/linux.py` — the rest of the engine
should not need OS-specific changes.
