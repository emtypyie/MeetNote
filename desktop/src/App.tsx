import { useEffect, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { RecoveryModal } from "./components/RecoveryModal";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Dashboard } from "./pages/Dashboard";
import { NewMeeting } from "./pages/NewMeeting";
import { Meeting } from "./pages/Meeting";
import { Completion } from "./pages/Completion";
import { Settings } from "./pages/Settings";
import { Templates } from "./pages/Templates";
import { useUIStore } from "./stores/uiStore";
import { useMeetingStore } from "./stores/meetingStore";
import { engineClient } from "./services/engineClient";
import type { MeetingMetadata } from "./types/engine";

function App() {
  const view = useUIStore((s) => s.view);
  const navigate = useUIStore((s) => s.navigate);
  const hydrate = useMeetingStore((s) => s.hydrateFromCurrent);
  const [unfinished, setUnfinished] = useState<MeetingMetadata[]>([]);
  const [checkedRecovery, setCheckedRecovery] = useState(false);

  useEffect(() => {
    (async () => {
      // If the engine already has a live session (app window reloaded
      // without the engine restarting), jump straight back into it rather
      // than showing the dashboard as if nothing were recording.
      const wasActive = await hydrate().catch(() => false);
      if (wasActive) {
        navigate({ name: "meeting" });
        setCheckedRecovery(true);
        return;
      }
      const list = await engineClient.listUnfinished().catch(() => []);
      setUnfinished(list);
      setCheckedRecovery(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isFocusMode = view.name === "meeting";

  return (
    <div className="flex h-full w-full bg-[var(--color-bg)] text-[var(--color-text)]">
      {!isFocusMode && <Sidebar />}
      <main className="min-w-0 flex-1 overflow-y-auto">
        {/* Keyed by view so navigating away and back gives a fresh boundary
            instead of staying stuck on a previous crash. A view crashing
            here must never leave a blank window — see ErrorBoundary. */}
        <ErrorBoundary
          key={view.name}
          title="loading this page"
          secondaryAction={{
            label: view.name === "meeting" ? "Return to New Meeting" : "Back to Meetings",
            onClick: () => navigate(view.name === "meeting" ? { name: "new-meeting" } : { name: "dashboard" }),
          }}
        >
          {view.name === "dashboard" && <Dashboard />}
          {view.name === "new-meeting" && <NewMeeting />}
          {view.name === "meeting" && <Meeting />}
          {view.name === "completion" && <Completion meetingId={view.meetingId} />}
          {view.name === "settings" && <Settings />}
          {view.name === "templates" && <Templates />}
        </ErrorBoundary>
      </main>

      {checkedRecovery && unfinished.length > 0 && (
        <RecoveryModal meetings={unfinished} onResolved={() => setUnfinished([])} />
      )}
    </div>
  );
}

export default App;
