import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { ArrowRight, Cpu, RefreshCw } from "lucide-react";
import { Button, Card, HealthRow, SectionLabel } from "../components/ui";
import { ProviderStatusRow } from "../components/ProviderStatusRow";
import { engineClient } from "../services/engineClient";
import { useMeetingStore } from "../stores/meetingStore";
import { useUIStore } from "../stores/uiStore";
import type { HealthResponse, NoteTemplate, AIProviderStatus } from "../types/engine";

function getAiStatusMessage(ai: AIProviderStatus | null | undefined): React.ReactNode {
  if (!ai) return (
    <>
      No AI provider is configured.<br />
      Meetings will still record and transcribe locally.<br />
      AI notes will remain pending until Gemini or Groq is configured.
    </>
  );

  const gOk = ai.gemini.status === "configured";
  const qOk = ai.groq.status === "configured";
  const gNotConf = ai.gemini.status === "not_configured";
  const qNotConf = ai.groq.status === "not_configured";

  if (gNotConf && qNotConf) {
    return (
      <>
        No AI provider is configured.<br />
        Meetings will still record and transcribe locally.<br />
        AI notes will remain pending until Gemini or Groq is configured.
      </>
    );
  }

  if (!gOk && !qOk) {
    return (
      <>
        No AI provider is currently available.<br />
        Meetings will still record and transcribe locally.
      </>
    );
  }

  if (!gOk && qOk && !gNotConf) {
    return "Gemini is unavailable. Groq will be used for AI notes.";
  }

  if (gOk && !qOk && !qNotConf) {
    return "Gemini is available. Groq is unavailable.";
  }

  if (gOk && qOk) {
    return (
      <>
        Gemini will be used as the primary AI provider.<br/>
        Groq will be used as the fallback if Gemini is unavailable.
      </>
    );
  }

  if (gOk) {
    return "Gemini is configured and will be used for AI note generation.";
  }
  
  if (qOk) {
    return "Groq is configured and will be used for AI note generation.";
  }

  return null;
}

function getRoutingMessage(ai: AIProviderStatus | null | undefined): string {
  if (!ai) return "Unavailable";
  const gOk = ai.gemini.status === "configured";
  const qOk = ai.groq.status === "configured";
  const gNotConf = ai.gemini.status === "not_configured";
  const qNotConf = ai.groq.status === "not_configured";

  if (gNotConf && qNotConf) return "Unavailable";
  if (!gOk && !qOk) return "Unavailable";
  if (gOk && qOk) return "Gemini → Groq fallback";
  if (gOk && !qOk && !qNotConf) return "Gemini";
  if (!gOk && qOk && !gNotConf) return "Groq";
  if (gOk) return "Gemini";
  if (qOk) return "Groq";
  
  return "Unavailable";
}

