# Build MeetNote: Cross-Platform Local Meeting Transcription and AI Notes Desktop App

You are building a production-quality desktop application called **MeetNote**.

MeetNote is a lightweight meeting assistant for **Windows 10/11 and Ubuntu Linux**. Its primary purpose is to capture meeting audio locally, transcribe it locally using `faster-whisper`, save transcription incrementally so nothing is lost during crashes, and after the meeting use an AI API to generate concise, accurate, natural meeting notes.

The application must be designed with a strong focus on reliability, automatic hardware/OS detection, excellent UX, modularity, and recovery from failures.

Do not build a simplistic demo. Build the architecture and UI so it can evolve into a polished real desktop product.

---

## 1. Core product requirement

The complete flow must be:

```text
Microphone + System Audio
        ↓
Local Audio Capture
        ↓
Automatic OS Detection
        ↓
Automatic Hardware Detection
        ↓
faster-whisper
   ┌───────────────┐
   │ NVIDIA CUDA   │ → GPU transcription
   │ No CUDA       │ → CPU transcription
   └───────────────┘
        ↓
20–30 second transcription chunks
        ↓
Immediate local persistence
        ↓
Complete meeting transcript
        ↓
Meeting ends
        ↓
Groq API
        ↓
If Groq fails → Gemini API
        ↓
Structured meeting analysis
        ↓
Final notes generation
        ↓
Quality validation
        ↓
TXT / Markdown / DOCX
```

Important:

- Meeting audio must remain local.
- Do not upload raw meeting audio to the cloud.
- Only transcript text and relevant meeting metadata should be sent to Groq/Gemini.
- Transcription must happen locally.
- The application must automatically use an NVIDIA GPU when a compatible CUDA environment is available.
- Otherwise it must automatically fall back to CPU.
- The user should not have to manually choose GPU vs CPU.
- The same application must work on Windows and Ubuntu Linux.
- OS-specific implementation should be isolated behind clean interfaces.

---

# 2. Technology direction

Use the following stack unless there is a strong technical reason to change it:

### Desktop

- **Tauri**
- **React**
- **Vite**
- TypeScript

The UI should feel like a native desktop application, not a website inside a window.

### Backend/native functionality

Use a clean native/service architecture suitable for:

- Windows
- Ubuntu Linux

Python may be used for the local speech transcription service because `faster-whisper` is the primary transcription engine.

Keep the Python transcription process isolated from the UI so that the frontend remains responsive.

### Speech-to-text

Use:

- `faster-whisper`
- CTranslate2
- NVIDIA CUDA when available
- CPU INT8 fallback when CUDA is unavailable

### AI

Primary:

- **Groq API**

Fallback:

- **Google Gemini API**

Use environment variables for credentials:

```text
GROQ_API_KEY=
GEMINI_API_KEY=
```

Never hard-code API keys.

### Local persistence

Use:

- SQLite for structured state
- TXT for human-readable transcript
- JSON for metadata/checkpoints
- Markdown/DOCX for generated notes

---

# 3. Automatic OS detection

The application must automatically detect:

- Windows
- Ubuntu/Linux

Do not expose OS selection to the user.

Use a clean abstraction:

```text
AudioCapture
├── WindowsAudioCapture
└── LinuxAudioCapture
```

The rest of the application must not need platform-specific logic.

Conceptually:

```python
audio_capture = AudioCaptureFactory.create()
```

The factory decides the correct implementation.

---

# 4. Audio capture

This is a critical component.

The application must capture:

1. Microphone audio
2. System/meeting audio

The two sources must be available simultaneously.

### Windows

Use a suitable WASAPI loopback implementation for system audio.

### Ubuntu Linux

Support modern PipeWire/PulseAudio environments.

The application should automatically discover:

- default microphone
- active/default output device
- system audio monitor source

Do not make users understand concepts such as "monitor source" or "loopback device."

The UI should simply show:

```text
Microphone    ✓ Connected
System Audio  ✓ Connected
```

Provide a manual device selector under Settings for advanced users, but automatic selection must be the default.

