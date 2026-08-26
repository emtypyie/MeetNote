# Linux Verification Checklist

The Linux audio path (`engine/audio/linux.py`) was written against the same
`AudioCapture` interface as Windows and follows the documented behavior of
the `soundcard` library on PulseAudio / PipeWire-Pulse, but **no Linux
machine was available during development, so it has not actually been
run.** Everything else (hardware detection, Whisper/CPU transcription,
persistence, crash recovery, the AI pipeline, the whole frontend) is
platform-agnostic Python/TypeScript and should work identically — audio
capture is the one piece with real OS-specific system calls underneath it.

Before trusting this in production on Ubuntu, run through:

## Setup

```bash
sudo apt-get install python3-venv portaudio19-dev pulseaudio-utils
cd engine
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys if testing AI notes
python main.py --port 8765
```

No `nvidia-cudnn-cu12`/`cuda_env.py` DLL dance is needed on Linux — CUDA
shared libraries are found normally there. If you have an NVIDIA GPU,
`curl localhost:8765/health` should report `cuda_usable: true`; if not,
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
   (`libwebkit2gtk-4.1-dev`, `libappindicator3-dev`, `librsvg2-dev`,
   `patchelf` — see https://tauri.app/start/prerequisites/#linux) and
   confirm `npx tauri dev` / `npx tauri build` succeed; this session only
   built the Windows target.

If any of these fail, the fix almost certainly belongs in
`audio/soundcard_common.py` or `audio/linux.py` — the rest of the engine
should not need OS-specific changes.
