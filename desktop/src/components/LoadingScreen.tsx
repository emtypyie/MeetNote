import { useEffect, useState } from "react";

interface LoadingScreenProps {
  status: "connecting" | "loading" | "error";
  onRetry?: () => void;
}

export function LoadingScreen({ status, onRetry }: LoadingScreenProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed((e) => e + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="flex h-full w-full items-center justify-center bg-[var(--color-bg)] text-[var(--color-text)]">
      <div className="flex max-w-md flex-col items-center gap-8 text-center">
        {/* Logo/Title */}
        <div>
          <h1 className="text-4xl font-bold text-[var(--color-primary)] mb-2">MEETNOTE</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Desktop Meeting Assistant</p>
        </div>

        {/* Spinner */}
        <div className="flex items-center justify-center">
          <div
            className="h-12 w-12 animate-spin rounded-full border-4 border-[var(--color-text-tertiary)] border-t-[var(--color-primary)]"
            aria-label="Loading spinner"
          />
        </div>

        {/* Status Message */}
        <div>
          {status === "connecting" && (
            <>
              <p className="text-lg font-semibold text-[var(--color-text)]">
                Connecting to local engine...
              </p>
              <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
                {elapsed < 5 ? "Starting up" : "This may take a moment on first launch"}
              </p>
            </>
          )}
          {status === "loading" && (
            <>
              <p className="text-lg font-semibold text-[var(--color-text)]">
                Loading MeetNote...
              </p>
              <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
                Engine ready, initializing interface
              </p>
            </>
          )}
          {status === "error" && (
            <>
              <p className="text-lg font-semibold text-red-500">
                Failed to connect to engine
              </p>
              <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
                Check logs/engine.log for details
              </p>
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="mt-6 rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white hover:bg-[var(--color-primary-hover)] transition-colors"
                >
                  Retry
                </button>
              )}
            </>
          )}
        </div>

        {/* Elapsed time hint (only show after 3 seconds) */}
        {status === "connecting" && elapsed > 3 && (
          <p className="text-xs text-[var(--color-text-tertiary)] mt-4">
            Connected for {elapsed}s. If this continues, check engine/logs/
          </p>
        )}
      </div>
    </div>
  );
}
