from intelligence.validation.checks import has_hard_issues, run_checks

SECTIONS = ["Meeting Title", "Decisions", "Action Items"]

GOOD_ANALYSIS = {
    "attendees": ["Divy", "Rahul"],
    "action_items": [{"task": "Prepare budget", "owner": "Divy", "deadline": "Friday"}],
    "deadlines": ["Friday"],
}

GOOD_NOTES = """## Meeting Title
House Coordination Meeting

## Decisions
The team finalized the venue for the event.

## Action Items
Divy will prepare the budget by Friday.
"""


def test_clean_notes_pass():
    issues = run_checks(GOOD_NOTES, SECTIONS, GOOD_ANALYSIS)
    assert not has_hard_issues(issues)


def test_emoji_is_flagged():
    notes = GOOD_NOTES + "\nGreat meeting! \U0001F389"
    issues = run_checks(notes, SECTIONS, GOOD_ANALYSIS)
    assert any(i.code == "emoji" for i in issues)
    assert has_hard_issues(issues)


def test_em_dash_is_flagged():
    notes = GOOD_NOTES.replace("Friday.", "Friday — no exceptions.")
    issues = run_checks(notes, SECTIONS, GOOD_ANALYSIS)
    assert any(i.code == "em_dash" for i in issues)


def test_filler_phrase_is_flagged():
    notes = "Here is a summary of the meeting.\n" + GOOD_NOTES
    issues = run_checks(notes, SECTIONS, GOOD_ANALYSIS)
    assert any(i.code == "filler_phrase" for i in issues)


def test_missing_section_is_flagged():
    notes = "## Meeting Title\nHouse Coordination Meeting\n\n## Decisions\nVenue finalized.\n"
    issues = run_checks(notes, SECTIONS, GOOD_ANALYSIS)
    missing = [i for i in issues if i.code == "missing_sections"]
    assert missing and "Action Items" in missing[0].message


def test_dropped_owner_name_is_flagged():
    notes = GOOD_NOTES.replace("Divy", "someone")
    issues = run_checks(notes, SECTIONS, GOOD_ANALYSIS)
    assert any(i.code == "entities_dropped" for i in issues)