---

# 5. Audio processing

Audio should be processed in short chunks, approximately:

```text
20–30 seconds
```

Each completed chunk should be transcribed and immediately persisted.

Do not keep the entire meeting transcript only in memory.

The system should work like:

```text
Audio Chunk
    ↓
Whisper
    ↓
Transcript
    ↓
Write to disk
    ↓
Checkpoint
    ↓
Next chunk
```

A laptop crash after 20 minutes must not erase the previous 20 minutes of transcription.

---

# 6. Crash recovery

Crash recovery is a core feature, not an optional enhancement.

For every completed chunk, save:

- transcript text
- chunk number
- start timestamp
- end timestamp
- transcription status

Maintain metadata such as:

```json
{
  "meeting_id": "...",
  "started_at": "...",
  "last_completed_chunk": 42,
  "status": "recording",
  "transcription_mode": "gpu"
}
```

If the application restarts and detects an unfinished meeting:

```text
An unfinished meeting was found.

Resume previous meeting?
[ Resume ] [ Start New Meeting ]
```

The application must resume from the last successfully committed checkpoint.

If a crash occurs while processing one chunk, only that unfinished chunk may need to be reprocessed.

Never delete previously completed transcript data.

---

# 7. Local transcript structure

Each meeting should have its own directory.

Example:

```text
MeetNote/
└── meetings/
    └── 2026-08-27_1900_house-meeting/
        ├── metadata.json
        ├── transcript.txt
        ├── transcript.json
        ├── notes.md
        └── notes.docx
```

`transcript.txt` should be human readable.

Example:

```text
[00:00:00 - 00:00:27]
Speaker 1: ...

[00:00:27 - 00:00:54]
Speaker 2: ...
```

Do not claim speaker identities unless speaker diarization has actually identified them.

For V1, speaker labels can simply be:

```text
Speaker 1
Speaker 2
```

or omitted where reliable attribution is unavailable.

---

# 8. Automatic hardware detection

At startup, detect:

- CPU
- RAM
- NVIDIA GPU presence
- GPU VRAM
- CUDA availability
- whether the current Whisper/CTranslate2 installation can actually use CUDA

Do not simply check whether an NVIDIA GPU exists.

The decision should be based on whether GPU inference is genuinely usable.

Conceptually:

```text
Can CUDA be used?
    ↓
YES → GPU mode
NO  → CPU mode
```

Display the selected mode in the UI.

Example:

```text
RTX 4060
CUDA available
Whisper: GPU mode
Compute: FP16
```

or:

```text
NVIDIA GPU unavailable
Whisper: CPU mode
Compute: INT8
```

---

# 9. Automatic Whisper model selection

Do not force every machine to use the same model.

Create a hardware profiling layer.

Use hardware information such as:

- available RAM
- GPU VRAM
- CPU core count
- CUDA availability

Then select a suitable Whisper model/configuration.

The model selection logic should be centralized and configurable.

For example:

```text
High-end compatible NVIDIA GPU
→ larger/high-accuracy model

Mid-range NVIDIA GPU
→ medium/turbo configuration

CPU-only system
→ CPU-appropriate model
```

Do not blindly hard-code these thresholds before benchmarking.

Make them configurable so they can be tuned later.

---

# 10. Transcription quality

Prioritize:

1. Accuracy
2. Reliability
3. Reasonable latency
4. Resource efficiency

Do not sacrifice transcription accuracy merely to make the interface appear real-time.

A small transcription delay is acceptable.

The application should support timestamps and preserve the chronological order of transcript segments.

---

# 11. Meeting workflow

The application state machine should explicitly support:

```text
IDLE
PREPARING
RECORDING
PAUSED
RESUMED
FINALIZING
GENERATING_NOTES
COMPLETED
ERROR
RECOVERY
```

Avoid a large collection of loosely managed booleans.

Use explicit state transitions.

---

# 12. Meeting screen

The primary meeting UI should be minimal and calm.

