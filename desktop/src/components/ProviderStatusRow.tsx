import { StatusDot } from "./ui";
import type { ProviderStatus } from "../types/engine";

const LABELS: Record<ProviderStatus["status"], string> = {
  not_configured: "Not configured",
  checking: "Checking…",
  configured: "Configured",
  auth_failed: "Invalid API key",
  unavailable: "Temporarily unavailable",
  model_not_found: "Model unavailable",
  unknown: "Not yet checked",
};

export function ProviderStatusRow({ label, provider }: { label: string; provider: ProviderStatus | undefined }) {
  const status = provider?.status ?? "not_configured";
  const ok = status === "configured";
  const pending = status === "checking";
  const neutral = status === "unknown";
  const isError = status === "auth_failed" || status === "unavailable" || status === "model_not_found";

  return (
    <div className="flex items-start justify-between py-2 border-b border-[var(--color-border-subtle)] last:border-b-0">
      <div className="flex items-center gap-2.5 mt-0.5">
        <StatusDot ok={ok} pending={pending} neutral={neutral} />
        <span className="text-sm text-[var(--color-text)]">{label}</span>
      </div>
      <div className="text-right">
        <div className={`text-xs ${isError ? "text-[var(--color-danger)]" : "text-[var(--color-text-muted)]"}`}>
          {LABELS[status]}
        </div>
        {isError && (
          <div className="text-[10px] text-[var(--color-text-faint)] mt-0.5">
            Recheck or update key in Settings.
          </div>
        )}
      </div>
    </div>
  );
}
