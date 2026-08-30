import React, { type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";
import { Check, CheckCircle2, ChevronDown, Clock, Loader2, XCircle } from "lucide-react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Secondary/quiet content can drop the border and lean on surface
   * contrast alone, so not every section on a page reads as an equally
   * loud bordered rectangle. Defaults to the standard bordered surface. */
  variant?: "default" | "quiet";
}

export function Card({ className, variant = "default", ...props }: CardProps) {
  return (
    <div
      className={clsx(
        "rounded-xl",
        variant === "default" && "border border-[var(--color-border)] bg-[var(--color-surface-1)]",
        variant === "quiet" && "bg-[var(--color-surface-1)]/60",
        className,
      )}
      {...props}
    />
  );
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  /** Shows a spinner in place of the leading icon and disables the button,
   * so an in-flight async action is never ambiguous with an inert one. */
  loading?: boolean;
}

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium",
        "transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer",
        size === "md" ? "px-4 py-2 text-sm" : "px-3 py-1.5 text-xs",
        variant === "primary" &&
          "bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)]",
        variant === "secondary" &&
          "bg-[var(--color-surface-2)] text-[var(--color-text)] border border-[var(--color-border)] hover:bg-[var(--color-surface-3)]",
        variant === "ghost" && "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface-2)]",
        variant === "danger" &&
          "bg-[var(--color-danger-soft)] text-[var(--color-danger)] border border-[var(--color-danger)]/30 hover:bg-[var(--color-danger)]/25",
        className,
      )}
      {...props}
    >
      {loading ? <Loader2 size={size === "md" ? 16 : 13} className="animate-spin" aria-hidden /> : null}
      {children}
    </button>
  );
}

/** Icon + color status indicator, so a status is never conveyed by color
 * alone (a colorblind user, or a low-contrast display, can still read a
 * check mark, spinner, or "x" shape). Used by HealthRow / ProviderStatusRow
 * wherever a green/red dot previously stood alone.
 *
 * `neutral` is for "not yet known" (e.g. a configured provider whose first
 * connectivity check hasn't run yet) — distinct from `ok=false`, which
 * means a check actually ran and failed. Without this, a brand-new,
 * perfectly fine API key would flash the same alarming red "x" as a
 * genuine auth failure for the instant before its first check completes. */
export function StatusDot({ ok, pending, neutral }: { ok: boolean; pending?: boolean; neutral?: boolean }) {
  if (pending) {
    return <Loader2 size={14} className="shrink-0 animate-spin text-[var(--color-warning)]" aria-hidden />;
  }
  if (neutral) {
    return <Clock size={14} className="shrink-0 text-[var(--color-info)]" aria-hidden />;
  }
  if (ok) {
    return <CheckCircle2 size={14} className="shrink-0 text-[var(--color-success)]" aria-hidden />;
  }
  return <XCircle size={14} className="shrink-0 text-[var(--color-danger)]" aria-hidden />;
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
    <div className="flex items-center justify-between py-2 border-b border-[var(--color-border-subtle)] last:border-b-0">
      <div className="flex items-center gap-2.5">
        <StatusDot ok={ok} pending={pending} />
        <span className="text-sm text-[var(--color-text)]">{label}</span>
      </div>
      {detail && <span className="text-xs text-[var(--color-text-muted)]">{detail}</span>}
    </div>
  );
}

export function SectionLabel({
  children,
  icon: Icon,
  description,
  trailing,
}: {
  children: ReactNode;
  /** A section icon (task requirement: every settings-style section gets
   * an icon, title, and optional short description rather than a bare
   * uppercase label). Omit to render the plain label as before. */
  icon?: React.ComponentType<{ size?: number; className?: string }>;
  description?: ReactNode;
  /** Right-aligned slot, e.g. a "Recheck" action button next to the title. */
  trailing?: ReactNode;
}) {
  return (
    <div className="mb-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {Icon && <Icon size={14} className="text-[var(--color-text-faint)]" />}
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-faint)]">
            {children}
          </span>
        </div>
        {trailing}
      </div>
      {description && <p className="mt-1 text-xs text-[var(--color-text-muted)]">{description}</p>}
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

interface Option {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  onChange: (value: string) => void;
  options: Option[];
  className?: string;
  disabled?: boolean;
  /** Associates the trigger with an external <label> (e.g. `<label id="x">`
   * above the field) for screen readers, since this is a custom combobox
   * rather than a native <select> a <label for> can bind to directly. */
  labelledBy?: string;
}

let selectInstanceCounter = 0;

