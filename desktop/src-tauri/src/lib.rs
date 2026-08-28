// MeetNote desktop shell.
//
// This crate is intentionally thin: almost all product logic (audio capture,
// hardware detection, transcription, persistence, AI notes) lives in the
// Python `engine/` service so it can be unit tested and iterated on without
// recompiling Rust. Tauri's job here is just:
//   1. launch the local engine process as a child of the app and keep it
//      alive for the lifetime of the window,
//   2. make sure it is always killed when the app exits (never leave an
//      orphaned process holding the microphone open),
//   3. tell the frontend which port to talk to.
//
// The frontend talks to the engine directly over HTTP/WebSocket on
// 127.0.0.1 — see desktop/src/services/engineClient.ts.

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;

/// Fixed local port for the engine. Kept fixed (rather than negotiated) for
/// V1 simplicity; if this ever collides with something else on the user's
/// machine, engine/main.py will fail to bind and log the error to
/// engine/logs/engine.stderr.log — the frontend's health check will then
/// show the engine as unavailable rather than hanging silently.
const ENGINE_PORT: u16 = 28765;

struct EngineHandle(Mutex<Option<Child>>);

/// Locate the Python venv and entrypoint for the engine in *dev-mode source
/// layout* (this repo, run via `cargo tauri dev`).
///
/// NOTE (packaging): for a distributable build, the engine must instead be
/// frozen into a standalone executable (e.g. with PyInstaller) and wired in
/// as a Tauri "externalBin" sidecar declared in tauri.conf.json, rather than
/// depending on a `.venv` sitting next to the source tree. That packaging
/// step is deliberately out of scope for this phase (see docs/ARCHITECTURE.md)
/// — dev-mode process spawning is what's implemented and tested here.
fn resolve_engine_paths() -> Option<(PathBuf, PathBuf, PathBuf)> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")); // .../desktop/src-tauri
    let project_root = manifest_dir.parent()?.parent()?.to_path_buf(); // .../meetnote
    let engine_dir = project_root.join("engine");

    let python_exe = if cfg!(target_os = "windows") {
        engine_dir.join(".venv").join("Scripts").join("python.exe")
    } else {
        engine_dir.join(".venv").join("bin").join("python")
    };
    let main_py = engine_dir.join("main.py");

    if python_exe.exists() && main_py.exists() {
        Some((engine_dir, python_exe, main_py))
    } else {
        None
    }
}

/// When set (by `run_meetnote.py`, the root-level launcher), the engine is
/// already running under the launcher's own management — Tauri must not
/// spawn a second copy (it would just fail to bind ENGINE_PORT) or kill it
/// on exit (that's the launcher's job, so it can do a graceful shutdown and
/// tell the difference between "closed normally" and "died unexpectedly").
/// Unset (e.g. running `npm run tauri dev` or the built .exe directly,
/// without the launcher), behavior is exactly as before: Tauri owns the
/// engine's whole lifecycle itself.
fn launcher_managed() -> bool {
    std::env::var_os("MEETNOTE_LAUNCHER_MANAGED").is_some()
}

fn spawn_engine(app: &tauri::AppHandle) {
    if launcher_managed() {
        eprintln!("[meetnote] MEETNOTE_LAUNCHER_MANAGED set — not spawning our own engine process");
        return;
    }

    let Some((engine_dir, python_exe, main_py)) = resolve_engine_paths() else {
        eprintln!(
            "[meetnote] engine venv not found at expected dev-mode path (engine/.venv). \
             The app will run but every engine-backed feature (health check, recording, \
             transcription, AI notes) will show as unavailable until it is set up. \
             See engine/README.md."
        );
        return;
    };

    let log_dir = engine_dir.join("logs");
    let _ = std::fs::create_dir_all(&log_dir);
    let stdout_log = std::fs::File::create(log_dir.join("engine.stdout.log")).ok();
    let stderr_log = std::fs::File::create(log_dir.join("engine.stderr.log")).ok();

    let mut cmd = Command::new(&python_exe);
    cmd.arg(&main_py)
        .arg("--port")
        .arg(ENGINE_PORT.to_string())
        .current_dir(&engine_dir);

    cmd.stdout(stdout_log.map_or(Stdio::null(), Stdio::from));
    cmd.stderr(stderr_log.map_or(Stdio::null(), Stdio::from));

    // Detach from the Tauri process's own stdin so the child never blocks
    // waiting on input that will never arrive.
    cmd.stdin(Stdio::null());

    match cmd.spawn() {
        Ok(child) => {
            eprintln!(
                "[meetnote] engine started (pid {}), logs at {}",
                child.id(),
                log_dir.display()
            );
            *app.state::<EngineHandle>().0.lock().unwrap() = Some(child);
        }
        Err(e) => {
            eprintln!("[meetnote] failed to launch engine process: {e}");
        }
    }
}

fn kill_engine(app: &tauri::AppHandle) {
    if let Some(mut child) = app.state::<EngineHandle>().0.lock().unwrap().take() {
        eprintln!("[meetnote] stopping engine (pid {})", child.id());
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[tauri::command]
fn engine_port() -> u16 {
    ENGINE_PORT
}

#[tauri::command]
fn restart_app() {
    std::process::exit(42);
}

/// Open a plain-text notes file in the platform text editor.
///
/// The path is supplied by the frontend after it has been resolved and
/// verified by the engine (GET /meetings/{id}/export/txt), so it is always
/// a known MeetNote artifact — not an arbitrary caller-controlled path.
/// We still validate existence here as a belt-and-suspenders check.
#[tauri::command]
fn open_in_notepad(path: String) -> Result<(), String> {
    let p = std::path::Path::new(&path);
    if !p.exists() {
        return Err(format!("Notes file not found: {}", p.display()));
    }
    if !p.is_file() {
        return Err("Path is not a file".to_string());
    }

    #[cfg(target_os = "windows")]
    {
        // Explicitly open with notepad.exe, not with the default app.
        Command::new("notepad.exe")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to launch Notepad: {e}"))?;
    }
    #[cfg(target_os = "macos")]
    {
        // `open -e` forces TextEdit; plain `open` would pick the default
        // Markdown viewer which may not be a text editor.
        Command::new("open")
            .args(["-e", &path])
            .spawn()
            .map_err(|e| format!("Failed to open file: {e}"))?;
    }
    #[cfg(target_os = "linux")]
    {
        Command::new("xdg-open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to open file: {e}"))?;
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_opener::init())
        .manage(EngineHandle(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![engine_port, restart_app, open_in_notepad])
        .setup(|app| {
            spawn_engine(&app.handle());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                kill_engine(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // Safety net: guarantees the engine process is never left running
            // as an orphan (holding the microphone/system-audio device open)
            // even if the app exits via a path that doesn't fire
            // CloseRequested on the main window.
            if let tauri::RunEvent::ExitRequested { .. } = event {
                kill_engine(app_handle);
            }
        });
}
