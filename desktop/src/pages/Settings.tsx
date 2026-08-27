import { useEffect, useState } from "react";
import { FolderOpen } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { openPath } from "@tauri-apps/plugin-opener";
import { Button, Card, HealthRow, SectionLabel } from "../components/ui";
import { ProviderStatusRow } from "../components/ProviderStatusRow";
import { engineClient } from "../services/engineClient";
import type { AppConfig, HealthResponse, NoteTemplate } from "../types/engine";

export function Settings() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [templates, setTemplates] = useState<NoteTemplate[]>([]);
  const [saved, setSaved] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const [chunkSecondsInput, setChunkSecondsInput] = useState<string>("");
  const [chunkError, setChunkError] = useState<string | null>(null);
  const [pendingHardwareMode, setPendingHardwareMode] = useState<string | null>(null);
  const [showRestartDialog, setShowRestartDialog] = useState(false);
  const [isRestarting, setIsRestarting] = useState(false);
  const [restartError, setRestartError] = useState<string | null>(null);

  useEffect(() => {
    engineClient.getConfig().then((c) => {
      setConfig(c);
      setChunkSecondsInput(String(c.audio.chunk_seconds));
    });
    engineClient.health().then(setHealth);
    engineClient.listTemplates().then(setTemplates);
  }, []);

  async function recheckProviders() {
    setRechecking(true);
    try {
      const ai_providers = await engineClient.recheckAIProviders();
      setHealth((h) => (h ? { ...h, ai_providers } : h));
    } finally {
      setRechecking(false);
    }
  }

  async function save(patch: Partial<AppConfig>) {
    try {
      const updated = await engineClient.patchConfig(patch);
      setConfig(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 1200);
      
      // If we saved anything, re-fetch health to ensure state is fresh
      const newHealth = await engineClient.health();
      setHealth(newHealth);
    } catch (err: any) {
      alert(err.message || "Failed to save settings");
    }
  }

  function handleHardwareChange(e: React.ChangeEvent<HTMLSelectElement>) {
    if (health?.active_meeting_id) return;
    setPendingHardwareMode(e.target.value);
    setShowRestartDialog(true);
  }

  function cancelRestart() {
    setPendingHardwareMode(null);
    setShowRestartDialog(false);
  }

  async function confirmRestart() {
    if (!pendingHardwareMode || !config) return;
    setIsRestarting(true);
    setRestartError(null);
    try {
      // 1. Persist the newly selected hardware preference.
      await engineClient.patchConfig({
        transcription: {
          ...config.transcription,
          hardware_mode: pendingHardwareMode as "automatic" | "gpu" | "cpu",
        },
      });
      // 2. Initiate full application restart.
      await invoke("restart_app");
    } catch (err: any) {
      setIsRestarting(false);
      setRestartError(err.message || "Failed to save config or restart app");
    }
  }

  if (!config) {
    return <div className="px-8 py-10 text-sm text-[var(--color-text-muted)]">Loading…</div>;
  }

  const hw = health?.hardware;
  const mode = health?.transcription_mode;

  return (
    <div className="mx-auto max-w-2xl px-8 py-10 pb-16">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[var(--color-text)]">Settings</h1>
        {saved && <span className="text-xs text-[var(--color-success)]">Saved</span>}
      </div>

      <Card className="mt-6 p-5">
        <SectionLabel>General</SectionLabel>

        <Field label="Startup behavior">
          <select
            value={config.startup_behavior}
            onChange={(e) => save({ startup_behavior: e.target.value })}
            className={selectClass}
          >
            <option value="show_dashboard">Show dashboard</option>
            <option value="show_new_meeting">Go straight to New Meeting</option>
          </select>
        </Field>

        <Field label="Default meeting template">
          <select
            value={config.default_template_id}
            onChange={(e) => save({ default_template_id: e.target.value })}
            className={selectClass}
          >
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Transcript storage location">
          <div className="flex items-center gap-2">
            <span className="flex-1 truncate rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-xs text-[var(--color-text-muted)]">
              {config.storage_root ?? "~/MeetNote"}
            </span>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => config.storage_root && openPath(config.storage_root)}
            >
              <FolderOpen size={14} />
              Open
            </Button>
          </div>
        </Field>
      </Card>

      <Card className="mt-4 p-5">
        <SectionLabel>Audio</SectionLabel>
        <HealthRow
          label="Microphone"
          ok={!!health?.audio_devices.microphone_ok}
          detail={health?.audio_devices.microphone_name ?? "Automatic"}
        />
        <HealthRow
          label="System Audio"
          ok={!!health?.audio_devices.system_audio_ok}
          detail={health?.audio_devices.system_audio_name ?? "Automatic"}
        />
        <p className="mt-2 text-xs text-[var(--color-text-faint)]">
          MeetNote automatically uses your default microphone and default output device. Manual device
          selection and input/output level controls are planned but not implemented in this version.
        </p>

        <Field label="Chunk length (seconds)">
          <input
            type="number"
            min={5}
            max={120}
            value={chunkSecondsInput}
            onChange={(e) => {
              setChunkSecondsInput(e.target.value);
              setChunkError(null);
            }}
            onBlur={(e) => {
              const val = Number(e.target.value);
              if (!Number.isInteger(val) || val < 5 || val > 120) {
                setChunkError("Chunk length must be between 5 and 120 seconds.");
                return;
              }
              setChunkError(null);
              if (val !== config.audio.chunk_seconds) {
                save({ audio: { ...config.audio, chunk_seconds: val } });
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.currentTarget.blur();
              }
            }}
            className={`${selectClass} ${chunkError ? "border-red-500 focus:border-red-500" : ""}`}
          />
          {chunkError && <p className="mt-1 text-xs text-red-500">{chunkError}</p>}
        </Field>
      </Card>

      <Card className="mt-4 p-5">
        <SectionLabel>Transcription</SectionLabel>

        <Field label="Transcription hardware">
          <select
            value={pendingHardwareMode || config.transcription?.hardware_mode || "automatic"}
            onChange={handleHardwareChange}
            disabled={!!health?.active_meeting_id}
            className={selectClass}
          >
            <option value="automatic">Automatic</option>
            <option value="gpu">NVIDIA GPU</option>
            <option value="cpu">CPU only</option>
          </select>
          {!!health?.active_meeting_id && (
            <p className="mt-2 text-xs text-[var(--color-warning)]">
              Locked while a meeting is recording.
            </p>
          )}
          <p className="mt-2 text-xs text-[var(--color-text-faint)]">
            {(!config.transcription?.hardware_mode || config.transcription.hardware_mode === "automatic") &&
              "Automatically uses NVIDIA GPU acceleration when available, otherwise uses CPU."}
            {config.transcription?.hardware_mode === "gpu" &&
              "Always use NVIDIA GPU acceleration. MeetNote will not silently switch to CPU."}
            {config.transcription?.hardware_mode === "cpu" &&
              "Use CPU transcription even when a compatible NVIDIA GPU is available."}
          </p>
          {health?.whisper?.restart_required && !pendingHardwareMode && !showRestartDialog && (
            <div className="mt-4 rounded-md bg-[var(--color-surface-2)] p-3 border border-[var(--color-border)] flex items-center justify-between">
              <span className="text-sm font-medium text-amber-500">
                Restart required. {health.whisper.saved_hardware_preference === 'gpu' ? 'NVIDIA GPU' : health.whisper.saved_hardware_preference === 'cpu' ? 'CPU only' : 'Automatic'} will be used after MeetNote restarts.
              </span>
              <Button variant="primary" size="sm" onClick={async () => {
                setIsRestarting(true);
                setShowRestartDialog(true);
                try {
                  await invoke("restart_app");
                } catch (err: any) {
                  setIsRestarting(false);
                  setRestartError(err.message);
                }
              }}>Restart Now</Button>
            </div>
          )}
        </Field>

        <div className="mt-4 space-y-2">
          <HealthRow label="Operating System" ok detail={health?.os} />
          <HealthRow label="CPU" ok detail={hw ? `${hw.cpu_model} (${hw.cpu_logical} threads)` : undefined} />
          <HealthRow label="RAM" ok detail={hw ? `${hw.ram_total_gb.toFixed(1)} GB` : undefined} />
          <HealthRow label="Detected GPU" ok={!!hw?.gpu_name} detail={hw?.gpu_name ?? "None detected"} />
          <HealthRow label="VRAM" ok={!!hw?.gpu_vram_mb} detail={hw?.gpu_vram_mb ? `${hw.gpu_vram_mb} MB` : "—"} />
          <HealthRow
            label="CUDA"
            ok={!!hw?.cuda_usable}
            detail={hw?.cuda_usable ? "Usable" : hw?.cuda_failure_reason ?? "Unavailable"}
          />
          <HealthRow label="Whisper Model" ok detail={mode?.model_size} />
          <HealthRow label="Compute Type" ok detail={mode?.compute_type} />
          
          {(() => {
            const pref = health?.whisper?.active_hardware_preference || "automatic";
            let modeLabel = "Unknown";
            let subText = "";
            let isError = false;

            if (pref === "automatic") {
              if (hw?.cuda_usable) {
                modeLabel = "NVIDIA GPU";
              } else {
                modeLabel = "CPU";
              }
            } else if (pref === "cpu") {
              modeLabel = "CPU";
              if (hw?.gpu_name) {
                subText = "GPU available but disabled by preference.";
              }
            } else if (pref === "gpu") {
              if (hw?.cuda_usable) {
                modeLabel = "NVIDIA GPU";
              } else {
                modeLabel = "Unavailable";
                subText = hw?.cuda_failure_reason || "CUDA is not available.";
                isError = true;
              }
            }

            return (
              <div className="flex flex-col gap-1">
                <HealthRow 
                  label="Current Mode" 
                  ok={!isError} 
                  detail={modeLabel} 
                />
                {subText && (
                  <p className={`pl-32 text-xs ${isError ? "text-[var(--color-danger)]" : "text-[var(--color-text-faint)]"}`}>
                    {subText}
                  </p>
                )}
              </div>
            );
          })()}
        </div>
      </Card>

      <Card className="mt-4 p-5">
        <div className="flex items-center justify-between">
          <SectionLabel>AI</SectionLabel>
          <Button variant="ghost" size="sm" onClick={recheckProviders} disabled={rechecking}>
            {rechecking ? "Checking…" : "Recheck"}
          </Button>
        </div>
        <ProviderStatusRow label="Groq API (primary)" provider={health?.ai_providers?.primary} />
        <ProviderStatusRow label="Gemini API (fallback)" provider={health?.ai_providers?.fallback} />
        <p className="mt-2 text-xs text-[var(--color-text-faint)]">
          API keys are never entered in the app. Add <code>GROQ_API_KEY</code> and/or{" "}
          <code>GEMINI_API_KEY</code> to <code>engine/.env</code> (copy from{" "}
          <code>engine/.env.example</code>) and restart MeetNote. &ldquo;Recheck&rdquo; makes a small,
          free, read-only call to each provider to confirm the key actually works, not just that it's
          present.
        </p>
      </Card>

      <Card className="mt-4 p-5">
        <SectionLabel>Storage</SectionLabel>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => config.storage_root && openPath(config.storage_root)}
        >
          <FolderOpen size={14} />
          Open meetings directory
        </Button>
        <p className="mt-2 text-xs text-[var(--color-text-faint)]">
          MeetNote stores your API keys securely in your system's native keychain (Credential Manager on
          Windows, Keychain on macOS). They are never saved in plain text.
        </p>
      </Card>
      
      {showRestartDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <Card className="w-full max-w-md p-6 bg-[var(--color-surface)] shadow-2xl">
            {isRestarting ? (
              <div className="flex flex-col items-center justify-center py-6">
                 <h2 className="text-lg font-semibold text-[var(--color-text)]">Restarting MeetNote...</h2>
                 <p className="mt-4 text-sm text-[var(--color-text-muted)] text-center leading-relaxed">
                   Saving configuration<br/>Stopping services<br/>Restarting application
                 </p>
              </div>
            ) : restartError ? (
              <div>
                <h2 className="text-lg font-semibold text-[var(--color-text)]">MeetNote could not restart automatically.</h2>
                <p className="mt-3 text-sm text-[var(--color-text-muted)]">
                  Your new transcription setting has been saved.
                </p>
                <p className="mt-3 text-sm text-[var(--color-text-muted)]">
                  Please restart MeetNote manually.
                </p>
                {restartError && <p className="mt-3 text-xs text-[var(--color-danger)]">{restartError}</p>}
                <div className="mt-6 flex justify-end gap-3">
                  <Button variant="primary" onClick={() => { setShowRestartDialog(false); setRestartError(null); setPendingHardwareMode(null); }}>Close</Button>
                </div>
              </div>
            ) : (
              <>
                <h2 className="text-lg font-semibold text-[var(--color-text)]">Restart MeetNote?</h2>
                <p className="mt-2 text-sm text-[var(--color-text-muted)]">
                  Changing transcription hardware requires a restart.
                </p>
                
                <div className="mt-5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-4 text-sm">
                  <div className="flex justify-between mb-3 border-b border-[var(--color-border)] pb-3">
                    <span className="text-[var(--color-text-muted)]">Current mode</span>
                    <span className="font-medium text-[var(--color-text)]">
                      {health?.whisper?.active_hardware_preference === 'gpu' ? 'NVIDIA GPU' : health?.whisper?.active_hardware_preference === 'cpu' ? 'CPU only' : 'Automatic'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--color-text-muted)]">New mode</span>
                    <span className="font-medium text-[var(--color-text)]">
                      {pendingHardwareMode === 'gpu' ? 'NVIDIA GPU' : pendingHardwareMode === 'cpu' ? 'CPU only' : 'Automatic'}
                    </span>
                  </div>
                </div>

                <div className="mt-6 flex justify-end gap-3">
                  <Button variant="secondary" onClick={cancelRestart}>Cancel</Button>
                  <Button variant="primary" onClick={confirmRestart}>Restart</Button>
                </div>
              </>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

const selectClass =
  "mt-1.5 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-accent)]";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-4 first:mt-0">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  );
}
