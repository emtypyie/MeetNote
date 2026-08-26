import { StatusDot } from "./ui";
import type { ProviderStatus } from "../types/engine";

const LABELS: Record<ProviderStatus["status"], string> = {
  not_configured: "Not configured",
  checking: "Checking…",
  configured: "Configured",
  auth_failed: "Configured, authentication failed",
  unavailable: "Configured, temporarily unavailable",
  model_not_found: "Configured, model unavailable",
  unknown: "Configured, not yet checked",
};

export function ProviderStatusRow({ label, provider }: { label: string; provider: ProviderStatus | undefined }) {
  const status = provider?.status ?? "not_configured";
  const ok = status === "configured";
  const pending = status === "checking";

  return (
    <div className="flex items-center justify-between py-2 border-b border-[var(--color-border)] last:border-b-0">
      <div className="flex items-center gap-2.5">
        <StatusDot ok={ok} pending={pending} />
        <span className="text-sm text-[var(--color-text)]">{label}</span>
      </div>
      <div className="text-right">
        <div className="text-xs text-[var(--color-text-muted)]">{LABELS[status]}</div>
        {provider?.error && (status === "auth_failed" || status === "unavailable" || status === "model_not_found") && (
          <div className="max-w-[220px] truncate text-[10px] text-[var(--color-text-faint)]" title={provider.error}>
            {provider.error}
          </div>
        )}
      </div>
    </div>
  );
}
