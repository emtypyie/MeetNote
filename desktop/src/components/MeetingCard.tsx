import { FileText, Sparkles } from "lucide-react";
import { Badge, Card } from "./ui";
import { formatDate, formatDuration } from "../lib/format";
import type { MeetingSummary } from "../types/engine";
import { useUIStore } from "../stores/uiStore";

function notesBadge(status: string) {
  if (status === "completed") return <Badge tone="success">Notes ready</Badge>;
  if (status === "pending") return <Badge tone="warning">Notes pending</Badge>;
  if (status === "failed") return <Badge tone="danger">Notes failed</Badge>;
  if (status === "generating_notes" || status === "generating") return <Badge tone="warning">Generating…</Badge>;
  return <Badge tone="neutral">Not started</Badge>;
}

export function MeetingCard({ meeting }: { meeting: MeetingSummary }) {
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
    </Card>
  );
}
