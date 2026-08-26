import { useEffect, useState } from "react";
import { ArrowRight, Cpu } from "lucide-react";
import { Button, Card, HealthRow, SectionLabel } from "../components/ui";
import { ProviderStatusRow } from "../components/ProviderStatusRow";
import { engineClient } from "../services/engineClient";
import { useMeetingStore } from "../stores/meetingStore";
import { useUIStore } from "../stores/uiStore";
import type { HealthResponse, NoteTemplate } from "../types/engine";

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
  const canStart = whisperReady && title.trim().length > 0 && !starting;

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
        <ProviderStatusRow label="Groq API" provider={health?.ai_providers?.primary} />
        <ProviderStatusRow label="Gemini API" provider={health?.ai_providers?.fallback} />

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

        {!health?.ai_providers?.primary.configured && !health?.ai_providers?.fallback.configured && (
          <p className="mt-3 text-xs text-[var(--color-text-faint)]">
            No AI provider is configured yet, so the meeting will still record and transcribe locally —
            AI notes generation will be marked pending until a Groq or Gemini key is added in Settings.
          </p>
        )}
      </Card>

      {error && <p className="mt-3 text-sm text-[var(--color-danger)]">{error}</p>}

      <div className="mt-6 flex justify-end">
        <Button variant="primary" disabled={!canStart} onClick={handleStart}>
          {starting ? "Starting…" : "Start Meeting"}
          <ArrowRight size={16} />
        </Button>
      </div>
    </div>
  );
}
