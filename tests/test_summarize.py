import json
import sqlite3
from unittest.mock import patch
from datetime import date

from ingest import clean_record
from fhir_mapping import build_bundle
from store import init_db
from summarize import _extract_clinical_text, get_or_generate_summary

FAKE_SUMMARY = {
    "chief_concern": "Routine follow-up",
    "key_diagnoses": ["Hypertension"],
    "recent_records": ["2024-01-15 (lab): normal"],
    "flagged_anomalies": [],
    "disclaimer": "AI-generated summary, not a clinical decision",
}


def _sample_bundle():
    raw = {"mrn": "MRN-1", "name": "Jane Doe", "dob": "1985-04-12", "gender": "F",
           "record_type": "lab", "record_date": "2024-01-15", "text": "CBC normal, WBC 7.2"}
    rec = clean_record(raw, "json", seen=set())
    return build_bundle([rec])


def test_extract_clinical_text_pulls_dates_and_content():
    bundle = _sample_bundle()
    text = _extract_clinical_text(bundle)
    assert "2024-01-15" in text
    assert "CBC normal" in text


@patch("summarize._call_claude", return_value=FAKE_SUMMARY)
def test_summary_is_cached_second_call_skips_api(mock_call):
    conn = init_db(":memory:")
    bundle = _sample_bundle()

    first = get_or_generate_summary(conn, "abc123", bundle)
    second = get_or_generate_summary(conn, "abc123", bundle)

    assert first == FAKE_SUMMARY
    assert second == FAKE_SUMMARY
    mock_call.assert_called_once()  # second call should hit the cache, not Claude again
