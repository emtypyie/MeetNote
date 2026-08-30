import { LayoutGrid, Mic, FileStack, Settings as SettingsIcon } from "lucide-react";
import clsx from "clsx";
import { useUIStore } from "../stores/uiStore";

const items = [
  { key: "dashboard", label: "Meetings", icon: LayoutGrid },
  { key: "new-meeting", label: "New Meeting", icon: Mic },
  { key: "templates", label: "Templates", icon: FileStack },
  { key: "settings", label: "Settings", icon: SettingsIcon },
] as const;

export function Sidebar() {
  const view = useUIStore((s) => s.view);
  const navigate = useUIStore((s) => s.navigate);

  return (
    <nav className="flex w-[200px] shrink-0 flex-col border-r border-[var(--color-border-subtle)] bg-[var(--color-surface-1)] px-3 py-5">
      <div className="mb-7 flex items-center gap-2.5 px-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--color-accent)] shadow-[var(--shadow-sm)]">
          <Mic size={14} className="text-white" strokeWidth={2.25} />
        </div>
        <span className="text-[15px] font-semibold tracking-tight text-[var(--color-text)]">MeetNote</span>
      </div>
      <div className="flex flex-col gap-0.5">
        {items.map(({ key, label, icon: Icon }) => {
          const active = view.name === key;
          return (
            <button
              key={key}
              onClick={() => navigate({ name: key } as never)}
              aria-current={active ? "page" : undefined}
              className={clsx(
                "relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150 cursor-pointer text-left",
                active
                  ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  : "text-[var(--color-text-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)]",
              )}
            >
              {active && (
                <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-[var(--color-accent)]" />
              )}
              <Icon size={16} strokeWidth={active ? 2.25 : 2} />
              {label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