export function Select({ value, onChange, options, className, disabled, labelledBy }: SelectProps) {
  const [isOpen, setIsOpen] = React.useState(false);
  const [focusedIndex, setFocusedIndex] = React.useState(-1);
  const [openUpward, setOpenUpward] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const listRef = React.useRef<HTMLDivElement>(null);
  const instanceId = React.useRef(`select-${++selectInstanceCounter}`).current;

  const selectedOption = options.find((o) => o.value === value);

  // Only listens while actually open — a closed dropdown costs nothing.
  // With several Select instances per page (Settings alone has four), an
  // always-on document listener per instance is exactly the kind of
  // "unnecessary global event listener" that adds up for no benefit.
  React.useEffect(() => {
    if (!isOpen) return;

    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  React.useEffect(() => {
    if (!isOpen) return;
    const idx = options.findIndex((o) => o.value === value);
    setFocusedIndex(idx >= 0 ? idx : 0);

    // Decide whether the panel has room to open downward, or should flip
    // above the trigger instead, so it's never clipped against the bottom
    // of the (scrollable) window.
    const trigger = containerRef.current;
    if (trigger) {
      const rect = trigger.getBoundingClientRect();
      const estimatedPanelHeight = Math.min(options.length * 36 + 8, 240);
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;
      setOpenUpward(spaceBelow < estimatedPanelHeight && spaceAbove > spaceBelow);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Keep the keyboard-focused option scrolled into view as it changes.
  React.useEffect(() => {
    if (!isOpen || focusedIndex < 0) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-index="${focusedIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [isOpen, focusedIndex]);

  function commitSelection(index: number) {
    const option = options[index];
    if (option) onChange(option.value);
    setIsOpen(false);
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (disabled) return;

    switch (e.key) {
      case "Enter":
      case " ":
        if (isOpen) {
          commitSelection(focusedIndex);
        } else {
          setIsOpen(true);
        }
        e.preventDefault();
        break;
      case "Escape":
        if (isOpen) {
          setIsOpen(false);
          e.preventDefault();
        }
        break;
      case "Tab":
        setIsOpen(false);
        break;
      case "ArrowDown":
        if (!isOpen) {
          setIsOpen(true);
        } else {
          setFocusedIndex((prev) => Math.min(prev + 1, options.length - 1));
        }
        e.preventDefault();
        break;
      case "ArrowUp":
        if (!isOpen) {
          setIsOpen(true);
        } else {
          setFocusedIndex((prev) => Math.max(prev - 1, 0));
        }
        e.preventDefault();
        break;
      case "Home":
        if (isOpen) {
          setFocusedIndex(0);
          e.preventDefault();
        }
        break;
      case "End":
        if (isOpen) {
          setFocusedIndex(options.length - 1);
          e.preventDefault();
        }
        break;
    }
  };

  return (
    <div ref={containerRef} className={clsx("relative w-full", className)} onKeyDown={handleKeyDown}>
      <div
        tabIndex={disabled ? -1 : 0}
        onClick={() => !disabled && setIsOpen((v) => !v)}
        className={clsx(
          "flex w-full items-center justify-between rounded-lg border bg-[var(--color-surface-2)] px-3 py-2 text-sm text-[var(--color-text)] outline-none transition-colors duration-150",
          disabled
            ? "cursor-not-allowed opacity-50 border-[var(--color-border)]"
            : "cursor-pointer border-[var(--color-border)] hover:border-[var(--color-border-strong)]",
          isOpen && !disabled && "border-[var(--color-accent)]",
        )}
        role="combobox"
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-disabled={disabled || undefined}
        aria-labelledby={labelledBy}
        aria-activedescendant={isOpen && focusedIndex >= 0 ? `${instanceId}-opt-${focusedIndex}` : undefined}
      >
        <span className="truncate">{selectedOption?.label || ""}</span>
        <ChevronDown
          size={16}
          className={clsx(
            "ml-2 shrink-0 text-[var(--color-text-muted)] transition-transform duration-150",
            isOpen && "rotate-180",
          )}
        />
      </div>

      {isOpen && (
        <div
          ref={listRef}
          className={clsx(
            "animate-overlay-in absolute z-50 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface-3)] py-1 shadow-[var(--shadow-md)] max-h-60 overflow-auto",
            openUpward ? "bottom-full mb-1" : "top-full mt-1",
          )}
          role="listbox"
        >
          {options.map((option, index) => {
            const isSelected = option.value === value;
            const isFocused = focusedIndex === index;
            return (
              <div
                key={option.value}
                id={`${instanceId}-opt-${index}`}
                data-index={index}
                onClick={() => commitSelection(index)}
                onMouseEnter={() => setFocusedIndex(index)}
                className={clsx(
                  "flex cursor-pointer items-center justify-between gap-2 px-3 py-2 text-sm transition-colors duration-100",
                  isFocused ? "bg-[var(--color-accent-soft)] text-[var(--color-text)]" : "text-[var(--color-text)]",
                  isSelected && "font-medium",
                )}
                role="option"
                aria-selected={isSelected}
              >
                <span className="truncate">{option.label}</span>
                {isSelected && <Check size={14} className="shrink-0 text-[var(--color-accent)]" aria-hidden />}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