Use a professional dark desktop-product aesthetic inspired by applications such as Linear, Raycast, and Notion.

Avoid:

- excessive gradients
- unnecessary animations
- cartoon-like elements
- excessive glassmorphism
- giant glowing AI effects
- emoji-heavy interface

The visual style should feel premium, serious, and productivity-focused.

### Layout

Use a two-column meeting interface.

Left:

**Live Transcript**

Right:

**Meeting Memory**

Example:

```text
┌──────────────────────────────────────────────────────┐
│ House Coordination Meeting              01:17:42     │
│                                        ● RECORDING   │
├─────────────────────────┬────────────────────────────┤
│                         │                            │
│ LIVE TRANSCRIPT         │ MEETING MEMORY             │
│                         │                            │
│ 19:42:12                │ DECISIONS                  │
│ Speaker 1               │ • Venue finalized          │
│ ...                     │                            │
│                         │ ACTION ITEMS               │
│ 19:42:35                │ • Divy → Budget            │
│ Speaker 2               │ • Rahul → Poster           │
│ ...                     │                            │
│                         │ DEADLINES                  │
│                         │ • Budget → Friday          │
│                         │                            │
│                         │ OPEN QUESTIONS             │
│                         │ • Volunteer count pending  │
├─────────────────────────┴────────────────────────────┤
│ GPU ✓  Whisper ✓  Saving ✓  Mic ✓  System Audio ✓  │
│                                                      │
│ [ Mark Important ]        [ Pause ]      [ Stop ]    │
└──────────────────────────────────────────────────────┘
```

---

# 13. Important markers

Provide:

```text
Mark Important
```

When clicked, save a timestamp.

Optional future marker types:

```text
Important
Decision
Action Item
Follow-up
```

For V1, implement at least `Mark Important`.

These timestamps should be passed to the analysis layer so the AI can pay additional attention to those sections.

---

# 14. Meeting memory

The application should not simply show a transcript.

It should maintain a structured meeting memory during or after transcription.

Track:

### Decisions

Things that were actually finalized.

### Action items

Tasks assigned to a person/team.

### Owners

Who is responsible.

### Deadlines

Dates or relative deadlines explicitly stated.

### Important points

Important discussion outcomes.

### Open questions

Things that remain unresolved.

The system must distinguish between:

```text
Proposal
Discussion
Decision
```

Do not turn a suggestion into a confirmed decision.

This is extremely important.

---

# 15. AI provider architecture

Do not hard-code Groq directly into the entire application.

Create a provider interface such as:

```text
LLMProvider
├── GroqProvider
└── GeminiProvider
```

The application should use:

```text
Primary: Groq
Fallback: Gemini
```

If a Groq request fails because of:

- timeout
- rate limit
- server error
- invalid response
- temporary network failure

then retry sensibly and fall back to Gemini.

Fallback should happen at the request level.

Do not switch the entire system unnecessarily.

Example:

```text
Chunk/analysis request 17
Groq → failed
Gemini → successful

Request 18
Groq → successful
```

---

# 16. API handling

Implement:

- timeout handling
- retry with exponential backoff
- structured error logging
- provider fallback
- rate-limit handling
- clear user-facing status

Never expose raw API errors directly as the main UI.

Instead:

```text
Groq temporarily unavailable.
Gemini fallback is being used.
```

---

# 17. Offline resilience

The meeting must continue working even if the internet connection disappears.

Because transcription is local:

```text
Internet lost
    ↓
Local transcription continues
    ↓
Transcript keeps saving
    ↓
Internet returns
    ↓
AI analysis resumes
```

If internet is unavailable when the meeting ends, show:

```text
Transcript saved locally.

AI analysis is pending because the internet connection is unavailable.

[ Retry Analysis ]
```

Do not lose the meeting.

---

# 18. Final AI analysis

After the meeting ends:

```text
Complete transcript
        +
Important timestamps
        +
Meeting metadata
        +
User-selected template
        ↓
Primary Groq
        ↓
Fallback Gemini if needed
        ↓
Structured meeting information
```

