import { type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx(
        "rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-1)]",
        className,
      )}
      {...props}
    />
  );
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
}

export function Button({ variant = "secondary", size = "md", className, ...props }: ButtonProps) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors",
        "disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer",
        size === "md" ? "px-4 py-2 text-sm" : "px-3 py-1.5 text-xs",
        variant === "primary" &&
          "bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)]",
        variant === "secondary" &&
          "bg-[var(--color-surface-2)] text-[var(--color-text)] border border-[var(--color-border)] hover:bg-[var(--color-surface-3)]",
        variant === "ghost" && "text-[var(--color-text-muted)] hover:text-[var(--color-text)]",
        variant === "danger" &&
          "bg-[var(--color-danger-soft)] text-[var(--color-danger)] border border-[var(--color-danger)]/30 hover:bg-[var(--color-danger)]/25",
        className,
      )}
      {...props}
    />
  );
}

export function StatusDot({ ok, pending }: { ok: boolean; pending?: boolean }) {
  return (
    <span
      className={clsx(
        "inline-block h-2 w-2 rounded-full",
        pending ? "bg-[var(--color-warning)]" : ok ? "bg-[var(--color-success)]" : "bg-[var(--color-danger)]",
      )}
    />
  );
}

export function HealthRow({
  label,
  ok,
  detail,
  pending,
}: {
  label: string;
  ok: boolean;
  detail?: string;
  pending?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[var(--color-border)] last:border-b-0">
      <div className="flex items-center gap-2.5">
        <StatusDot ok={ok} pending={pending} />
        <span className="text-sm text-[var(--color-text)]">{label}</span>
      </div>
      {detail && <span className="text-xs text-[var(--color-text-muted)]">{detail}</span>}
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-faint)] mb-3">
      {children}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "success" | "warning" | "danger" }) {
  const toneClasses = {
    neutral: "bg-[var(--color-surface-2)] text-[var(--color-text-muted)] border-[var(--color-border)]",
    success: "bg-[var(--color-success)]/10 text-[var(--color-success)] border-[var(--color-success)]/30",
    warning: "bg-[var(--color-warning)]/10 text-[var(--color-warning)] border-[var(--color-warning)]/30",
    danger: "bg-[var(--color-danger)]/10 text-[var(--color-danger)] border-[var(--color-danger)]/30",
  }[tone];
  return (
    <span className={clsx("inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium", toneClasses)}>
      {children}
    </span>
  );
}
