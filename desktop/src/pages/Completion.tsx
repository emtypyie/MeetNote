import { useEffect, useRef, useState } from "react";
import { Check, Clock, Copy, FileText, Loader2, RotateCw, X, Trash2 } from "lucide-react";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import { invoke } from "@tauri-apps/api/core";
import { Badge, Button, Card, SectionLabel } from "../components/ui";
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
  const [copyError, setCopyError] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [openingNotes, setOpeningNotes] = useState(false);

  const [showConfirm, setShowConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  async function load() {
    try {
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
    } catch (err: unknown) {
      const msg = String((err as { message?: string })?.message ?? err);
      if (msg.includes("404") || msg.toLowerCase().includes("not found")) {
        setNotFound(true);
      }
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

  async function copyNotes() {
    setCopyError(null);
    if (!notesText) {
      setCopyError("Meeting summary is not available yet.");
      return;
    }
    try {
      await writeText(notesText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      console.error("copyNotes failed:", err);
      setCopyError("Could not copy the summary to the clipboard.");
    }
  }

  async function openNotes() {
    setOpenError(null);
    if (!notesText) {
      setOpenError("Meeting summary is not available yet.");
      return;
    }
    setOpeningNotes(true);
    try {
      // Ask the engine to ensure notes.txt exists (generates it from notes.md
      // if missing) and return its verified filesystem path.
      const { path } = await engineClient.exportPath(meetingId, "txt");
      // Opens the plain-text notes file in the OS's plain-text editor
      // (Notepad on Windows, TextEdit on macOS, xdg-open on Linux — see
      // open_in_notepad in desktop/src-tauri/src/lib.rs), not whatever
      // application is associated with .txt files by default.
      await invoke<void>("open_in_notepad", { path });
    } catch (err) {
      console.error("openNotes failed:", err);
      setOpenError("Could not open notes. " + String(err));
    } finally {
      setOpeningNotes(false);
    }
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-2xl px-8 py-16 text-center">
        <p className="mb-1 text-base font-medium text-[var(--color-text)]">This meeting no longer exists.</p>
        <p className="mb-6 text-sm text-[var(--color-text-muted)]">It may have been deleted.</p>
        <Button variant="secondary" onClick={() => navigate({ name: "dashboard" })}>Back to Dashboard</Button>
      </div>
    );
  }

  if (!detail) {
    return <div className="px-8 py-10 text-sm text-[var(--color-text-muted)]">Loading meeting…</div>;
  }

  const { metadata } = detail;
  const notesStatus = metadata.notes_status;
  const generating = GENERATING_STATUSES.has(metadata.status) || notesStatus === "not_started";
  const notesOk = notesStatus === "completed";
  const notesFailed = notesStatus === "pending" || notesStatus === "failed";
  const providerLabel =
    metadata.ai_provider_used === "gemini"
      ? "Gemini"
      : metadata.ai_provider_used === "groq"
        ? "Groq"
        : null;

  return (
    <div className="mx-auto max-w-5xl px-10 py-10">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[var(--color-text)]">
            {metadata.status === "completed" && !generating ? "Meeting Complete" : "Finishing Up"}
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            {metadata.title} · {formatDate(metadata.started_at)} · {formatDuration(metadata.duration_seconds)}
          </p>
        </div>
        <Button variant="ghost" onClick={() => navigate({ name: "dashboard" })}>
          <X size={15} />
          Done
        </Button>
      </div>

      <div className="mt-6 grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div>
          <SectionLabel icon={FileText}>Summary</SectionLabel>
          {notesOk && notesText && (
            <Card className="max-h-[32rem] overflow-y-auto p-4">
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-[var(--color-text)]">
                {notesText}
              </pre>
            </Card>
          )}

          {!notesOk && !generating && (
            <Card variant="quiet" className="flex flex-col items-center gap-1 py-10 text-center">
              <p className="text-sm text-[var(--color-text-muted)]">Meeting summary is not available yet.</p>
            </Card>
          )}

          {generating && (
            <Card variant="quiet" className="flex flex-col items-center gap-2 py-10 text-center">
              <Loader2 size={18} className="animate-spin text-[var(--color-text-faint)]" />
              <p className="text-sm text-[var(--color-text-muted)]">Generating meeting notes…</p>
              <p className="text-xs text-[var(--color-text-faint)]">This usually takes a few seconds.</p>
            </Card>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <div>
            <SectionLabel>Status</SectionLabel>
            <Card className="divide-y divide-[var(--color-border-subtle)] p-0">
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
                        ? "Pending: AI provider unavailable"
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
          </div>

          {notesFailed && (
            <div className="flex flex-col gap-2 rounded-lg bg-[var(--color-warning-soft)] px-4 py-3">
              <p className="text-xs text-[var(--color-text-muted)]">
                The transcript is safe. AI notes could not be generated. Check your internet connection,
                or add a Groq/Gemini key in Settings, then retry.
              </p>
              <Button variant="secondary" size="sm" onClick={retry} loading={retrying} className="self-start">
                {!retrying && <RotateCw size={13} />}
                Retry Analysis
              </Button>
            </div>
          )}

          {metadata.validation_warnings.length > 0 && notesOk && (
            <div className="rounded-lg bg-[var(--color-surface-2)] px-4 py-3 text-xs text-[var(--color-text-muted)]">
              <span className="font-medium text-[var(--color-text)]">Review suggested: </span>
              {metadata.validation_warnings.join(" · ")}
            </div>
          )}

          {copyError && (
            <div className="rounded-lg bg-[var(--color-warning-soft)] px-4 py-3 text-xs text-[var(--color-text-muted)]">
              {copyError}
            </div>
          )}

          {openError && (
            <div className="rounded-lg bg-[var(--color-warning-soft)] px-4 py-3 text-xs text-[var(--color-text-muted)]">
              {openError}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={copyNotes} disabled={!notesOk || !notesText}>
              {copied ? <Check size={15} /> : <Copy size={15} />}
              {copied ? "Copied" : "Copy Summary"}
            </Button>
            <Button variant="secondary" onClick={openNotes} disabled={!notesOk} loading={openingNotes}>
              {!openingNotes && <FileText size={15} />}
              {openingNotes ? "Opening" : "Open Notes"}
            </Button>
            <Button variant="danger" onClick={() => setShowConfirm(true)}>
              <Trash2 size={15} />
              Delete Meeting
            </Button>
          </div>

          {showConfirm && (
            <div className="rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-soft)] p-5">
              <p className="mb-1 text-sm font-semibold text-[var(--color-danger)]">Delete meeting?</p>
              <p className="mb-1 text-sm text-[var(--color-text)] font-medium">&ldquo;{metadata.title}&rdquo;</p>
              <p className="mb-4 text-xs text-[var(--color-text-muted)]">
                This will permanently delete this meeting, including its transcript, summary, notes,
                and associated files. This action cannot be undone.
              </p>
              {deleteError && (
                <p className="mb-3 text-xs text-[var(--color-danger)]">{deleteError}</p>
              )}
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" onClick={() => { setShowConfirm(false); setDeleteError(null); }} disabled={isDeleting}>Cancel</Button>
                <Button variant="danger" size="sm" onClick={async () => {
                  setIsDeleting(true);
                  setDeleteError(null);
                  try {
                    const res = await engineClient.deleteMeeting(meetingId);
                    if (res.success) {
                      navigate({ name: "dashboard", flashMessage: "Meeting deleted." });
                    } else {
                      setDeleteError("Could not delete this meeting. Your meeting data has not been removed.");
                    }
                  } catch (err: unknown) {
                    const msg = String((err as { message?: string })?.message ?? err);
                    if (msg.toLowerCase().includes("active")) {
                      setDeleteError("This meeting is still active and cannot be deleted.");
                    } else {
                      setDeleteError("Could not delete this meeting. Your meeting data has not been removed.");
                    }
                  } finally {
                    setIsDeleting(false);
                  }
                }} loading={isDeleting}>
                  Delete Meeting
                </Button>
              </div>
            </div>
          )}
        </div>
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
