"""Prompt for turning the structured analysis into final prose notes.

The strict writing rules here are a direct, largely verbatim translation of
the product spec's section 20 — they are load-bearing, not decoration, and
validation/checks.py enforces the hard parts of them deterministically
afterward rather than trusting the model alone.
"""

from __future__ import annotations

import json

from intelligence.templates import NoteTemplate

NOTES_SYSTEM_PROMPT = """You write meeting notes the way a capable human secretary would after attending \
a meeting: concise, precise, natural, professional, and faithful to what was actually said. You are not \
writing a generic AI summary.

Hard rules, no exceptions:
- No emojis.
- No em dashes (the — character). Use a period or comma instead.
- No decorative symbols or bullet-point emoji.
- No filler openers like "Here is a summary" or "Here is the summary of the meeting".
- No "In conclusion" unless it is genuinely a concluding statement, not a habit.
- No corporate jargon, no robotic phrasing, no repeating the same point in different words.
- Use plain, normal sentence structure, the way a person writes, not a listicle of buzzwords.
- Only state things that are supported by the structured meeting record you're given below. Do not \
invent names, decisions, deadlines, or commitments.
- Preserve every name, date, deadline, and responsibility exactly as given.
- Where the record shows something was only proposed, not decided, say so plainly rather than implying \
it was settled.

Style example (this is the tone to match):
"The team finalized the venue for the event. The graphics team will prepare the poster by Wednesday. \
The revised budget will be shared by Friday."

Not this:
"Here is a concise AI-generated summary of the key takeaways and next steps from the productive \
discussion."

Structure your output as Markdown with exactly these section headings, in this order, each as a level-2 \
heading ("## Section Name"). If a section has nothing to report, write "Nothing recorded for this \
section." under it rather than omitting the heading or inventing content:
{sections}"""


def build_notes_user_prompt(analysis: dict, template: NoteTemplate, meeting_title: str, meeting_date: str) -> str:
    return f"""Meeting title: {meeting_title}
Date: {meeting_date}

Structured meeting record (the only source of truth for this meeting):
{json.dumps(analysis, indent=2, ensure_ascii=False)}

Write the final meeting notes now, following the section headings and rules exactly."""


def build_notes_system_prompt(template: NoteTemplate) -> str:
    sections_list = "\n".join(f"- {s}" for s in template.sections)
    return NOTES_SYSTEM_PROMPT.format(sections=sections_list)


def build_rewrite_user_prompt(previous_notes: str, issues: list[str]) -> str:
    issues_list = "\n".join(f"- {issue}" for issue in issues)
    return f"""Your previous draft of the meeting notes had the following problems:
{issues_list}

Previous draft:
---
{previous_notes}
---

Rewrite the notes, fixing every listed problem, and keep following all the original rules exactly. \
Output only the corrected notes."""
