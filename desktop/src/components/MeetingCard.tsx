import { useState } from "react";
import { Check, Copy, FileText, Sparkles, Trash2, FolderOpen } from "lucide-react";
import { Badge, Card, Button } from "./ui";
import { formatDate, formatDuration } from "../lib/format";
import type { MeetingSummary } from "../types/engine";
import { useUIStore } from "../stores/uiStore";
import { engineClient } from "../services/engineClient";

function notesBadge(status: string) {
  if (status === "completed") return <Badge tone="success">Notes ready</Badge>;
  if (status === "pending") return <Badge tone="warning">Notes pending</Badge>;
  if (status === "failed") return <Badge tone="danger">Notes failed</Badge>;
  if (status === "generating_notes" || status === "generating") return <Badge tone="warning">Generating…</Badge>;
  return <Badge tone="neutral">Not started</Badge>;
}

export function MeetingCard({ meeting, onDelete }: { meeting: MeetingSummary; onDelete?: (id: string) => void }) {
  const navigate = useUIStore((s) => s.navigate);
  const isIncomplete = meeting.status === "error" || meeting.status === "recording" || meeting.status === "paused";

  return (
    <Card
      onClick={() => navigate({ name: "completion", meetingId: meeting.meeting_id })}
      className="cursor-pointer p-4 transition-colors hover:border-[var(--color-border-strong)]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-[14px] font-medium text-[var(--color-text)]">{meeting.title}</h3>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            {formatDate(meeting.started_at)} · {formatDuration(meeting.duration_seconds)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 text-[var(--color-text-faint)]">
          <FileText size={14} />
          <Sparkles size={14} />
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {isIncomplete ? (
          <Badge tone="danger">Incomplete</Badge>
        ) : (
          <Badge tone="success">Transcript saved</Badge>
        )}
        {notesBadge(meeting.notes_status)}
        {meeting.ai_provider_used && (
          <Badge tone="neutral">
            {meeting.ai_provider_used === "gemini" ? "Gemini fallback" : "Groq"}
          </Badge>
        )}
      </div>

      <MeetingActions meeting={meeting} navigate={navigate} onDelete={onDelete} />
    </Card>
  );
}

function MeetingActions({ meeting, navigate, onDelete }: { meeting: MeetingSummary; navigate: any; onDelete?: (id: string) => void }) {
  const [copied, setCopied] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const isIncomplete = meeting.status === "error" || meeting.status === "recording" || meeting.status === "paused";

  const handleOpen = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate({ name: "completion", meetingId: meeting.meeting_id });
  };

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (meeting.notes_status !== "completed") return;
    try {
      const res = await engineClient.notesText(meeting.meeting_id);
      if (res.text) {
        await navigator.clipboard.writeText(res.text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch (err) {
      console.error("Failed to copy notes", err);
    }
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setShowConfirm(true);
  };

  const cancelDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    setShowConfirm(false);
    setDeleteError(null);
  };

  const confirmDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isIncomplete) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      const res = await engineClient.deleteMeeting(meeting.meeting_id);
      if (res.success) {
        setShowConfirm(false);
        if (onDelete) onDelete(meeting.meeting_id);
      } else {
        setDeleteError("Could not delete this meeting. Your meeting data has not been intentionally removed.");
      }
    } catch (err) {
      setDeleteError("Could not delete this meeting. Your meeting data has not been intentionally removed.");
    } finally {
      setIsDeleting(false);
    }
  };

  if (showConfirm) {
    return (
      <div className="mt-4 rounded-md border border-[var(--color-danger)] bg-red-50/50 p-3 dark:bg-red-950/20" onClick={(e) => e.stopPropagation()}>
        <p className="mb-2 text-sm font-semibold text-[var(--color-danger)]">Delete meeting?</p>
        <p className="mb-1 text-sm text-[var(--color-text)] font-medium">"{meeting.title}"</p>
        <p className="mb-4 text-xs text-[var(--color-text-muted)]">
          This will permanently delete the meeting, transcript, notes, and associated files.<br />
          This action cannot be undone.
        </p>
        {deleteError && (
          <p className="mb-3 text-xs text-[var(--color-danger)]">{deleteError}</p>
        )}
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={cancelDelete} disabled={isDeleting}>Cancel</Button>
          <Button variant="danger" size="sm" onClick={confirmDelete} disabled={isDeleting}>
            {isDeleting ? "Deleting..." : "Delete"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-4 flex gap-2" onClick={(e) => e.stopPropagation()}>
      <Button variant="secondary" size="sm" onClick={handleOpen}>
        <FolderOpen size={14} /> Open
      </Button>
      <Button variant="secondary" size="sm" onClick={handleCopy} disabled={meeting.notes_status !== "completed"}>
        {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? "Copied" : "Copy"}
      </Button>
      <div className="flex-1" />
      <Button variant="danger" size="sm" onClick={handleDeleteClick} disabled={isIncomplete} aria-label="Delete meeting">
        <Trash2 size={14} /> Delete
      </Button>
    </div>
  );
}
