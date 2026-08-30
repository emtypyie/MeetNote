import { useEffect, useState } from "react";
import { FileStack, Pencil, Plus, Trash2, X } from "lucide-react";
import { Button, Card, SectionLabel } from "../components/ui";
import { engineClient } from "../services/engineClient";
import type { NoteTemplate } from "../types/engine";

function blankTemplate(): NoteTemplate {
  return { id: `custom-${Date.now()}`, name: "New Template", sections: ["Meeting Title", "Discussion"] };
}

export function Templates() {
  const [templates, setTemplates] = useState<NoteTemplate[]>([]);
  const [editing, setEditing] = useState<NoteTemplate | null>(null);

  function refresh() {
    engineClient.listTemplates().then(setTemplates);
  }

  useEffect(refresh, []);

  async function handleDelete(id: string) {
    await engineClient.deleteTemplate(id);
    refresh();
  }

  async function handleSave() {
    if (!editing) return;
    await engineClient.saveTemplate({
      ...editing,
      sections: editing.sections.map((s) => s.trim()).filter(Boolean),
    });
    setEditing(null);
    refresh();
  }

  return (
    <div className="mx-auto max-w-5xl px-10 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[var(--color-text)]">Templates</h1>
        <Button variant="primary" onClick={() => setEditing(blankTemplate())}>
          <Plus size={16} />
          New Template
        </Button>
      </div>
      <p className="mt-1 text-sm text-[var(--color-text-muted)]">
        Templates control the section structure of generated meeting notes.
      </p>

      <div className="mt-6 grid grid-cols-1 gap-3 lg:grid-cols-2">
        {templates.map((t) => (
          <Card key={t.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate text-sm font-medium text-[var(--color-text)]">{t.name}</h3>
                <p className="mt-0.5 text-xs text-[var(--color-text-faint)]">
                  {t.sections.length} {t.sections.length === 1 ? "section" : "sections"}
                </p>
              </div>
              <div className="flex shrink-0 gap-1">
                <Button variant="ghost" size="sm" onClick={() => setEditing(t)} aria-label={`Edit ${t.name}`}>
                  <Pencil size={13} />
                  Edit
                </Button>
                {t.id !== "standard" && (
                  <Button variant="ghost" size="sm" onClick={() => handleDelete(t.id)} aria-label={`Delete ${t.name}`}>
                    <Trash2 size={13} />
                  </Button>
                )}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {t.sections.map((s) => (
                <span
                  key={s}
                  className="rounded-md bg-[var(--color-surface-2)] px-2 py-0.5 text-[11px] text-[var(--color-text-muted)]"
                >
                  {s}
                </span>
              ))}
            </div>
          </Card>
        ))}
      </div>

      {editing && (
        <div className="animate-overlay-in fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <Card className="animate-modal-in w-[440px] max-h-[80vh] overflow-y-auto p-5 shadow-[var(--shadow-lg)]">
            <div className="flex items-center justify-between">
              <SectionLabel icon={FileStack}>Edit Template</SectionLabel>
              <button onClick={() => setEditing(null)} className="text-[var(--color-text-faint)] cursor-pointer hover:text-[var(--color-text)]" aria-label="Close">
                <X size={16} />
              </button>
            </div>

            <label className="block text-xs font-medium text-[var(--color-text-muted)]">Name</label>
            <input
              value={editing.name}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })}
              className="mt-1.5 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-accent)]"
            />

            <label className="mt-4 block text-xs font-medium text-[var(--color-text-muted)]">
              Sections (in order)
            </label>
            <div className="mt-1.5 flex flex-col gap-1.5">
              {editing.sections.map((section, i) => (
                <div key={i} className="flex gap-1.5">
                  <input
                    value={section}
                    onChange={(e) => {
                      const sections = [...editing.sections];
                      sections[i] = e.target.value;
                      setEditing({ ...editing, sections });
                    }}
                    className="flex-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-1.5 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-accent)]"
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      setEditing({ ...editing, sections: editing.sections.filter((_, j) => j !== i) })
                    }
                  >
                    <X size={13} />
                  </Button>
                </div>
              ))}
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setEditing({ ...editing, sections: [...editing.sections, ""] })}
              >
                <Plus size={13} />
                Add section
              </Button>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleSave}>
                Save
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
