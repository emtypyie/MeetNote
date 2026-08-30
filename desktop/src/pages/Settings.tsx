import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  FolderOpen,
  Languages,
  Loader2,
  RefreshCw,
  Settings as SettingsIcon,
  Sparkles,
  Volume2,
} from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { Button, Card, HealthRow, SectionLabel, Select, StatusDot } from "../components/ui";
import { ProviderStatusRow } from "../components/ProviderStatusRow";
import { engineClient } from "../services/engineClient";
import type { AppConfig, HealthResponse, NoteTemplate } from "../types/engine";

const HARDWARE_LABEL: Record<string, string> = {
  automatic: "Automatic",
  gpu: "NVIDIA GPU",
  cpu: "CPU only",
};

/** Opens a path (file or directory) via the native `open_path` Tauri
 * command, tracking its own busy/error state. Two independent instances
 * are used below (storage root, meetings directory) so one button's
 * failure or in-flight state never affects the other's. */
function useOpenPath() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function open(path: string | undefined) {
    setError(null);
    if (!path) {
      setError("No path is available yet.");
      return;
    }
    setPending(true);
    try {
      await invoke<void>("open_path", { path });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }

  return { open, pending, error };
}

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
  const [loadError, setLoadError] = useState<string | null>(null);
  const storageOpen = useOpenPath();
  const meetingsOpen = useOpenPath();

  function loadSettings() {
    setLoadError(null);
    engineClient
      .getConfig()
      .then((c) => {
        setConfig(c);
        setChunkSecondsInput(String(c.audio.chunk_seconds));
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : String(err)));
    engineClient.health().then(setHealth).catch(() => {});
    engineClient.listTemplates().then(setTemplates).catch(() => {});
  }

  useEffect(loadSettings, []);

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

  function handleHardwareChange(value: string) {
    if (health?.active_meeting_id) return;
    setPendingHardwareMode(value);
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

  if (loadError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
        <AlertTriangle size={24} className="text-[var(--color-danger)]" />
        <p className="text-sm font-medium text-[var(--color-text)]">Unable to load settings</p>
        <p className="max-w-sm text-xs text-[var(--color-text-muted)]">
          MeetNote could not reach the local engine.
        </p>
        <Button variant="secondary" onClick={loadSettings}>
          <RefreshCw size={14} />
          Try Again
        </Button>
      </div>
    );
  }

  if (!config) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
        <Loader2 size={20} className="animate-spin text-[var(--color-text-faint)]" />
        <p className="text-sm text-[var(--color-text-muted)]">Loading settings…</p>
      </div>
    );
  }

  const hw = health?.hardware;
  const mode = health?.transcription_mode;

  return (
    <div className="mx-auto max-w-5xl px-10 py-10 pb-16">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[var(--color-text)]">Settings</h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            Configure how MeetNote records, transcribes, and generates notes.
          </p>
        </div>
        {saved && (
          <span className="flex items-center gap-1.5 text-xs text-[var(--color-success)]">
            <CheckCircle2 size={13} />
            Saved
          </span>
        )}
      </div>

      {/* CSS multi-column layout, not a row-paired grid: each card keeps its
          natural height and the browser balances the two columns by total
          content, so a tall Transcription card never forces an empty gap
          beside a short Language card in the same "row" (there is no row).
          break-inside-avoid keeps a card from being visually split across
          the column boundary. */}
      <div className="mt-6 columns-1 gap-4 lg:columns-2">
      <Card className="mb-4 break-inside-avoid p-5">
        <SectionLabel icon={SettingsIcon}>General</SectionLabel>

        <Field label="Startup behavior">
          <Select
            value={config.startup_behavior}
            onChange={(val) => save({ startup_behavior: val })}
            options={[
              { value: "show_dashboard", label: "Show dashboard" },
              { value: "show_new_meeting", label: "Go straight to New Meeting" }
            ]}
          />
        </Field>

        <Field label="Default meeting template">
          <Select
            value={config.default_template_id}
            onChange={(val) => save({ default_template_id: val })}
            options={templates.map((t) => ({ value: t.id, label: t.name }))}
          />
        </Field>

        <Field label="Transcript storage location">
          <div className="flex items-center gap-2">
            <span className="flex-1 truncate rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-xs text-[var(--color-text-muted)]">
              {config.storage_root ?? "~/MeetNote"}
            </span>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => storageOpen.open(config.storage_root)}
              loading={storageOpen.pending}
            >
              {!storageOpen.pending && <FolderOpen size={14} />}
              Open
            </Button>
          </div>
          {storageOpen.error && (
            <p className="mt-1.5 text-xs text-[var(--color-danger)]">{storageOpen.error}</p>
          )}
        </Field>
      </Card>

      <Card className="mb-4 break-inside-avoid p-5">
        <SectionLabel icon={Volume2}>Audio</SectionLabel>
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
          Uses your default microphone and speakers automatically. Manual device selection isn&rsquo;t
          available yet.
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
            className={`${selectClass} ${chunkError ? "border-[var(--color-danger)] focus:border-[var(--color-danger)]" : ""}`}
          />
          {chunkError && <p className="mt-1 text-xs text-[var(--color-danger)]">{chunkError}</p>}
        </Field>
      </Card>

      <Card className="mb-4 break-inside-avoid p-5">
        <SectionLabel icon={Cpu}>Transcription</SectionLabel>

        {(() => {
          const pref = health?.whisper?.active_hardware_preference || "automatic";
          let modeLabel = "Unknown";
          let subText = "";
          let isError = false;

          if (pref === "automatic") {
            modeLabel = hw?.cuda_usable ? "NVIDIA GPU" : "CPU";
          } else if (pref === "cpu") {
            modeLabel = "CPU";
            if (hw?.gpu_name) subText = "GPU available but disabled by preference.";
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
            <div
              className={`mb-4 flex items-center justify-between rounded-lg px-3 py-2.5 ${
                isError
                  ? "bg-[var(--color-danger-soft)]"
                  : "bg-[var(--color-surface-2)]"
              }`}
            >
              <div>
                <p className="text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">Active mode</p>
                <p className={`text-sm font-semibold ${isError ? "text-[var(--color-danger)]" : "text-[var(--color-text)]"}`}>
                  {modeLabel === "NVIDIA GPU" ? "Using NVIDIA GPU acceleration" : modeLabel === "CPU" ? "Running on CPU" : modeLabel}
                </p>
                {subText && <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">{subText}</p>}
              </div>
              <StatusDot ok={!isError} />
            </div>
          );
        })()}

        <Field label="Transcription hardware">
          <Select
            value={pendingHardwareMode || config.transcription?.hardware_mode || "automatic"}
            onChange={handleHardwareChange}
            disabled={!!health?.active_meeting_id}
            options={[
              { value: "automatic", label: "Automatic" },
              { value: "gpu", label: "NVIDIA GPU" },
              { value: "cpu", label: "CPU only" }
            ]}
          />
          {!!health?.active_meeting_id && (
            <p className="mt-2 text-xs text-[var(--color-warning)]">
              Locked while a meeting is recording.
            </p>
          )}
          <p className="mt-2 text-xs text-[var(--color-text-faint)]">
            {(!config.transcription?.hardware_mode || config.transcription.hardware_mode === "automatic") &&
              "Uses NVIDIA GPU acceleration when available, otherwise uses CPU."}
            {config.transcription?.hardware_mode === "gpu" &&
              "Always uses NVIDIA GPU acceleration. MeetNote will not silently switch to CPU."}
            {config.transcription?.hardware_mode === "cpu" &&
              "Uses CPU transcription even when a compatible NVIDIA GPU is available."}
          </p>
          {health?.whisper?.restart_required && !pendingHardwareMode && !showRestartDialog && (
            <div className="mt-4 rounded-md bg-[var(--color-warning-soft)] p-3 flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-sm font-medium text-[var(--color-warning)]">
                <RefreshCw size={14} className="shrink-0" />
                Restart required. {HARDWARE_LABEL[health.whisper.saved_hardware_preference ?? "automatic"]} will be used after MeetNote restarts.
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
              }}>
                <RefreshCw size={14} />
                Restart Now
              </Button>
            </div>
          )}
        </Field>

        <div className="mt-4 space-y-2">
          <HealthRow label="Operating System" ok detail={health?.os} />
          <HealthRow label="CPU" ok detail={hw ? `${hw.cpu_model} (${hw.cpu_logical} threads)` : undefined} />
          <HealthRow label="RAM" ok detail={hw ? `${hw.ram_total_gb.toFixed(1)} GB` : undefined} />
          <HealthRow label="Detected GPU" ok={!!hw?.gpu_name} detail={hw?.gpu_name ?? "None detected"} />
          <HealthRow label="VRAM" ok={!!hw?.gpu_vram_mb} detail={hw?.gpu_vram_mb ? `${hw.gpu_vram_mb} MB` : "N/A"} />
          <HealthRow
            label="CUDA"
            ok={!!hw?.cuda_usable}
            detail={hw?.cuda_usable ? "Usable" : hw?.cuda_failure_reason ?? "Unavailable"}
          />
          <HealthRow label="Whisper Model" ok detail={mode?.model_size} />
          <HealthRow label="Compute Type" ok detail={mode?.compute_type} />
        </div>
      </Card>

      <Card className="mb-4 break-inside-avoid p-5">
        <SectionLabel icon={Languages}>Language & Translation</SectionLabel>
        <Field label="Transcript output language">
          <Select
            value={config.transcription?.output_language || "en"}
            onChange={(val) => save({ transcription: { ...config.transcription, output_language: val } })}
            options={[
              { value: "en", label: "English" }
            ]}
          />
          <p className="mt-2 text-xs text-[var(--color-text-faint)]">
            MeetNote detects the spoken language automatically. Non-English speech is translated to
            English.
          </p>
        </Field>
      </Card>

      <Card className="mb-4 break-inside-avoid p-5">
        <SectionLabel
          icon={Sparkles}
          trailing={
            <Button variant="ghost" size="sm" onClick={recheckProviders} loading={rechecking}>
              Recheck
            </Button>
          }
        >
          AI
        </SectionLabel>
        <ProviderStatusRow label="Gemini" provider={health?.ai_providers?.gemini} />
        <ProviderStatusRow label="Groq" provider={health?.ai_providers?.groq} />

        {health?.ai_providers?.primary && (
          <div className="mt-3 rounded-lg bg-[var(--color-surface-2)] p-3">
            <p className="text-xs font-medium text-[var(--color-text-secondary)] mb-1">Active configuration</p>
            <div className="flex justify-between items-center text-xs">
              <span className="text-[var(--color-text-muted)]">Primary</span>
              <span className="text-[var(--color-text)] capitalize">{health.ai_providers.primary}</span>
            </div>
            {health.ai_providers.fallback && (
              <div className="flex justify-between items-center text-xs mt-1">
                <span className="text-[var(--color-text-muted)]">Fallback</span>
                <span className="text-[var(--color-text)] capitalize">{health.ai_providers.fallback}</span>
              </div>
            )}
          </div>
        )}

        <p className="mt-3 text-xs text-[var(--color-text-faint)]">
          Configure either Gemini or Groq. When both are configured, Gemini is used first and Groq is
          used as fallback.
        </p>
        <p className="mt-2 text-xs text-[var(--color-text-faint)]">
          API keys are never entered in the app. Add <code>GEMINI_API_KEY</code> and/or{" "}
          <code>GROQ_API_KEY</code> to <code>engine/.env</code> (copy from{" "}
          <code>engine/.env.example</code>) and restart MeetNote. &ldquo;Recheck&rdquo; makes a small,
          free, read-only call to each provider to confirm the key actually works, not just that it's
          present.
        </p>
      </Card>

      <Card className="mb-4 break-inside-avoid p-5">
        <SectionLabel icon={FolderOpen}>Storage</SectionLabel>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => meetingsOpen.open(config.meetings_root)}
          loading={meetingsOpen.pending}
        >
          {!meetingsOpen.pending && <FolderOpen size={14} />}
          Open meetings directory
        </Button>
        {meetingsOpen.error && (
          <p className="mt-1.5 text-xs text-[var(--color-danger)]">{meetingsOpen.error}</p>
        )}
        <p className="mt-2 text-xs text-[var(--color-text-faint)]">
          API keys live only in <code>engine/.env</code>, which is excluded from Git. MeetNote never
          displays, transmits, or stores them anywhere else.
        </p>
      </Card>
      </div>

      {showRestartDialog && (
        <div className="animate-overlay-in fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <Card className="animate-modal-in w-full max-w-md p-6 bg-[var(--color-surface-2)] shadow-[var(--shadow-lg)]">
            {isRestarting ? (
              <div className="flex flex-col items-center justify-center gap-3 py-6 text-center">
                 <Loader2 size={22} className="animate-spin text-[var(--color-accent)]" />
                 <h2 className="text-lg font-semibold text-[var(--color-text)]">Restarting MeetNote…</h2>
                 <p className="text-sm text-[var(--color-text-muted)] leading-relaxed">
                   Saving configuration, stopping services, and restarting the application.
                 </p>
              </div>
            ) : restartError ? (
              <div>
                <div className="mb-3 flex items-center gap-2.5">
                  <AlertTriangle size={18} className="text-[var(--color-warning)]" />
                  <h2 className="text-lg font-semibold text-[var(--color-text)]">Could not restart automatically</h2>
                </div>
                <p className="text-sm text-[var(--color-text-muted)]">
                  Your new transcription setting has been saved. Please restart MeetNote manually.
                </p>
                {restartError && <p className="mt-3 text-xs text-[var(--color-danger)]">{restartError}</p>}
                <div className="mt-6 flex justify-end gap-3">
                  <Button variant="primary" onClick={() => { setShowRestartDialog(false); setRestartError(null); setPendingHardwareMode(null); }}>Close</Button>
                </div>
              </div>
            ) : (
              <>
                <div className="mb-1 flex items-center gap-2.5">
                  <RefreshCw size={18} className="text-[var(--color-accent)]" />
                  <h2 className="text-lg font-semibold text-[var(--color-text)]">Restart required</h2>
                </div>
                <p className="text-sm text-[var(--color-text-muted)]">
                  Changing transcription hardware requires restarting MeetNote.
                </p>

                <div className="mt-5 rounded-lg bg-[var(--color-surface-1)] p-4 text-sm">
                  <div className="flex justify-between mb-3 border-b border-[var(--color-border-subtle)] pb-3">
                    <span className="text-[var(--color-text-muted)]">Current mode</span>
                    <span className="font-medium text-[var(--color-text)]">
                      {HARDWARE_LABEL[health?.whisper?.active_hardware_preference ?? "automatic"]}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--color-text-muted)]">New mode</span>
                    <span className="font-medium text-[var(--color-text)]">
                      {HARDWARE_LABEL[pendingHardwareMode ?? "automatic"]}
                    </span>
                  </div>
                </div>

                <div className="mt-6 flex justify-end gap-3">
                  <Button variant="secondary" onClick={cancelRestart}>Cancel</Button>
                  <Button variant="primary" onClick={confirmRestart}>Restart Now</Button>
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
