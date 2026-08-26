"""User-configurable meeting-note templates.

Templates are plain data (id + display name + ordered section list), never
hardcoded into the AI service or the notes-generation prompt — see
prompts/notes.py, which renders whatever sections a template specifies.
Built-in templates ship as JSON under intelligence/builtin_templates/;
user-created ones are saved under ~/MeetNote/templates/ and take priority
over a built-in template with the same id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from storage.atomic import atomic_write_json
from storage.paths import storage_root

_BUILTIN_DIR = Path(__file__).parent / "builtin_templates"


@dataclass
class NoteTemplate:
    id: str
    name: str
    sections: list[str]

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "sections": self.sections}


def _user_templates_dir() -> Path:
    d = storage_root() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_dir(directory: Path) -> dict[str, NoteTemplate]:
    templates: dict[str, NoteTemplate] = {}
    if not directory.exists():
        return templates
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            template = NoteTemplate(id=data["id"], name=data["name"], sections=data["sections"])
            templates[template.id] = template
        except (json.JSONDecodeError, KeyError):
            continue
    return templates


def list_templates() -> list[NoteTemplate]:
    templates = _load_dir(_BUILTIN_DIR)
    templates.update(_load_dir(_user_templates_dir()))  # user templates override built-ins by id
    return sorted(templates.values(), key=lambda t: t.name)


def get_template(template_id: str) -> NoteTemplate:
    for template in list_templates():
        if template.id == template_id:
            return template
    # Never fail meeting completion just because a template id was deleted
    # or mistyped — fall back to the standard template and let the caller
    # decide whether to surface that as a warning.
    return get_template("standard")


def save_template(template: NoteTemplate) -> None:
    atomic_write_json(_user_templates_dir() / f"{template.id}.json", template.to_dict())


def delete_template(template_id: str) -> bool:
    path = _user_templates_dir() / f"{template_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False
