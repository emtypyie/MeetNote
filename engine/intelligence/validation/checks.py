"""Deterministic quality-control checks (product spec section 22).

These run in code, not just as instructions to the model, because an LLM
following its own prompt is not a reliable enough guarantee for hard
requirements like "no emojis" or "every deadline the meeting actually had
must still be in the notes". A failed hard check triggers one automatic
rewrite pass (intelligence/analysis/service.py); whatever still fails after
that is reported to the user, never silently swallowed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"  # arrows sometimes used decoratively
    "\U00002B00-\U00002BFF"
    "]",
    flags=re.UNICODE,
)

_BANNED_PHRASES = [
    "here is a summary",
    "here is the summary",
    "here's a summary",
    "here's the summary",
    "as an ai",
    "i hope this helps",
    "let me know if you need",
    "in today's meeting, we discussed",
]


@dataclass
class ValidationIssue:
    code: str
    message: str
    hard: bool  # hard issues force a rewrite pass; soft issues are reported only

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hard": self.hard}


def _find_missing_sections(notes_text: str, sections: list[str]) -> list[str]:
    missing = []
    for section in sections:
        heading_pattern = re.compile(rf"^#{{1,3}}\s*{re.escape(section)}\s*$", re.MULTILINE | re.IGNORECASE)
        if not heading_pattern.search(notes_text):
            missing.append(section)
    return missing


def _extract_expected_entities(analysis: dict) -> list[str]:
    # Deliberately excludes plain `attendees`: someone can attend without
    # being individually named outside an Attendees section, so checking
    # for their name everywhere in the notes would be too strict. Owners
    # and deadlines tied to concrete commitments are what the spec calls
    # out as needing to survive accurately, so those are checked instead.
    entities: list[str] = []
    for item in analysis.get("action_items", []):
        if item.get("owner"):
            entities.append(item["owner"])
        if item.get("deadline"):
            entities.append(item["deadline"])
    entities.extend(d for d in analysis.get("deadlines", []) if d)
    return entities


def run_checks(notes_text: str, sections: list[str], analysis: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if _EMOJI_PATTERN.search(notes_text):
        issues.append(ValidationIssue("emoji", "Notes contain emoji characters", hard=True))

    if "—" in notes_text:
        issues.append(ValidationIssue("em_dash", "Notes contain an em dash (—)", hard=True))

    lowered = notes_text.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lowered:
            issues.append(
                ValidationIssue("filler_phrase", f"Notes contain a filler phrase: \"{phrase}\"", hard=True)
            )

    missing_sections = _find_missing_sections(notes_text, sections)
    if missing_sections:
        issues.append(
            ValidationIssue(
                "missing_sections",
                f"Missing required section(s): {', '.join(missing_sections)}",
                hard=True,
            )
        )

    missing_entities = [e for e in _extract_expected_entities(analysis) if e.lower() not in lowered]
    if missing_entities:
        issues.append(
            ValidationIssue(
                "entities_dropped",
                f"Name(s)/date(s) from the meeting record did not survive into the notes: {', '.join(missing_entities)}",
                hard=True,
            )
        )

    action_items_present = bool(analysis.get("action_items"))
    if action_items_present and "action item" not in lowered and "next step" not in lowered:
        issues.append(
            ValidationIssue(
                "action_items_missing",
                "The meeting record has action items but the notes don't appear to include them",
                hard=False,
            )
        )

    word_count = len(notes_text.split())
    if word_count > 1200:
        issues.append(
            ValidationIssue(
                "verbose",
                f"Notes are unusually long ({word_count} words) for a concise summary",
                hard=False,
            )
        )

    return issues


def has_hard_issues(issues: list[ValidationIssue]) -> bool:
    return any(i.hard for i in issues)
