import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Button, Card } from "./ui";
import { engineClient } from "../services/engineClient";
import { useMeetingStore } from "../stores/meetingStore";
import { useUIStore } from "../stores/uiStore";
import type { MeetingMetadata } from "../types/engine";

export function RecoveryModal({
  meetings,
  onResolved,
}: {
  meetings: MeetingMetadata[];
  onResolved: () => void;
}) {
  const [busyAction, setBusyAction] = useState<"resume" | "startNew" | null>(null);
  const meeting = meetings[0];
  const navigate = useUIStore((s) => s.navigate);
  const hydrate = useMeetingStore((s) => s.hydrateFromCurrent);

  if (!meeting) return null;

  async function resume() {
    setBusyAction("resume");
    try {
      await engineClient.resumeAfterRestart(meeting.meeting_id);
      await hydrate();
      navigate({ name: "meeting" });
      onResolved();
    } finally {
      setBusyAction(null);
    }
  }

  async function startNew() {
    setBusyAction("startNew");
    try {
      await engineClient.abandonMeeting(meeting.meeting_id);
      onResolved();
      navigate({ name: "new-meeting" });
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <div className="animate-overlay-in fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <Card className="animate-modal-in w-[420px] p-6 shadow-[var(--shadow-lg)]">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 shrink-0 rounded-full bg-[var(--color-warning-soft)] p-2">
            <AlertTriangle size={18} className="text-[var(--color-warning)]" />
          </div>
          <div>
            <h2 className="text-[15px] font-semibold text-[var(--color-text)]">
              An unfinished meeting was found
            </h2>
            <p className="mt-1.5 text-sm text-[var(--color-text-muted)]">
              &ldquo;{meeting.title}&rdquo; was still recording when MeetNote last closed. Nothing has
              been lost: the transcript recorded so far is saved. Resume it now, or leave it and start a
              new meeting.
            </p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={startNew} disabled={!!busyAction} loading={busyAction === "startNew"}>
            Start New Meeting
          </Button>
          <Button variant="primary" onClick={resume} disabled={!!busyAction} loading={busyAction === "resume"}>
            Resume
          </Button>
        </div>
      </Card>
    </div>
  );
}
