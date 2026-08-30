import { useEffect, useState } from "react";
import { AlertTriangle, CalendarClock, Loader2, Mic, Plus } from "lucide-react";
import { Button } from "../components/ui";
import { MeetingCard } from "../components/MeetingCard";
import { engineClient } from "../services/engineClient";
import { useUIStore } from "../stores/uiStore";
import type { MeetingSummary } from "../types/engine";

export function Dashboard() {
  const navigate = useUIStore((s) => s.navigate);
  const view = useUIStore((s) => s.view);
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flashMessage, setFlashMessage] = useState<string | null>(null);

  // Pick up any flash message passed when navigating to Dashboard (e.g. after deletion)
  useEffect(() => {
    if (view.name === "dashboard" && view.flashMessage) {
      setFlashMessage(view.flashMessage);
      const t = setTimeout(() => setFlashMessage(null), 4000);
      return () => clearTimeout(t);
    }
  }, [view]);

  function loadMeetings() {
    setError(null);
    engineClient
      .listMeetings()
      .then(setMeetings)
      .catch((e) => setError(String(e.message ?? e)));
  }

  useEffect(loadMeetings, []);

  return (
    <div className="mx-auto max-w-6xl px-10 py-10">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[var(--color-text)]">Meetings</h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">Your recorded meetings and generated notes.</p>
        </div>
        <Button variant="primary" onClick={() => navigate({ name: "new-meeting" })}>
          <Plus size={16} />
          Start New Meeting
        </Button>
      </div>

      {flashMessage && (
        <div className="mt-4 rounded-lg bg-[var(--color-success-soft)] px-4 py-3 text-sm text-[var(--color-success)]">
          {flashMessage}
        </div>
      )}

      <div className="mt-8">
        {meetings !== null && meetings.length > 0 && (
          <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-faint)]">
            Recent Meetings
          </h2>
        )}

        {error && (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-[var(--color-border)] px-6 py-12 text-center">
            <AlertTriangle size={22} className="text-[var(--color-danger)]" />
            <div>
              <p className="text-sm font-medium text-[var(--color-text)]">Unable to load meetings</p>
              <p className="mt-1 text-xs text-[var(--color-text-muted)]">MeetNote could not reach the local engine.</p>
            </div>
            <Button variant="secondary" size="sm" onClick={loadMeetings}>Try Again</Button>
          </div>
        )}

        {!error && meetings === null && (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-[var(--color-text-muted)]">
            <Loader2 size={16} className="animate-spin" />
            Loading meetings…
          </div>
        )}

        {!error && meetings?.length === 0 && (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-[var(--color-border)] px-6 py-16 text-center">
            <div className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--color-surface-2)]">
              <CalendarClock size={20} className="text-[var(--color-text-faint)]" />
            </div>
            <div>
              <p className="text-sm font-medium text-[var(--color-text)]">No meetings yet</p>
              <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                Start your first meeting and MeetNote will handle the rest.
              </p>
            </div>
            <Button variant="secondary" size="sm" onClick={() => navigate({ name: "new-meeting" })}>
              <Mic size={14} />
              Start New Meeting
            </Button>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {meetings?.map((m) => (
            <MeetingCard
              key={m.meeting_id}
              meeting={m}
              onDelete={(id) => setMeetings((prev) => prev?.filter((x) => x.meeting_id !== id) ?? null)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
