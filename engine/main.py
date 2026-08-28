"""MeetNote engine entrypoint.

A local-only (127.0.0.1) FastAPI + WebSocket service that the Tauri shell
spawns as a child process. Owns everything product-relevant: hardware
detection, audio capture, transcription, persistence/crash-recovery, and
the AI notes pipeline. The desktop UI is a thin client of this service —
see desktop/src/services/engineClient.ts.

Run directly for local development:
    engine/.venv/Scripts/python engine/main.py --port 28765
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cuda_env import configure_cuda_dll_search_path

configure_cuda_dll_search_path()  # must run before any GPU-touching import below

from ai_pipeline import run_ai_pipeline
from audio.factory import AudioCaptureFactory, UnsupportedPlatformError
from audio.health import probe_devices
from hardware.detector import detect_hardware
from hardware.model_selector import select_transcription_mode
from intelligence import templates as templates_module
from intelligence.providers.gemini_provider import GeminiProvider
from intelligence.providers.groq_provider import GroqProvider
from intelligence.router import AIRouter
from logging_setup import setup_logging
from os_detect import os_display_name
from recovery.checkpoint import scan_for_unfinished
from session import MeetingSession
from state.machine import MeetingState
from storage import db
from storage.config import load_config, save_config
from storage.meeting_store import MeetingStore
from storage.paths import ensure_dirs, meetings_root, set_storage_root, storage_root

logger = logging.getLogger("meetnote.main")

load_dotenv(Path(__file__).parent / ".env")


# ---------------------------------------------------------------------------
# Engine-wide state
# ---------------------------------------------------------------------------


class WSHub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def broadcast(self, message: dict) -> None:
        """Safe to call from any thread."""
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(message), self.loop)

    async def _broadcast(self, message: dict) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


class EngineState:
    def __init__(self):
        self.config: dict = {}
        self.hardware_profile = None
        self.mode_decision = None
        self.transcriber = None
        self.whisper_loading = True
        self.whisper_load_error: Optional[str] = None
        self.ai_router: Optional[AIRouter] = None
        self.active_session: Optional[MeetingSession] = None
        self.unfinished_on_startup: list[dict] = []
        self.ws_hub = WSHub()
        self.session_lock = threading.Lock()
        self.active_hardware_preference: str = "automatic"

    def broadcast(self, message: dict) -> None:
        self.ws_hub.broadcast(message)


engine_state = EngineState()


whisper_load_lock = threading.Lock()

def _load_whisper_in_background():
    with whisper_load_lock:
        if engine_state.transcriber is not None or engine_state.mode_decision.device == "error":
            engine_state.whisper_loading = False
            return
            
        from transcription.whisper_engine import WhisperTranscriber

        try:
            transcriber = WhisperTranscriber(
                engine_state.mode_decision.model_size,
                engine_state.mode_decision.device,
                engine_state.mode_decision.compute_type,
            )
            transcriber.load()
            engine_state.transcriber = transcriber
        except Exception as exc:  # even CPU load failed — transcription is unavailable
            logger.exception("Fatal: could not load Whisper model on GPU or CPU")
            engine_state.whisper_load_error = str(exc)
        finally:
            engine_state.whisper_loading = False





@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("MeetNote engine starting up")

    engine_state.config = load_config()
    if engine_state.config.get("storage_root"):
        set_storage_root(Path(engine_state.config["storage_root"]))
    else:
        ensure_dirs()

    db.init_db()
    engine_state.unfinished_on_startup = scan_for_unfinished()

    hardware_mode = engine_state.config.get("transcription", {}).get("hardware_mode", "automatic")
    engine_state.active_hardware_preference = hardware_mode
    engine_state.hardware_profile = detect_hardware(skip_cuda_check=(hardware_mode == "cpu"))
    engine_state.mode_decision = select_transcription_mode(
        engine_state.hardware_profile, user_preference=hardware_mode
    )
    logger.info(
        "Hardware: %s | Transcription mode: %s (%s)",
        engine_state.hardware_profile.to_dict(),
        engine_state.mode_decision.to_dict(),
        engine_state.mode_decision.reason,
    )

    if engine_state.mode_decision.device == "error":
        engine_state.whisper_load_error = engine_state.mode_decision.reason
        engine_state.whisper_loading = False
    else:
        threading.Thread(target=_load_whisper_in_background, daemon=True, name="whisper-load").start()

    ai_cfg = engine_state.config["ai"]
    engine_state.ai_router = AIRouter(
        gemini=GeminiProvider(model=ai_cfg.get("gemini_model", "gemini-1.5-flash-latest")),
        groq=GroqProvider(model=ai_cfg.get("groq_model", "llama3-8b-8192")),
    )
    # A live connectivity check (not just "is a key present") runs in the
    # background so a wrong/expired key surfaces as such in the UI instead
    # of a misleading "Not configured" — see intelligence/router.py and
    # providers/*.py's _probe_connection. Backgrounded, and every layer of
    # it catches its own exceptions, so a network hiccup here can never
    # delay startup or take the engine down (spec: a missing/invalid AI API
    # must not terminate MeetNote).
    threading.Thread(
        target=engine_state.ai_router.refresh_connectivity,
        daemon=True,
        name="ai-connectivity-check",
    ).start()

    engine_state.ws_hub.bind_loop(asyncio.get_running_loop())

    yield

    logger.info("MeetNote engine shutting down")
    if engine_state.active_session is not None:
        try:
            engine_state.active_session.audio_capture.stop()
        except Exception:
            logger.exception("Error stopping audio capture during shutdown")


app = FastAPI(title="MeetNote Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Local-only server (bound to 127.0.0.1) talking only to this app's own
    # Tauri webview, whose origin differs by platform/dev-vs-build. Verified
    # directly against a real built app via WebView2's CDP: on Windows the
    # bundled app's actual origin is "http://tauri.localhost" (http, not
    # https) — a mismatch here doesn't throw anywhere visible, it just makes
    # every fetch() silently fail, which from the UI looks like "the engine
    # health checks the app to a permanent stuck disabled state (e.g.
    # "Start Meeting" never enables) rather than a loud error. A regex
    # covers the dev-server origin plus every tauri.localhost variant
    # (scheme, platform) instead of enumerating and hoping.
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1):1420|tauri://localhost|https?://tauri\.localhost)$",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_session() -> MeetingSession:
    if engine_state.active_session is None:
        raise HTTPException(404, "No meeting is currently active")
    return engine_state.active_session


def _storage_health() -> dict:
    try:
        probe = storage_root() / ".health_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    device_probe = probe_devices()
    storage_ok = _storage_health()
    router_status = engine_state.ai_router.status() if engine_state.ai_router else None

    current_hardware_mode = engine_state.config.get("transcription", {}).get("hardware_mode", "automatic")
    restart_required = current_hardware_mode != engine_state.active_hardware_preference

    return {
        "service": "meetnote-engine",
        "os": os_display_name(),
        "hardware": engine_state.hardware_profile.to_dict() if engine_state.hardware_profile else None,
        "transcription_mode": engine_state.mode_decision.to_dict() if engine_state.mode_decision else None,
        "whisper": {
            "loading": engine_state.whisper_loading,
            "loaded": bool(engine_state.transcriber and engine_state.transcriber.is_loaded),
            "error": engine_state.whisper_load_error,
            "status": engine_state.transcriber.status() if engine_state.transcriber else None,
            "restart_required": restart_required,
            "saved_hardware_preference": current_hardware_mode,
            "active_hardware_preference": engine_state.active_hardware_preference,
        },
        "audio_devices": device_probe.to_dict(),
        "storage": storage_ok,
        "ai_providers": router_status,
        "active_meeting_id": engine_state.active_session.meeting_id if engine_state.active_session else None,
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@app.post("/ai/recheck")
async def recheck_ai_providers():
    """Manually re-run the Groq/Gemini connectivity probe — e.g. after the
    user edits engine/.env and restarts, or just to confirm a key still
    works. Runs the (blocking, network) probe off the event loop."""
    if engine_state.ai_router is None:
        raise HTTPException(503, "AI router not initialized yet")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, engine_state.ai_router.refresh_connectivity)
    return engine_state.ai_router.status()


@app.get("/config")
def get_config():
    # Always reflect the actual effective storage root (even when the user
    # never explicitly overrode it via /config), so the frontend's "Open
    # meetings directory" buttons always have a real path to open rather
    # than silently doing nothing.
    return {**engine_state.config, "storage_root": str(storage_root())}


@app.post("/config")
def patch_config(patch: dict):
    if "transcription" in patch and "hardware_mode" in patch["transcription"]:
        if engine_state.active_session is not None:
            raise HTTPException(409, "Cannot change transcription hardware while a meeting is in progress")

    engine_state.config = save_config(patch)
    if "storage_root" in patch and patch["storage_root"]:
        set_storage_root(Path(patch["storage_root"]))
    
    return engine_state.config


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TemplateBody(BaseModel):
    id: str
    name: str
    sections: list[str]


@app.get("/templates")
def list_templates():
    return [t.to_dict() for t in templates_module.list_templates()]


@app.post("/templates")
def upsert_template(body: TemplateBody):
    template = templates_module.NoteTemplate(id=body.id, name=body.name, sections=body.sections)
    templates_module.save_template(template)
    return template.to_dict()


@app.delete("/templates/{template_id}")
def delete_template(template_id: str):
    if template_id == "standard":
        raise HTTPException(400, "Cannot delete the built-in standard template")
    deleted = templates_module.delete_template(template_id)
    if not deleted:
        raise HTTPException(404, "Template not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Meetings — listing / detail / export
# ---------------------------------------------------------------------------


@app.get("/meetings")
def list_meetings():
    return db.list_meetings()


@app.get("/meetings/unfinished")
def unfinished_meetings():
    return engine_state.unfinished_on_startup


@app.get("/meetings/{meeting_id}")
def get_meeting_detail(meeting_id: str):
    row = db.get_meeting(meeting_id)
    if row is None:
        raise HTTPException(404, "Meeting not found")
    store = MeetingStore.load(Path(row["meeting_dir"]))
    return {
        "metadata": store.metadata,
        "chunks": store.read_transcript_chunks(),
    }


@app.delete("/meetings/{meeting_id}")
def delete_meeting(meeting_id: str):
    row = db.get_meeting(meeting_id)
    if row is None:
        raise HTTPException(404, "Meeting not found")

    if row["status"] in ("recording", "paused"):
        raise HTTPException(400, "Cannot delete an active meeting")

    meeting_dir = Path(row["meeting_dir"]).resolve()
    base_dir = meetings_root().resolve()

    if not str(meeting_dir).startswith(str(base_dir)):
        raise HTTPException(400, "Invalid meeting path")

    if meeting_dir.exists() and meeting_dir.is_dir():
        import stat as _stat

        def _remove_readonly(func, path, exc_info):
            """onerror handler: clear read-only flag and retry, else log and continue."""
            try:
                os.chmod(path, _stat.S_IWRITE)
                func(path)
            except Exception:
                # File may be locked by another process (e.g. a note file still open).
                # Skip it — leftover files will be cleaned up on next OS reboot or
                # when the lock is released.
                pass

        shutil.rmtree(meeting_dir, onerror=_remove_readonly)

    db.delete_meeting(meeting_id)

    global engine_state
    if engine_state.active_session and engine_state.active_session.meeting_id == meeting_id:
        engine_state.active_session = None

    return {"success": True, "meeting_id": meeting_id}


@app.get("/meetings/{meeting_id}/export/{fmt}")
def export_meeting(meeting_id: str, fmt: str):
    if fmt not in ("txt", "md"):
        raise HTTPException(400, "format must be one of: txt, md")
    row = db.get_meeting(meeting_id)
    if row is None:
        raise HTTPException(404, "Meeting not found")
    meeting_dir = Path(row["meeting_dir"])
    store = MeetingStore.load(meeting_dir)

    filename = {"txt": "notes.txt", "md": "notes.md"}[fmt]
    path = meeting_dir / filename
    if not path.exists():
        if store.metadata.get("notes_status") != "completed":
            raise HTTPException(409, "Notes have not been generated for this meeting yet")

        notes_md_path = meeting_dir / "notes.md"
        if not notes_md_path.exists():
            raise HTTPException(500, f"Expected export file missing: {filename} and notes.md is also missing")

        notes_markdown = notes_md_path.read_text(encoding="utf-8")
        if fmt == "txt":
            from export.txt import write_notes_txt
            write_notes_txt(meeting_dir, notes_markdown)

    # The path is returned (not the file's bytes) so the frontend opens it
    # with the native OS file handler via Tauri's opener plugin, rather than
    # this local server ever serving transcript/notes content over HTTP.
    return {"path": str(path)}


@app.get("/meetings/{meeting_id}/notes-text")
def notes_text(meeting_id: str):
    row = db.get_meeting(meeting_id)
    if row is None:
        raise HTTPException(404, "Meeting not found")
    notes_path = Path(row["meeting_dir"]) / "notes.md"
    if not notes_path.exists():
        return {"text": None}
    return {"text": notes_path.read_text(encoding="utf-8")}


@app.get("/meetings/{meeting_id}/transcript-path")
def transcript_path(meeting_id: str):
    row = db.get_meeting(meeting_id)
    if row is None:
        raise HTTPException(404, "Meeting not found")
    return {"path": str(Path(row["meeting_dir"]) / "transcript.txt")}


@app.get("/meetings/{meeting_id}/folder-path")
def folder_path(meeting_id: str):
    row = db.get_meeting(meeting_id)
    if row is None:
        raise HTTPException(404, "Meeting not found")
    return {"path": row["meeting_dir"]}


# ---------------------------------------------------------------------------
# Live meeting control
# ---------------------------------------------------------------------------


class StartMeetingBody(BaseModel):
    title: str
    template_id: str = "standard"


@app.get("/meeting/current")
def current_meeting():
    session = engine_state.active_session
    if session is None:
        return {"active": False}
    return {
        "active": True,
        "meeting_id": session.meeting_id,
        "state": session.state.state.value,
        "elapsed_seconds": session.elapsed_seconds(),
        "device_status": session.device_status(),
        "pending_chunks": session.pipeline.pending_count(),
    }


@app.post("/meeting/start")
def start_meeting(body: StartMeetingBody):
    with engine_state.session_lock:
        if engine_state.active_session is not None:
            raise HTTPException(409, "A meeting is already in progress")
            
        # Ensure whisper is loaded. If another thread is already loading it,
        # _load_whisper_in_background will wait on the lock.
        _load_whisper_in_background()

        if engine_state.transcriber is None or not engine_state.transcriber.is_loaded:
            detail = engine_state.whisper_load_error or "Whisper model failed to load."
            raise HTTPException(503, detail)

        # Check audio devices explicitly so we can return a clear error if both are broken.
        from audio.health import probe_devices
        devices = probe_devices()
        if not devices.microphone_ok and not devices.system_audio_ok:
            raise HTTPException(503, "Meeting start rejected: No audio devices available (neither microphone nor system audio).")

        try:
            audio_capture = AudioCaptureFactory.create()
        except UnsupportedPlatformError as exc:
            raise HTTPException(500, str(exc)) from exc

        meeting_id = uuid.uuid4().hex
        store = MeetingStore.create(
            meeting_id=meeting_id,
            title=body.title.strip() or "Untitled Meeting",
            template_id=body.template_id,
            transcription_mode=engine_state.transcriber.status(),
        )
        chunk_seconds = float(engine_state.config["audio"].get("chunk_seconds", 25))
        output_language = engine_state.config.get("transcription", {}).get("output_language", "en")
        session = MeetingSession(
            meeting_id=meeting_id,
            store=store,
            transcriber=engine_state.transcriber,
            audio_capture=audio_capture,
            chunk_seconds=chunk_seconds,
            output_language=output_language,
            broadcast=engine_state.broadcast,
        )
        try:
            session.start_recording()
        except Exception as exc:
            logger.exception("Failed to start recording")
            raise HTTPException(500, f"Failed to start recording: {exc}") from exc

        engine_state.active_session = session
        return {"meeting_id": meeting_id}


@app.post("/meeting/pause")
def pause_meeting():
    session = _require_session()
    session.pause()
    return {"state": session.state.state.value}


@app.post("/meeting/resume")
def resume_meeting():
    session = _require_session()
    session.resume()
    return {"state": session.state.state.value}


@app.post("/meeting/mark-important")
def mark_important():
    session = _require_session()
    offset = session.mark_important()
    return {"offset_seconds": offset}


@app.post("/meeting/stop")
async def stop_meeting():
    session = _require_session()
    duration = session.stop()
    session.set_generating_notes()
    meeting_id = session.meeting_id

    async def finish_and_generate_notes():
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, run_ai_pipeline, meeting_id, engine_state.ai_router, engine_state.broadcast
            )
        except Exception:
            logger.exception("AI pipeline task crashed for meeting %s", meeting_id)
        finally:
            session.mark_completed()
            if engine_state.active_session is session:
                engine_state.active_session = None

    asyncio.create_task(finish_and_generate_notes())
    return {"meeting_id": meeting_id, "duration_seconds": duration}


@app.post("/meetings/{meeting_id}/generate-notes")
async def retry_generate_notes(meeting_id: str):
    """Manual 'Retry Analysis' — usable any time after the meeting is
    recorded, including after an engine restart, per the offline-resilience
    requirement that AI analysis can always be retried later."""
    row = db.get_meeting(meeting_id)
    if row is None:
        raise HTTPException(404, "Meeting not found")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, run_ai_pipeline, meeting_id, engine_state.ai_router, engine_state.broadcast
    )
    return {"ok": True}


@app.post("/meetings/{meeting_id}/abandon")
def abandon_meeting(meeting_id: str):
    """User chose 'Start New Meeting' over resuming this crash-recovered
    one. We never delete transcript data — we just stop offering it as a
    resume candidate on future startups."""
    row = db.get_meeting(meeting_id)
    if row is None:
        raise HTTPException(404, "Meeting not found")
    store = MeetingStore.load(Path(row["meeting_dir"]))
    store.set_status("error")
    db.upsert_meeting(store.to_summary_row())
    engine_state.unfinished_on_startup = [
        m for m in engine_state.unfinished_on_startup if m["meeting_id"] != meeting_id
    ]
    return {"ok": True}


@app.post("/meetings/{meeting_id}/resume-after-restart")
def resume_after_restart(meeting_id: str):
    """Reattach a live MeetingSession to a meeting left unfinished by a
    crash/restart, continuing chunk indices and timestamps from where it
    left off (product spec section 6)."""
    with engine_state.session_lock:
        if engine_state.active_session is not None:
            raise HTTPException(409, "A meeting is already in progress")
            
        if engine_state.transcriber is None and engine_state.mode_decision.device != "error":
            _load_whisper_in_background()
            
        if engine_state.transcriber is None or not engine_state.transcriber.is_loaded:
            detail = engine_state.whisper_load_error or "Whisper model failed to load."
            raise HTTPException(503, detail)

        row = db.get_meeting(meeting_id)
        if row is None:
            raise HTTPException(404, "Meeting not found")

        store = MeetingStore.load(Path(row["meeting_dir"]))
        chunks = store.read_transcript_chunks()
        next_index = (max((c["chunk_index"] for c in chunks), default=-1)) + 1
        last_end_offset = max((c["end_offset_seconds"] for c in chunks), default=0.0)

        try:
            audio_capture = AudioCaptureFactory.create()
        except UnsupportedPlatformError as exc:
            raise HTTPException(500, str(exc)) from exc

        chunk_seconds = float(engine_state.config["audio"].get("chunk_seconds", 25))
        output_language = engine_state.config.get("transcription", {}).get("output_language", "en")
        session = MeetingSession(
            meeting_id=meeting_id,
            store=store,
            transcriber=engine_state.transcriber,
            audio_capture=audio_capture,
            chunk_seconds=chunk_seconds,
            output_language=output_language,
            broadcast=engine_state.broadcast,
            start_index=next_index,
            initial_elapsed_seconds=last_end_offset,
            initial_state=MeetingState.RECOVERY,
        )
        session.start_recording()
        engine_state.active_session = session
        engine_state.unfinished_on_startup = [
            m for m in engine_state.unfinished_on_startup if m["meeting_id"] != meeting_id
        ]
        return {"meeting_id": meeting_id, "resumed_from_chunk": next_index}


# ---------------------------------------------------------------------------
# WebSocket — live meeting event stream
# ---------------------------------------------------------------------------


@app.websocket("/ws/meeting")
async def ws_meeting(websocket: WebSocket):
    await websocket.accept()
    engine_state.ws_hub.clients.add(websocket)
    try:
        session = engine_state.active_session
        await websocket.send_json(
            {
                "type": "snapshot",
                "active": session is not None,
                "meeting_id": session.meeting_id if session else None,
                "state": session.state.state.value if session else None,
            }
        )
        while True:
            # This endpoint is push-only from the server; we still need to
            # await something so a client disconnect is detected promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        engine_state.ws_hub.clients.discard(websocket)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=28765)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_config=None)


if __name__ == "__main__":
    main()
