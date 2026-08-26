"""Orchestrates the full post-meeting AI pipeline:

    transcript + markers + metadata
        -> analysis pass (Groq, fallback Gemini)  -> structured JSON
        -> notes pass (Groq, fallback Gemini)     -> prose notes
        -> deterministic validation
        -> (if hard issues) one rewrite pass
        -> final notes + any remaining warnings

One analysis pass and one notes pass per meeting for V1, deliberately, per
the product spec's instruction to prefer an efficient single final pass
over repeatedly re-sending the whole transcript — this module is the seam
where incremental/streaming meeting-memory processing could be added later
without changing anything above it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from intelligence.prompts.analysis import ANALYSIS_SYSTEM_PROMPT, build_analysis_user_prompt
from intelligence.prompts.notes import (
    build_notes_system_prompt,
    build_notes_user_prompt,
    build_rewrite_user_prompt,
)
from intelligence.router import AIRouter, AllProvidersFailedError
from intelligence.templates import NoteTemplate
from intelligence.validation.checks import ValidationIssue, has_hard_issues, run_checks

logger = logging.getLogger("meetnote.ai")

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class NotesGenerationFailed(Exception):
    """Raised only when every configured provider failed. The caller is
    expected to leave the meeting's notes_status as 'pending' and let the
    user retry once connectivity/providers recover — never lose the
    transcript over this."""


@dataclass
class NotesResult:
    analysis: dict
    notes_markdown: str
    provider_used: str
    warnings: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "analysis": self.analysis,
            "notes_markdown": self.notes_markdown,
            "provider_used": self.provider_used,
            "warnings": [w.to_dict() for w in self.warnings],
        }


def _parse_json_response(raw: str) -> dict:
    text = raw.strip()
    match = _JSON_FENCE.search(text)
    if match:
        text = match.group(1)
    return json.loads(text)


def generate_notes(
    router: AIRouter,
    transcript_text: str,
    meeting_title: str,
    meeting_date: str,
    duration_seconds: float,
    important_marker_offsets: list[float],
    template: NoteTemplate,
) -> NotesResult:
    try:
        analysis_result = router.complete(
            ANALYSIS_SYSTEM_PROMPT,
            build_analysis_user_prompt(
                transcript_text, meeting_title, important_marker_offsets, duration_seconds
            ),
            json_mode=True,
        )
    except AllProvidersFailedError as exc:
        raise NotesGenerationFailed(str(exc)) from exc

    try:
        analysis = _parse_json_response(analysis_result.text)
    except json.JSONDecodeError as exc:
        logger.error("Analysis response was not valid JSON: %s", exc)
        raise NotesGenerationFailed(f"AI analysis response could not be parsed as JSON: {exc}") from exc

    notes_system = build_notes_system_prompt(template)
    notes_user = build_notes_user_prompt(analysis, template, meeting_title, meeting_date)
    try:
        notes_result = router.complete(notes_system, notes_user)
    except AllProvidersFailedError as exc:
        raise NotesGenerationFailed(str(exc)) from exc

    notes_text = notes_result.text.strip()
    provider_used = notes_result.provider_name

    issues = run_checks(notes_text, template.sections, analysis)
    if has_hard_issues(issues):
        logger.info("Notes failed validation, running one rewrite pass: %s", issues)
        rewrite_user = build_rewrite_user_prompt(notes_text, [i.message for i in issues if i.hard])
        try:
            rewrite_result = router.complete(notes_system, rewrite_user)
            notes_text = rewrite_result.text.strip()
            provider_used = rewrite_result.provider_name
            issues = run_checks(notes_text, template.sections, analysis)
        except AllProvidersFailedError as exc:
            # Keep the original (imperfect) draft rather than losing notes
            # entirely; the unresolved issues are still reported below.
            logger.error("Rewrite pass failed, keeping original draft: %s", exc)

    return NotesResult(
        analysis=analysis,
        notes_markdown=notes_text,
        provider_used=provider_used,
        warnings=issues,
    )
