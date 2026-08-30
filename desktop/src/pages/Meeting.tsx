import { useEffect, useRef, useState } from "react";
import { Bookmark, Pause, Play, Square, Cpu, Mic, MonitorSpeaker, HardDrive, Zap, WifiOff } from "lucide-react";
import { Button } from "../components/ui";
import { useMeetingStore } from "../stores/meetingStore";
import { useUIStore } from "../stores/uiStore";
import { engineClient } from "../services/engineClient";
import { formatClockTime, formatElapsed } from "../lib/format";
import type { HealthResponse } from "../types/engine";

export function Meeting() {
  const navigate = useUIStore((s) => s.navigate);
  // Individual primitive/function selectors, not one selector returning a
  // fresh object literal — Zustand v5's store hook is backed by React's
  // useSyncExternalStore, which requires getSnapshot() to return a stable
  // reference when nothing actually changed. A selector that allocates a
  // new object every call fails that check on every render, which React
  // reports as "Maximum update depth exceeded" and, with no error boundary
  // above it, silently unmounts the whole tree — the exact cause of the
  // blank meeting window bug fixed here.
  const meetingId = useMeetingStore((s) => s.meetingId);
  const title = useMeetingStore((s) => s.title);
  const state = useMeetingStore((s) => s.state);
  const elapsedSeconds = useMeetingStore((s) => s.elapsedSeconds);
  const deviceStatus = useMeetingStore((s) => s.deviceStatus);
  const chunks = useMeetingStore((s) => s.chunks);
  const markers = useMeetingStore((s) => s.markers);
  const pauseAction = useMeetingStore((s) => s.pause);
  const resumeAction = useMeetingStore((s) => s.resume);
  const stop = useMeetingStore((s) => s.stop);
  const markImportant = useMeetingStore((s) => s.markImportant);
  const hydrateFromCurrent = useMeetingStore((s) => s.hydrateFromCurrent);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [busyAction, setBusyAction] = useState<"pause-resume" | "stop" | null>(null);
  const busy = busyAction !== null;
  const [justMarked, setJustMarked] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    engineClient.health().then(setHealth).catch(() => {});
  }, []);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chunks.length]);

  const isRecording = state === "recording";
  const isPaused = state === "paused";

  async function handleRetryConnection() {
    setReconnecting(true);
    try {
      const active = await hydrateFromCurrent();
      if (!active) navigate({ name: "new-meeting" });
    } catch {
      // engine still unreachable — stay on this screen, let the user retry again
    } finally {
      setReconnecting(false);
    }
  }

  // Reaching this page without an active meeting means the engine session
  // was lost (e.g. the engine restarted) between navigating here and
  // mounting — never render the meeting chrome around a meeting that
  // doesn't exist.
  if (!meetingId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
        <WifiOff size={22} className="text-[var(--color-danger)]" />
        <h1 className="text-lg font-semibold text-[var(--color-text)]">Unable to initialize meeting</h1>
        <p className="max-w-sm text-sm text-[var(--color-text-muted)]">
          The local MeetNote engine could not be reached.
        </p>
        <div className="mt-2 flex gap-2">
          <Button variant="primary" onClick={handleRetryConnection} loading={reconnecting}>
            Retry
          </Button>
          <Button variant="secondary" onClick={() => navigate({ name: "new-meeting" })}>
            Return to New Meeting
          </Button>
        </div>
      </div>
    );
  }

  async function handlePauseResume() {
    setBusyAction("pause-resume");
    try {
      if (isRecording) await pauseAction();
      else await resumeAction();
    } finally {
      setBusyAction(null);
    }
  }

  async function handleMarkImportant() {
    await markImportant();
    setJustMarked(true);
    setTimeout(() => setJustMarked(false), 1500);
  }

  async function handleStop() {
    if (!meetingId) return;
    setBusyAction("stop");
    try {
      await stop();
      navigate({ name: "completion", meetingId });
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-6 py-4">
        <h1 className="text-[15px] font-semibold text-[var(--color-text)]">{title || "Meeting"}</h1>
        <div className="flex items-center gap-4">
          <span className="tabular-nums text-sm text-[var(--color-text-muted)]">
            {formatElapsed(elapsedSeconds)}
          </span>
          <span
            className={
              "flex items-center gap-1.5 text-xs font-medium " +
              (isRecording ? "text-[var(--color-record)]" : "text-[var(--color-warning)]")
            }
          >
            <span
              className={
                "h-2 w-2 rounded-full " +
                (isRecording ? "bg-[var(--color-record)] animate-record-pulse" : "bg-[var(--color-warning)]")
              }
            />
            {isRecording ? "RECORDING" : isPaused ? "PAUSED" : state.toUpperCase()}
          </span>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_360px]">
        <section className="flex min-h-0 flex-col border-r border-[var(--color-border-subtle)]">
          <div className="border-b border-[var(--color-border-subtle)] px-6 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-faint)]">
            Live Transcript
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {chunks.length === 0 && (
              <p className="text-sm text-[var(--color-text-faint)]">
                Listening… transcript will appear here as the meeting is recorded.
              </p>
            )}
            <div className="flex flex-col gap-4">
              {chunks.map((c) => (
                <div key={c.chunk_index}>
                  <div className="text-xs tabular-nums text-[var(--color-text-faint)]">
                    {formatClockTime(c.start_offset_seconds)}
                  </div>
                  <p className="mt-0.5 text-sm leading-relaxed text-[var(--color-text)]">
                    {c.status === "failed"
                      ? "[transcription unavailable for this segment]"
                      : c.text || "[silence]"}
                  </p>
                </div>
              ))}
            </div>
            <div ref={transcriptEndRef} />
          </div>
        </section>

        <aside className="flex min-h-0 flex-col">
          <div className="border-b border-[var(--color-border-subtle)] px-5 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-faint)]">
            Meeting Memory
          </div>
          <div className="flex-1 overflow-y-auto px-5 py-4">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-faint)]">
              Important Moments ({markers.length})
            </div>
            {markers.length === 0 ? (
              <p className="mt-1.5 text-xs text-[var(--color-text-faint)]">
                Use &ldquo;Mark Important&rdquo; below to flag a moment for extra attention in the notes.
              </p>
            ) : (
              <ul className="mt-1.5 flex flex-col gap-1">
                {markers.map((m, i) => (
                  <li key={i} className="text-sm tabular-nums text-[var(--color-text)]">
                    {formatClockTime(m.offset_seconds)}
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-6 rounded-lg border border-dashed border-[var(--color-border)] p-3 text-xs leading-relaxed text-[var(--color-text-faint)]">
              Decisions, action items, deadlines and open questions are generated from the full transcript
              after the meeting ends, so they stay accurate rather than guessing mid-conversation.
              You&rsquo;ll see them on the completion screen.
            </div>
          </div>
        </aside>
      </div>

      <footer className="border-t border-[var(--color-border-subtle)] px-6 py-3">
        <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-[var(--color-text-muted)]">
          <StatusItem icon={Zap} label={health?.transcription_mode?.device === "cuda" ? "GPU" : "CPU"} ok />
          <StatusItem icon={Cpu} label="Whisper" ok={!!health?.whisper.loaded} />
          <StatusItem icon={HardDrive} label="Saving" ok />
          <StatusItem icon={Mic} label="Mic" ok={!!deviceStatus?.microphone_connected} />
          <StatusItem icon={MonitorSpeaker} label="System Audio" ok={!!deviceStatus?.system_audio_connected} />
        </div>
        <div className="flex items-center justify-between">
          <Button variant="secondary" onClick={handleMarkImportant} disabled={busy}>
            <Bookmark size={16} />
            {justMarked ? "Marked" : "Mark Important"}
          </Button>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={handlePauseResume} disabled={busy} loading={busyAction === "pause-resume"}>
              {busyAction !== "pause-resume" && (isRecording ? <Pause size={16} /> : <Play size={16} />)}
              {isRecording ? "Pause" : "Resume"}
            </Button>
            <Button variant="danger" onClick={handleStop} disabled={busy} loading={busyAction === "stop"}>
              {busyAction !== "stop" && <Square size={16} />}
              Stop
            </Button>
          </div>
        </div>
      </footer>
    </div>
  );
}

function StatusItem({ icon: Icon, label, ok }: { icon: typeof Cpu; label: string; ok: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <Icon size={13} className={ok ? "text-[var(--color-success)]" : "text-[var(--color-danger)]"} />
      {label}
    </span>
  );
}