Do not repeatedly send the entire transcript unnecessarily.

Prefer an efficient final analysis pass for V1.

Architect the code so incremental meeting-memory processing can be added later.

---

# 19. Final notes generation

The generated meeting notes must be:

- concise
- precise
- natural
- human-like
- professional
- grammatically polished
- easy to scan
- faithful to the transcript

The output must not sound like generic AI prose.

The model must not invent:

- decisions
- people
- deadlines
- commitments
- facts
- motivations

The model must clearly distinguish uncertainty.

---

# 20. Strict writing rules for generated notes

This is a hard requirement.

Final meeting notes must:

- contain **no emojis**
- contain **no em dashes**
- contain no unnecessary decorative symbols
- avoid robotic language
- avoid unnecessary corporate jargon
- avoid filler phrases
- avoid repetitive summaries
- avoid phrases such as "Here is the summary"
- avoid phrases such as "In conclusion" unless genuinely necessary
- use normal human sentence structure
- preserve names, dates, responsibilities, decisions, and deadlines accurately

The writing should feel like a capable human secretary prepared the notes after attending the meeting.

Example of desired style:

```text
The team finalized the venue for the event. The graphics team will prepare the poster by Wednesday. The revised budget will be shared by Friday.
```

Not:

```text
Here is a concise AI-generated summary of the key takeaways and next steps from the productive discussion.
```

---

# 21. User-configurable note templates

Support customizable templates.

Default structure can include:

```text
Meeting Title
Date
Attendees
Agenda
Discussion
Decisions
Action Items
Deadlines
Next Steps
```

Do not hard-code the final output format into the AI service.

Represent templates as structured data so they can be changed later.

Example:

```json
{
  "name": "Standard Meeting Notes",
  "sections": [
    "Meeting Title",
    "Date",
    "Attendees",
    "Agenda",
    "Discussion",
    "Decisions",
    "Action Items",
    "Deadlines",
    "Next Steps"
  ]
}
```

---

# 22. Quality-control layer

After the AI generates the notes, perform a validation pass.

Check for:

```text
✓ Required sections present
✓ No emojis
✓ No em dashes
✓ Names preserved
✓ Dates preserved
✓ Deadlines preserved
✓ Action items included
✓ No obvious unsupported claims
✓ Template structure respected
✓ Concise output
```

Do not rely only on the LLM's own prompt.

Implement deterministic checks in code where possible.

If the output fails basic validation, automatically run a cleanup/rewrite pass.

---

# 23. Completion screen

After processing:

```text
Meeting Complete

House Coordination Meeting
1h 42m

Transcript
✓ Saved locally

AI Analysis
✓ Completed

Notes
✓ Generated

[ Open Notes ]
[ Export DOCX ]
[ Copy ]
[ Open Transcript ]
[ Done ]
```

Show which AI provider was used:

```text
Analysis Provider: Groq
```

or:

```text
Analysis Provider: Gemini fallback
```

---

# 24. Export formats

Implement:

- TXT
- Markdown
- DOCX

DOCX should preserve the configured meeting-note template as closely as possible.

PDF can be added later.

---

# 25. Settings

Create a Settings screen with sections:

### General

- Application startup behavior
- Default meeting template
- Transcript storage location

### Audio

- Microphone
- System audio
- Input level
- Output/system audio level

### Transcription

Show detected information:

```text
Operating System
CPU
RAM
GPU
VRAM
CUDA
Whisper Model
Compute Type
Current Mode
```

Allow advanced users to override automatic settings, but automatic detection remains the default.

### AI

```text
Groq API Key
Gemini API Key
Primary Provider: Groq
Fallback Provider: Gemini
```

Never display complete API keys.

### Storage

- Open meetings directory
- Retention options
- Clear cache
- Remove temporary files

---

# 26. System health panel

At startup and before recording, run a health check.

Check:

```text
Operating System       ✓
Microphone             ✓
System Audio           ✓
Whisper                ✓
GPU/CUDA               ✓/N/A
Local Storage          ✓
Groq API               ✓/Unavailable
Gemini API             ✓/Unavailable
```

