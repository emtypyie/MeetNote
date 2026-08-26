import { useEffect, useState } from "react";
import { FolderOpen } from "lucide-react";
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

  useEffect(() => {
    engineClient.getConfig().then(setConfig);
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
    const updated = await engineClient.patchConfig(patch);
    setConfig(updated);
    setSaved(true);
    setTimeout(() => setSaved(false), 1200);
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
            min={10}
            max={60}
            value={config.audio.chunk_seconds}
            onChange={(e) =>
              save({ audio: { ...config.audio, chunk_seconds: Number(e.target.value) } })
            }
            className={selectClass}
          />
        </Field>
      </Card>

      <Card className="mt-4 p-5">
        <SectionLabel>Transcription</SectionLabel>
        <HealthRow label="Operating System" ok detail={health?.os} />
        <HealthRow label="CPU" ok detail={hw ? `${hw.cpu_model} (${hw.cpu_logical} threads)` : undefined} />
        <HealthRow label="RAM" ok detail={hw ? `${hw.ram_total_gb.toFixed(1)} GB` : undefined} />
        <HealthRow label="GPU" ok={!!hw?.gpu_name} detail={hw?.gpu_name ?? "None detected"} />
        <HealthRow label="VRAM" ok={!!hw?.gpu_vram_mb} detail={hw?.gpu_vram_mb ? `${hw.gpu_vram_mb} MB` : "—"} />
        <HealthRow
          label="CUDA"
          ok={!!hw?.cuda_usable}
          detail={hw?.cuda_usable ? "Usable" : hw?.cuda_failure_reason ?? "Unavailable"}
        />
        <HealthRow label="Whisper Model" ok detail={mode?.model_size} />
        <HealthRow label="Compute Type" ok detail={mode?.compute_type} />
        <HealthRow label="Current Mode" ok detail={mode ? `${mode.device.toUpperCase()} — ${mode.label}` : undefined} />
        <p className="mt-2 text-xs text-[var(--color-text-faint)]">
          Hardware detection and model selection are automatic. Manual overrides are planned but not
          implemented in this version.
        </p>
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
        <p className="mt-3 text-xs text-[var(--color-text-faint)]">
          Retention limits and cache clearing are planned but not implemented in this version — meetings
          are kept until you delete their folder yourself.
        </p>
      </Card>
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
