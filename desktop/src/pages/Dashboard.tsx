import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "../components/ui";
import { MeetingCard } from "../components/MeetingCard";
import { engineClient } from "../services/engineClient";
import { useUIStore } from "../stores/uiStore";
import type { MeetingSummary } from "../types/engine";

export function Dashboard() {
  const navigate = useUIStore((s) => s.navigate);
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    engineClient
      .listMeetings()
      .then((m) => !cancelled && setMeetings(m))
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[var(--color-text)]">Meetings</h1>
        <Button variant="primary" onClick={() => navigate({ name: "new-meeting" })}>
          <Plus size={16} />
          Start New Meeting
        </Button>
      </div>

      <div className="mt-8">
        <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-faint)]">
          Recent Meetings
        </h2>

        {error && (
          <p className="text-sm text-[var(--color-danger)]">
            Could not load meetings: {error}
          </p>
        )}

        {!error && meetings === null && (
          <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
        )}

        {meetings?.length === 0 && (
          <p className="text-sm text-[var(--color-text-muted)]">
            No meetings yet. Start one to see it here.
          </p>
        )}

        <div className="flex flex-col gap-2">
          {meetings?.map((m) => (
            <MeetingCard key={m.meeting_id} meeting={m} />
          ))}
        </div>
      </div>
    </div>
  );
}