The application should still allow recording if Groq/Gemini are unavailable, because transcription is local.

---

# 27. Logging

Implement structured logs.

Keep logs separate from meeting transcript data.

Include:

- application errors
- device detection
- transcription failures
- model loading
- API errors
- fallback events
- crash recovery
- performance metrics

Do not log API keys or sensitive transcript contents unnecessarily.

---

# 28. Performance requirements

The UI must remain responsive while:

- audio is being captured
- Whisper is transcribing
- files are being written
- AI requests are running

Never run heavy transcription operations directly on the UI thread.

Use asynchronous/background worker architecture.

Memory use should remain bounded during long meetings.

Do not continuously keep the entire raw audio stream in RAM.

---

# 29. Meeting lifecycle

Implement the following flow:

```text
Launch application
    ↓
Run automatic health check
    ↓
Show Ready state
    ↓
User clicks Start Meeting
    ↓
Create meeting directory
    ↓
Initialize audio capture
    ↓
Detect hardware
    ↓
Load Whisper
    ↓
Begin chunk capture
    ↓
Transcribe each chunk
    ↓
Immediately save transcript
    ↓
Update meeting UI
    ↓
Repeat until Stop
    ↓
Finalize remaining audio
    ↓
Validate transcript
    ↓
Send transcript to Groq
    ↓
Fallback to Gemini if necessary
    ↓
Generate structured meeting information
    ↓
Generate final notes
    ↓
Run quality validation
    ↓
Save notes
    ↓
Show completion screen
```

---

# 30. Error handling

Do not let one failure kill the meeting.

Examples:

### Whisper chunk fails

Retry the chunk.

If still unsuccessful:

```text
Mark chunk as pending
Continue recording
```

### Microphone disconnects

Show:

```text
Microphone disconnected.
System audio is still being captured.
```

Attempt automatic reconnection.

### System audio disconnects

Attempt to rediscover the default output source.

### GPU fails

Automatically switch from GPU to CPU where possible.

### Groq fails

Use Gemini.

### Both AI APIs fail

Save transcript and show:

```text
Transcript saved.
AI notes are pending.
```

Allow retry later.

---

# 31. Automatic GPU-to-CPU fallback

This is different from API fallback and must be implemented separately.

If GPU initialization fails:

```text
GPU initialization failed
        ↓
Log reason
        ↓
Automatically switch to CPU
        ↓
Continue transcription
```

The meeting must not be lost merely because CUDA failed.

The UI should show:

```text
Transcription switched to CPU mode.
```

rather than crashing.

---

# 32. Automatic device reconfiguration

If a user changes headphones or microphone during a meeting:

- detect the device change
- attempt to maintain the meeting
- reconnect to the appropriate source
- do not restart transcription unnecessarily

Design the audio capture service to support device refresh/recovery.

---

# 33. UI design language

Create a polished dark-first interface.

Use:

- clean typography
- generous spacing
- restrained use of accent color
- subtle borders
- rounded cards
- clear status indicators
- smooth but minimal animations

Do not use emojis as UI icons.

Use an icon library such as Lucide where appropriate.

The visual hierarchy should prioritize:

1. Recording state
2. Transcript
3. Meeting memory
4. System health
5. Controls

The application should feel trustworthy.

---

# 34. Navigation

Suggested top-level navigation:

```text
Meetings
New Meeting
Templates
Settings
```

Dashboard should show recent meetings.

Each meeting should display:

```text
Title
Date
Duration
Transcript status
Notes status
AI provider used
```

---

# 35. Dashboard

Example:

```text
MeetNote

[ Start New Meeting ]

Recent Meetings

House Coordination Meeting
Aug 27, 2026
1h 42m

Event Planning Meeting
Aug 25, 2026
58m

Graphics Review
Aug 23, 2026
1h 12m
```

Keep it simple.

---

# 36. Security basics

Even though this application is intended to send transcript data to cloud AI providers:

