import json
from datetime import date, datetime, timezone

import pytest

import ask
import ingest
import retrieval


# ─── Αναγνώριση ΑΔΑ ──────────────────────────────────

@pytest.mark.parametrize("ada", [
    "ΨΤ1ΜΩ1Ρ-ΙΕΓ",
    "6ΧΡ9Ω1Ρ-ΤΗΑ",
    "9ΡΨΔΩ1Ρ-34Ξ",
    "ΡΨΗΗΩ1Ρ-ΒΡ0",
])
def test_ada_pattern_accepts_real_adas(ada):
    assert retrieval.ADA_PATTERN.match(ada)


@pytest.mark.parametrize("text", [
    "συντήρηση σχολικών κτιρίων",
    "πόσα ξόδεψε ο δήμος",
    "",
    "ΨΤ1ΜΩ1Ρ",
    "ένα δύο-τρία τέσσερα",
])
def test_ada_pattern_rejects_questions(text):
    assert not retrieval.ADA_PATTERN.match(text.upper())


def test_ada_pattern_is_case_insensitive_via_upper():
    assert retrieval.ADA_PATTERN.match("ψτ1μω1ρ-ιεγ".upper())


# ─── Μετατροπή ημερομηνίας ───────────────────────────

def ms_for(year, month, day):
    """Χτίζει timestamp σε ms από γνωστή ημερομηνία UTC — χωρίς μαντεψιές."""
    dt = datetime(year, month, day, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


@pytest.mark.parametrize("year,month,day", [
    (2026, 8, 5),
    (2023, 1, 3),
    (2024, 2, 29),
    (2025, 12, 31),
])
def test_ms_to_date_roundtrip(year, month, day):
    assert ingest.ms_to_date(ms_for(year, month, day)) == date(year, month, day)


def test_ms_to_date_matches_observed_api_value():
    """Τιμή που όντως επέστρεψε το API της Διαύγειας."""
    assert ingest.ms_to_date(1785888000000) == date(2026, 8, 5)


def test_ms_to_date_handles_none():
    assert ingest.ms_to_date(None) is None


# ─── Ανάλυση απόφασης από το API ─────────────────────

def test_parse_extracts_core_fields():
    row = ingest.parse({
        "ada": "ΨΤ1ΜΩ1Ρ-ΙΕΓ",
        "subject": "  Προμήθεια καυσίμων  ",
        "issueDate": ms_for(2026, 8, 5),
        "organizationId": "6265",
        "decisionTypeId": "Β.2.2",
        "documentUrl": "https://diavgeia.gov.gr/doc/ΨΤ1ΜΩ1Ρ-ΙΕΓ",
        "extraFieldValues": {
            "org": {"name": "ΔΗΜΟΣ ΡΟΔΟΥ"},
            "sponsor": [{"expenseAmount": {"amount": 100.5, "currency": "EUR"}}],
        },
    })
    assert row["ada"] == "ΨΤ1ΜΩ1Ρ-ΙΕΓ"
    assert row["subject"] == "Προμήθεια καυσίμων"
    assert row["issue_date"] == date(2026, 8, 5)
    assert row["expense_amount"] == 100.5
    assert row["currency"] == "EUR"
    assert row["organization_name"] == "ΔΗΜΟΣ ΡΟΔΟΥ"


def test_parse_sums_multiple_sponsors():
    row = ingest.parse({
        "ada": "X", "subject": "y",
        "extraFieldValues": {"sponsor": [
            {"expenseAmount": {"amount": 10.0, "currency": "EUR"}},
            {"expenseAmount": {"amount": 5.5, "currency": "EUR"}},
        ]},
    })
    assert row["expense_amount"] == 15.5


def test_parse_survives_missing_fields():
    row = ingest.parse({"ada": "X", "subject": "y"})
    assert row["expense_amount"] is None
    assert row["organization_name"] is None
    assert json.loads(row["raw"])["ada"] == "X"


def test_parse_handles_null_extra_fields():
    row = ingest.parse({"ada": "X", "subject": "y", "extraFieldValues": None})
    assert row["expense_amount"] is None


def test_parse_strips_whitespace_from_subject():
    row = ingest.parse({"ada": "X", "subject": "\n  θέμα  \t"})
    assert row["subject"] == "θέμα"


# ─── Διόρθωση παραπομπών ─────────────────────────────

VALID = ["ΨΤ1ΜΩ1Ρ-ΙΕΓ", "6ΧΡ9Ω1Ρ-ΤΗΑ", "9ΡΨΔΩ1Ρ-34Ξ"]


def test_repair_fixes_transcription_error():
    """Πραγματικό σφάλμα που έκανε το μοντέλο: έχασε έναν χαρακτήρα."""
    text = "Δες την απόφαση [9ΨΔΩ1Ρ-34Ξ] για λεπτομέρειες."
    fixed, repaired, dropped = ask.repair_citations(text, VALID)
    assert "9ΡΨΔΩ1Ρ-34Ξ" in fixed
    assert repaired == [("9ΨΔΩ1Ρ-34Ξ", "9ΡΨΔΩ1Ρ-34Ξ")]
    assert dropped == []


def test_repair_leaves_valid_citations_alone():
    text = "Η απόφαση [ΨΤ1ΜΩ1Ρ-ΙΕΓ] αφορά καύσιμα."
    fixed, repaired, dropped = ask.repair_citations(text, VALID)
    assert fixed == text
    assert repaired == []
    assert dropped == []


def test_repair_reports_fabricated_ada():
    text = "Σύμφωνα με την [ΑΒΓΔΕΖΗ-ΘΙΚ] απόφαση."
    _, repaired, dropped = ask.repair_citations(text, VALID)
    assert dropped == ["ΑΒΓΔΕΖΗ-ΘΙΚ"]
    assert repaired == []


def test_repair_handles_empty_input():
    assert ask.repair_citations("", VALID) == ("", [], [])
    assert ask.repair_citations("κείμενο", []) == ("κείμενο", [], [])