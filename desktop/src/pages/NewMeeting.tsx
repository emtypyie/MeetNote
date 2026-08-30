import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, ClipboardList, Cpu, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { Button, Card, HealthRow, SectionLabel, Select } from "../components/ui";
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
  const gChecking = ai.gemini.status === "checking";
  const qChecking = ai.groq.status === "checking";

  if (gChecking || qChecking) {
    return "Checking AI provider status...";
  }

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
  const gChecking = ai.gemini.status === "checking";
  const qChecking = ai.groq.status === "checking";

  if (gChecking || qChecking) return "Checking...";
  if (gNotConf && qNotConf) return "Unavailable";
  if (!gOk && !qOk) return "Unavailable";
  if (gOk && qOk) return "Gemini primary, Groq fallback";
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
      } catch {
        // Ignore fetch errors to keep polling alive
      } finally {
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

  let btnText = "Start Meeting";
  let audioMissing = false;
  if (health) {
    audioMissing = !health.audio_devices.microphone_ok && !health.audio_devices.system_audio_ok;
  }
  
  if (!health) btnText = "Checking...";
  else if (starting) btnText = "Starting...";
  else if (audioMissing) btnText = "Audio unavailable";
  else if (health.whisper.error) btnText = "Transcription Error";
  else if (health.whisper.loading) btnText = "Preparing transcription...";

  const restartRequired = !!health?.whisper?.restart_required;

  const canStart = title.trim().length > 0 &&
                   !starting &&
                   !restartRequired &&
                   !health?.whisper.error &&
                   health !== null &&
                   !audioMissing;

  const systemReady =
    !!health && !restartRequired && !health.whisper.error && !health.whisper.loading && !audioMissing;

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
    <div className="mx-auto max-w-6xl px-10 py-10">
      <h1 className="text-xl font-semibold text-[var(--color-text)]">New Meeting</h1>
      <p className="mt-1 text-sm text-[var(--color-text-muted)]">
        MeetNote checks everything automatically. You don&rsquo;t need to configure anything below.
      </p>

      <div className="mt-6 grid grid-cols-1 items-start gap-6 lg:grid-cols-[380px_minmax(0,1fr)]">
        <Card className="p-5">
          <SectionLabel icon={ClipboardList}>Meeting details</SectionLabel>
          <label className="block text-xs font-medium text-[var(--color-text-muted)]">Meeting title</label>
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. House Coordination Meeting"
            className="mt-1.5 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-accent)]"
          />

          <label className="mt-4 block text-xs font-medium text-[var(--color-text-muted)]">Note template</label>
          <div className="mt-1.5">
            <Select
              value={templateId}
              onChange={(val) => setTemplateId(val)}
              options={templates.map((t) => ({ value: t.id, label: t.name }))}
            />
          </div>

          {health?.transcription_mode && (
            <div className="mt-5 flex items-center gap-2 rounded-lg bg-[var(--color-surface-2)] px-3 py-2 text-xs text-[var(--color-text-muted)]">
              <Cpu size={14} className="shrink-0" />
              <span>
                Whisper will run in{" "}
                <span className="font-medium text-[var(--color-text)]">
                  {health.transcription_mode.device === "cuda" ? "GPU" : "CPU"} mode
                </span>{" "}
                ({health.transcription_mode.model_size}, {health.transcription_mode.compute_type})
              </span>
            </div>
          )}
        </Card>

        <div className="flex flex-col gap-4">
          <Card className="p-5">
            <SectionLabel icon={Activity}>System health</SectionLabel>

            <div
              className={`mb-4 flex items-center gap-2.5 rounded-lg px-3 py-2.5 ${
                !health
                  ? "bg-[var(--color-surface-2)]"
                  : systemReady
                    ? "bg-[var(--color-success-soft)]"
                    : "bg-[var(--color-warning-soft)]"
              }`}
            >
              {!health ? (
                <Loader2 size={16} className="animate-spin text-[var(--color-text-faint)]" />
              ) : systemReady ? (
                <CheckCircle2 size={16} className="text-[var(--color-success)]" />
              ) : (
                <AlertTriangle size={16} className="text-[var(--color-warning)]" />
              )}
              <span
                className={`text-sm font-semibold ${
                  !health ? "text-[var(--color-text-muted)]" : systemReady ? "text-[var(--color-success)]" : "text-[var(--color-warning)]"
                }`}
              >
                {!health ? "Checking system…" : systemReady ? "Ready to record" : "Not ready yet"}
              </span>
            </div>

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
              ok={!!health?.whisper.loaded}
              pending={health?.whisper.loading}
              detail={
                health?.whisper.loading
                  ? "Loading model…"
                  : health?.whisper.error
                    ? health.whisper.error
                    : health?.transcription_mode?.model_size
                      ? `${health.transcription_mode.model_size}`
                      : undefined
              }
            />
            <HealthRow
              label="GPU / CUDA"
              ok={!!health?.hardware?.cuda_usable}
              detail={health?.hardware?.cuda_usable ? health?.hardware?.gpu_name ?? undefined : "CPU mode"}
            />
            <HealthRow label="Local Storage" ok={!!health?.storage.ok} />
          </Card>

          <Card className="p-5">
            <SectionLabel icon={Sparkles}>AI providers</SectionLabel>
            <ProviderStatusRow label="Gemini" provider={health?.ai_providers?.gemini} />
            <ProviderStatusRow label="Groq" provider={health?.ai_providers?.groq} />

            <div className="flex items-center justify-between py-2 border-b border-[var(--color-border)] last:border-b-0">
              <span className="text-sm font-medium text-[var(--color-text)]">AI notes</span>
              <span className="text-right text-xs text-[var(--color-text-muted)]">
                {getRoutingMessage(health?.ai_providers)}
              </span>
            </div>

            <p className="mt-3 text-xs text-[var(--color-text-faint)] leading-relaxed">
              {getAiStatusMessage(health?.ai_providers)}
            </p>
          </Card>

          {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}

          {restartRequired ? (
            <div className="flex flex-col items-end gap-3 rounded-lg bg-[var(--color-warning-soft)] p-4">
              <span className="flex items-center gap-2 text-sm font-medium text-[var(--color-warning)]">
                <AlertTriangle size={15} className="shrink-0" />
                Restart required before starting a meeting.
              </span>
              <Button variant="primary" onClick={() => invoke("restart_app")}>
                <RefreshCw size={16} />
                Restart Now
              </Button>
            </div>
          ) : (
            <div className="flex justify-end">
              <Button variant="primary" disabled={!canStart} loading={starting} onClick={handleStart}>
                {btnText}
                {!starting && <ArrowRight size={16} />}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