- keep API keys outside source code
- store secrets securely where practical
- do not send raw audio to cloud AI providers
- do not log API keys
- do not accidentally expose transcript files through a web server
- sanitize file paths
- validate external API responses
- restrict local IPC appropriately

---

# 37. Code architecture

Use clean separation of concerns.

Suggested structure:

```text
meetnote/
│
├── desktop/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── stores/
│   │   ├── services/
│   │   └── types/
│   │
│   └── src-tauri/
│
├── transcription/
│   ├── engine/
│   ├── hardware/
│   ├── audio/
│   └── recovery/
│
├── intelligence/
│   ├── providers/
│   │   ├── groq/
│   │   └── gemini/
│   ├── prompts/
│   ├── analysis/
│   └── validation/
│
├── storage/
│   ├── sqlite/
│   ├── transcript/
│   └── files/
│
└── docs/
```

Keep provider-specific code isolated.

Keep OS-specific code isolated.

Keep UI independent from transcription implementation details.

---

# 38. Important implementation principle

Do not make this a giant monolithic Python script.

Use independent services/modules for:

```text
Audio Capture
Hardware Detection
Transcription
Persistence
Meeting State
AI Provider
Prompt Management
Validation
Export
UI
```

Each part should have clear interfaces.

---

# 39. MVP priority

Implement in this order:

### Phase 1

- Tauri + React + Vite shell
- Windows/Linux detection
- audio-device detection
- microphone capture
- system-audio capture
- hardware detection
- CUDA detection
- faster-whisper
- automatic GPU/CPU mode
- chunk transcription
- immediate TXT/JSON persistence
- crash recovery

### Phase 2

- Groq integration
- Gemini fallback
- final notes generation
- quality validation
- Markdown/DOCX export

### Phase 3

- polished meeting UI
- live transcript
- meeting memory
- important markers
- dashboard
- settings

### Phase 4

Add advanced capabilities only after the core system is stable:

- speaker diarization
- search
- Ask This Meeting
- action-item tracking
- cross-meeting memory
- analytics
- custom template builder

Do not overcomplicate Phase 1.

---

# 40. Development expectations

Before implementing a feature, consider:

- crash recovery
- long-running stability
- CPU/GPU resource usage
- Windows/Linux compatibility
- graceful failure
- user experience
- maintainability

Do not claim a feature works without testing it.

Whenever platform-specific behavior is uncertain, implement detection and graceful fallback rather than assuming a device or dependency exists.

Create useful comments for non-obvious platform-specific logic.

---

# 41. Final product principle

The application should behave as though the user does not know anything about the underlying technologies.

The user should not need to understand:

- CUDA
- Whisper
- CTranslate2
- PipeWire
- PulseAudio
- WASAPI
- GPU memory
- model selection
- API fallback

The application should automatically make the correct decision.

The ideal user experience is:

```text
Open MeetNote
      ↓
System automatically checks everything
      ↓
"Ready"
      ↓
Start Meeting
      ↓
Attend the meeting normally
      ↓
Stop Meeting
      ↓
Receive polished meeting notes
```

The application should feel lightweight during the meeting and intelligent afterward.

---

# 42. Build quality bar

Do not stop at a visually attractive mockup.

The implementation must have:

- real audio capture
- real local transcription
- real GPU/CPU switching
- real persistence
- real crash recovery
- real Groq integration
- real Gemini fallback
- real notes generation
- real DOCX export
- functional Windows/Linux abstractions
- sensible error handling

Start by inspecting the repository and existing files. Reuse suitable existing infrastructure where possible.

Before making major architectural changes, understand the current project structure.

Build incrementally and keep the application runnable after each major phase.

At the end, provide:

1. What was implemented
2. Architecture summary
3. Files changed/created
4. How to run on Windows
5. How to run on Ubuntu
6. Required environment variables
7. GPU/CUDA setup requirements
8. Known limitations
9. Testing performed

Do not leave placeholder buttons that appear functional but do nothing. If something is intentionally deferred, make that explicit in the UI and implementation notes.