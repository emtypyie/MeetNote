# MeetNote

MeetNote is a desktop meeting assistant that privately captures your meeting audio, transcribes it locally, and generates structured meeting notes using AI. 

Transcription happens entirely locally on your device, ensuring your raw meeting audio never leaves your machine. After the meeting, only the transcript text is sent to an AI provider of your choice to generate the final notes.

## Features

- Local speech transcription using faster-whisper
- Microphone audio capture
- System audio capture
- Automatic language detection
- Translation of supported non-English speech into English
- Automatic transcription hardware selection
- NVIDIA GPU transcription
- CPU-only transcription
- Restart-required hardware switching
- Crash-safe transcript persistence
- Gemini AI meeting notes
- Groq AI meeting notes
- Gemini-only provider configuration
- Groq-only provider configuration
- Gemini primary with Groq fallback when both are configured
- Copy Summary
- Open Notes
- Meeting history
- Meeting deletion
- Automatic .env creation through setup.py
- Interactive API-key configuration through setup.py

## Privacy

Meeting audio is processed locally, and transcription is performed entirely on your machine. Meeting data is stored locally. Only the transcript text required for AI note generation is sent to the configured AI provider. Runtime and user meeting data is excluded from Git.

## Requirements

- Python 3.10+
- Node.js 18+
- Rust and Tauri platform build tools
- Supported operating systems: Windows (Linux support is experimental)
- NVIDIA GPU is optional but recommended

## Setup

The canonical setup command is:

```bash
python setup.py
```

This script prepares the environment, detects available hardware, installs appropriate CPU/GPU dependencies, creates `engine/.env` automatically, and asks for missing AI provider keys.

## AI Provider Setup

MeetNote supports Gemini and Groq for generating notes. The supported configurations are:

- Gemini only -> Gemini
- Groq only -> Groq
- Both -> Gemini primary, Groq fallback
- Neither -> local recording and transcription still work, but AI notes are unavailable

At least one provider key is needed for AI-generated notes. The `setup.py` script asks for the missing API keys interactively. Existing configured keys will not be requested again.

### Getting API Keys

If you don't have API keys yet, you can get them for free:
- **Gemini**: Go to [Google AI Studio](https://aistudio.google.com/app/apikey), sign in with your Google account, and click "Create API key".
- **Groq**: Go to the [Groq Console](https://console.groq.com/keys), sign in, and click "Create API Key".

## Running MeetNote

The root launchers start the MeetNote engine and desktop application together. 

**Windows**:
```cmd
python run_meetnote.py
```
or:
```cmd
run_meetnote.bat
```

**Linux**:
```bash
python3 run_meetnote.py
```
or:
```bash
./run_meetnote.sh
```

## Hardware

MeetNote supports different hardware modes for local transcription:

- **Automatic**: Uses the best supported transcription hardware available on the system.
- **NVIDIA GPU**: Uses NVIDIA/CUDA acceleration when available.
- **CPU only**: Forces transcription to run on the CPU, even if an NVIDIA GPU is available.

Changing the transcription hardware requires restarting MeetNote.

## Language and Translation

English speech is transcribed as English. Supported non-English speech can be translated into English locally. The English transcript is then used for AI meeting notes.

## Local Data

Meeting-related data is stored locally (typically in `~/MeetNote/`). 

This includes transcripts, summaries, meeting metadata, recordings, runtime data, and logs. User and runtime data is intentionally excluded from Git. Deleting a meeting removes its associated local meeting data.

## Troubleshooting

### 'npm' is not recognized as an internal or external command
This means Node.js is not installed on your system. `npm` (Node Package Manager) is required to run the frontend portion of MeetNote. To fix this, download and install Node.js from [nodejs.org](https://nodejs.org/). Make sure to keep the option to "Add to PATH" checked during installation.

### MeetNote does not start
Run `python setup.py` and then try the canonical launcher again.

### AI notes are unavailable
Make sure at least one AI provider API key is configured. Run `python setup.py` again if required.

### NVIDIA GPU is not being used
Check whether the system has a supported NVIDIA GPU, check the selected MeetNote hardware mode, make sure required GPU dependencies are installed, and check whether MeetNote needs to be restarted.

### Microphone or system audio is unavailable
Check OS audio permissions and whether the expected microphone/output device is available.

### Hardware setting is not taking effect
Restart MeetNote when the application shows that a restart is required.

## Debugging

Logs can be useful when reporting problems. Runtime logs are stored in the `logs/` directory inside the project root.

## Development

For development, use the following commands:

To build the frontend:
```bash
cd desktop
npm install
npm run build
```

To run the backend test suite:
```bash
cd engine
.venv/Scripts/python -m pytest
```

To build the Tauri desktop application:
```bash
cd desktop
npm run tauri build
```

## Known Limitations

- Linux support may require additional platform-specific validation.
- Speaker diarization is not currently implemented.
- Some advanced settings may not yet be configurable.

## Project Structure

```text
MeetNote/
├── desktop/
├── docs/
├── engine/
├── setup.py
├── run_meetnote.py
├── run_meetnote.bat
├── run_meetnote.sh
├── .gitignore
└── README.md
```

## Contributing

Bug reports, improvements, and pull requests are welcome. Please keep API keys, meeting data, logs, and generated runtime files out of commits.
