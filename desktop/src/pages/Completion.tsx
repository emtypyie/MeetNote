import { useEffect, useRef, useState } from "react";
import { Check, Clock, Copy, FileDown, FileText, FolderOpen, RotateCw, X } from "lucide-react";
import { openPath } from "@tauri-apps/plugin-opener";
import { Badge, Button, Card } from "../components/ui";
import { engineClient } from "../services/engineClient";
import { useUIStore } from "../stores/uiStore";
import { formatDate, formatDuration } from "../lib/format";
import type { MeetingDetail } from "../types/engine";

const GENERATING_STATUSES = new Set(["generating_notes", "finalizing"]);

export function Completion({ meetingId }: { meetingId: string }) {
  const navigate = useUIStore((s) => s.navigate);
  const [detail, setDetail] = useState<MeetingDetail | null>(null);
  const [notesText, setNotesText] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  async function load() {
    const d = await engineClient.getMeeting(meetingId);
    setDetail(d);
    if (d.metadata.notes_status === "completed") {
      const { text } = await engineClient.notesText(meetingId);
      setNotesText(text);
    }
    const stillWorking = GENERATING_STATUSES.has(d.metadata.status) || d.metadata.notes_status === "not_started";
    if (stillWorking) {
      pollRef.current = setTimeout(load, 2000);
    }
  }

  useEffect(() => {
    load();
    return () => clearTimeout(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId]);

  async function retry() {
    setRetrying(true);
    try {
      await engineClient.retryGenerateNotes(meetingId);
      await load();
    } finally {
      setRetrying(false);
    }
  }

  async function openNotes() {
    const { path } = await engineClient.exportPath(meetingId, "md");
    await openPath(path);
  }

  async function openDocx() {
    const { path } = await engineClient.exportPath(meetingId, "docx");
    await openPath(path);
  }

  async function openTranscript() {
    const { path } = await engineClient.transcriptPath(meetingId);
    await openPath(path);
  }

  async function copyNotes() {
    if (!notesText) return;
    await navigator.clipboard.writeText(notesText);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  if (!detail) {
    return <div className="px-8 py-10 text-sm text-[var(--color-text-muted)]">Loading…</div>;
  }

  const { metadata } = detail;
  const notesStatus = metadata.notes_status;
  const generating = GENERATING_STATUSES.has(metadata.status) || notesStatus === "not_started";
  const notesOk = notesStatus === "completed";
  const notesFailed = notesStatus === "pending" || notesStatus === "failed";
  const providerLabel =
    metadata.ai_provider_used === "gemini"
      ? "Gemini (fallback)"
      : metadata.ai_provider_used === "groq"
        ? "Groq"
        : null;

  return (
    <div className="mx-auto max-w-2xl px-8 py-10">
      <h1 className="text-xl font-semibold text-[var(--color-text)]">
        {metadata.status === "completed" && !generating ? "Meeting Complete" : "Finishing Up"}
      </h1>
      <p className="mt-1 text-sm text-[var(--color-text-muted)]">
        {metadata.title} · {formatDate(metadata.started_at)} · {formatDuration(metadata.duration_seconds)}
      </p>

      <Card className="mt-6 divide-y divide-[var(--color-border)] p-0">
        <StatusRow label="Transcript" ok icon={FileText} detail="Saved locally" />
        <StatusRow
          label="AI Analysis"
          ok={notesOk}
          pending={generating}
          failed={notesFailed}
          icon={Clock}
          detail={
            generating
              ? "Generating…"
              : notesOk
                ? providerLabel ?? "Completed"
                : notesFailed
                  ? "Pending — AI provider unavailable"
                  : "Not started"
          }
        />
        <StatusRow
          label="Notes"
          ok={notesOk}
          pending={generating}
          failed={notesFailed}
          icon={FileText}
          detail={notesOk ? "Generated" : generating ? "Waiting on AI analysis" : "Not generated"}
        />
      </Card>

      {notesFailed && (
        <div className="mt-4 flex items-center justify-between rounded-lg border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/10 px-4 py-3">
          <p className="text-xs text-[var(--color-text-muted)]">
            The transcript is safe. AI notes could not be generated — check your internet connection or
            add a Groq/Gemini key in Settings, then retry.
          </p>
          <Button variant="secondary" size="sm" onClick={retry} disabled={retrying}>
            <RotateCw size={13} className={retrying ? "animate-spin" : undefined} />
            Retry Analysis
          </Button>
        </div>
      )}

      {metadata.validation_warnings.length > 0 && notesOk && (
        <div className="mt-4 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-4 py-3 text-xs text-[var(--color-text-muted)]">
          <span className="font-medium text-[var(--color-text)]">Review suggested: </span>
          {metadata.validation_warnings.join(" · ")}
        </div>
      )}

      {notesOk && notesText && (
        <Card className="mt-4 max-h-72 overflow-y-auto p-4">
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-[var(--color-text)]">
            {notesText}
          </pre>
        </Card>
      )}

      <div className="mt-6 flex flex-wrap gap-2">
        <Button variant="primary" onClick={openNotes} disabled={!notesOk}>
          <FileText size={15} />
          Open Notes
        </Button>
        <Button variant="secondary" onClick={openDocx} disabled={!notesOk}>
          <FileDown size={15} />
          Export DOCX
        </Button>
        <Button variant="secondary" onClick={copyNotes} disabled={!notesOk}>
          {copied ? <Check size={15} /> : <Copy size={15} />}
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button variant="secondary" onClick={openTranscript}>
          <FolderOpen size={15} />
          Open Transcript
        </Button>
        <Button variant="ghost" onClick={() => navigate({ name: "dashboard" })} className="ml-auto">
          <X size={15} />
          Done
        </Button>
      </div>
    </div>
  );
}

function StatusRow({
  label,
  ok,
  pending,
  failed,
  icon: Icon,
  detail,
}: {
  label: string;
  ok: boolean;
  pending?: boolean;
  failed?: boolean;
  icon: typeof Clock;
  detail: string;
}) {
  return (
    <div className="flex items-center justify-between px-5 py-3.5">
      <div className="flex items-center gap-2.5">
        <Icon size={15} className="text-[var(--color-text-faint)]" />
        <span className="text-sm font-medium text-[var(--color-text)]">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-[var(--color-text-muted)]">{detail}</span>
        {ok && <Badge tone="success">Done</Badge>}
        {!ok && pending && <Badge tone="warning">Working</Badge>}
        {!ok && !pending && failed && <Badge tone="danger">Pending</Badge>}
      </div>
    </div>
  );
}
