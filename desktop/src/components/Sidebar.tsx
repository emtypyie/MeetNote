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
    <nav className="flex w-[196px] shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-surface-1)] px-3 py-4">
      <div className="mb-6 flex items-center gap-2 px-2">
        <div className="h-6 w-6 rounded-md bg-[var(--color-accent)]" />
        <span className="text-[15px] font-semibold tracking-tight">MeetNote</span>
      </div>
      <div className="flex flex-col gap-0.5">
        {items.map(({ key, label, icon: Icon }) => {
          const active = view.name === key;
          return (
            <button
              key={key}
              onClick={() => navigate({ name: key } as never)}
              className={clsx(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors cursor-pointer text-left",
                active
                  ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  : "text-[var(--color-text-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)]",
              )}
            >
              <Icon size={16} />
              {label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