export function NewMeeting() {
  const navigate = useUIStore((s) => s.navigate);
  const start = useMeetingStore((s) => s.start);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [templates, setTemplates] = useState<NoteTemplate[]>([]);
  const [title, setTitle] = useState("");
  const [templateId, setTemplateId] = useState("standard");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const h = await engineClient.health();
        if (cancelled) return;
        setHealth(h);
        if (h.whisper.loading) {
          timer = setTimeout(poll, 1500);
        }
      } catch {
        if (!cancelled) timer = setTimeout(poll, 2000);
      }
    }
    poll();

    engineClient.listTemplates().then((t) => {
      if (cancelled) return;
      setTemplates(t);
      if (t.length && !t.find((x) => x.id === "standard")) setTemplateId(t[0].id);
    });

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  const whisperReady = !!health?.whisper.loaded;
  const restartRequired = !!health?.whisper?.restart_required;
  const canStart = whisperReady && title.trim().length > 0 && !starting && !restartRequired;

  async function handleStart() {
    setStarting(true);
    setError(null);
    try {
      await start(title.trim(), templateId);
      navigate({ name: "meeting" });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStarting(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl px-8 py-10">
      <h1 className="text-xl font-semibold text-[var(--color-text)]">New Meeting</h1>
      <p className="mt-1 text-sm text-[var(--color-text-muted)]">
        MeetNote checks everything automatically. You don&rsquo;t need to configure anything below.
      </p>

      <Card className="mt-6 p-5">
        <label className="block text-xs font-medium text-[var(--color-text-muted)]">Meeting title</label>
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. House Coordination Meeting"
          className="mt-1.5 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-accent)]"
        />

        <label className="mt-4 block text-xs font-medium text-[var(--color-text-muted)]">Note template</label>
        <select
          value={templateId}
          onChange={(e) => setTemplateId(e.target.value)}
          className="mt-1.5 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-accent)]"
        >
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </Card>

      <Card className="mt-4 p-5">
        <SectionLabel>System health</SectionLabel>
        <HealthRow label="Operating System" ok detail={health?.os} />
        <HealthRow
          label="Microphone"
          ok={!!health?.audio_devices.microphone_ok}
          detail={health?.audio_devices.microphone_name ?? undefined}
        />
        <HealthRow
          label="System Audio"
          ok={!!health?.audio_devices.system_audio_ok}
          detail={health?.audio_devices.system_audio_name ?? undefined}
        />
        <HealthRow
          label="Whisper"
          ok={whisperReady}
          pending={health?.whisper.loading}
          detail={
            health?.whisper.loading
              ? "Loading model…"
              : health?.whisper.error
                ? health.whisper.error
                : health?.transcription_mode?.model_size
          }
        />
        <HealthRow
          label="GPU / CUDA"
          ok={!!health?.hardware?.cuda_usable}
          detail={health?.hardware?.cuda_usable ? health?.hardware?.gpu_name ?? undefined : "CPU mode"}
        />
        <HealthRow label="Local Storage" ok={!!health?.storage.ok} />
        <ProviderStatusRow label="Groq API" provider={health?.ai_providers?.groq} />
        <ProviderStatusRow label="Gemini API" provider={health?.ai_providers?.gemini} />

        <div className="flex items-center justify-between py-2 border-b border-[var(--color-border)] last:border-b-0">
          <div className="flex items-center gap-2.5">
            <span className="text-sm font-medium text-[var(--color-text)]">AI notes</span>
          </div>
          <div className="text-right text-xs text-[var(--color-text-muted)]">
            {getRoutingMessage(health?.ai_providers)}
          </div>
        </div>

        {health?.transcription_mode && (
          <div className="mt-3 flex items-center gap-2 rounded-lg bg-[var(--color-surface-2)] px-3 py-2 text-xs text-[var(--color-text-muted)]">
            <Cpu size={14} />
            Whisper will run in{" "}
            <span className="font-medium text-[var(--color-text)]">
              {health.transcription_mode.device === "cuda" ? "GPU" : "CPU"} mode
            </span>{" "}
            ({health.transcription_mode.model_size}, {health.transcription_mode.compute_type})
          </div>
        )}

        <p className="mt-3 text-xs text-[var(--color-text-faint)] leading-relaxed">
          {getAiStatusMessage(health?.ai_providers)}
        </p>
      </Card>

      {error && <p className="mt-3 text-sm text-[var(--color-danger)]">{error}</p>}

      {restartRequired ? (
        <div className="mt-6 flex flex-col items-end gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-4">
          <span className="text-sm font-medium text-amber-500">
            Restart required before starting a meeting.
          </span>
          <Button variant="primary" onClick={() => invoke("restart_app")}>
            <RefreshCw size={16} className="mr-2" />
            Restart Now
          </Button>
        </div>
      ) : (
        <div className="mt-6 flex justify-end">
          <Button variant="primary" disabled={!canStart} onClick={handleStart}>
            {starting ? "Starting…" : "Start Meeting"}
            <ArrowRight size={16} />
          </Button>
        </div>
      )}
    </div>
  );
}
