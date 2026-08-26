"""Prompt for the structured meeting-analysis pass.

Transcript -> strict JSON meeting memory (decisions, action items, owners,
deadlines, important points, open questions). This is the one pass over the
full transcript per meeting (see intelligence/analysis/service.py) — later
phases can add incremental/streaming meeting-memory processing without
changing this prompt's contract.
"""

from __future__ import annotations

ANALYSIS_SYSTEM_PROMPT = """You are analyzing a meeting transcript to extract a factual, structured record \
of what happened. You must be strictly faithful to the transcript.

Rules:
- Only include a decision if the transcript shows it was actually finalized or agreed, not merely \
suggested or discussed. If people proposed something but did not clearly agree on it, put it in \
"proposals_not_decided", never in "decisions".
- Only include an action item if someone was actually assigned or volunteered for a task.
- Only include a deadline or date if it was explicitly stated in the transcript. Do not infer or \
estimate dates.
- Never invent attendee names, owners, decisions, deadlines, or facts that are not in the transcript.
- If information for a field is not present in the transcript, return an empty list for it rather than \
guessing.
- Segments marked as "unavailable" in the transcript are missing audio, not silence — do not treat a gap \
as meaning nothing happened there.
- Pay closer attention to any timestamp listed under "marked_important_at" — the person in the meeting \
flagged that moment as significant.

Respond with a single JSON object only, no prose before or after it, matching exactly this shape:
{
  "attendees": ["string, only if a name was stated"],
  "agenda": ["string"],
  "decisions": ["string, a finalized decision"],
  "proposals_not_decided": ["string, something suggested but not agreed"],
  "action_items": [{"task": "string", "owner": "string or null if unassigned", "deadline": "string or null"}],
  "deadlines": ["string, restated plainly, e.g. 'Budget due Friday'"],
  "important_points": ["string, a notable outcome or discussion point"],
  "open_questions": ["string, something left unresolved"]
}"""


def build_analysis_user_prompt(
    transcript_text: str,
    meeting_title: str,
    important_marker_offsets: list[float],
    duration_seconds: float,
) -> str:
    markers_str = (
        ", ".join(f"{int(m // 60)}m{int(m % 60):02d}s" for m in important_marker_offsets)
        if important_marker_offsets
        else "none"
    )
    return f"""Meeting title: {meeting_title}
Duration: {int(duration_seconds // 60)} minutes
marked_important_at: {markers_str}

Transcript:
---
{transcript_text}
---

Extract the structured meeting record as instructed."""
