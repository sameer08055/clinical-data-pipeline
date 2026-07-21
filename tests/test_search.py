from unittest.mock import patch
from ingest import clean_record
from fhir_mapping import build_bundle
from store import init_db, save_bundle
from search_index import build_index, search

FAKE_SUMMARY = {"chief_concern": "Routine check", "key_diagnoses": ["Hypertension"]}


def _seed_db(conn):
    raw1 = {"mrn": "MRN-1", "name": "Jane Doe", "dob": "1985-04-12", "gender": "F",
            "record_type": "imaging", "record_date": "2024-01-15", "text": "Chest X-ray clear, no acute findings"}
    raw2 = {"mrn": "MRN-2", "name": "John Smith", "dob": "1970-01-01", "gender": "M",
            "record_type": "lab", "record_date": "2024-02-01", "text": "Elevated blood pressure reading, 150/95"}
    seen = set()
    rec1 = clean_record(raw1, "json", seen)
    rec2 = clean_record(raw2, "json", seen)
    save_bundle(conn, rec1.demographics.patient_key, build_bundle([rec1]))
    save_bundle(conn, rec2.demographics.patient_key, build_bundle([rec2]))


@patch("search_index.get_or_generate_summary", return_value=FAKE_SUMMARY)
def test_search_finds_relevant_record(mock_summary, tmp_path):
    conn = init_db(":memory:")
    _seed_db(conn)
    collection = build_index(conn, chroma_path=str(tmp_path / "chroma_test"))

    results = search(collection, "blood pressure hypertension", top_k=3)

    assert len(results) > 0
    assert any("blood pressure" in r["text"].lower() or r["resource_type"] == "Summary" for r in results)


@patch("search_index.get_or_generate_summary", return_value=FAKE_SUMMARY)
def test_search_filters_by_resource_type(mock_summary, tmp_path):
    conn = init_db(":memory:")
    _seed_db(conn)
    collection = build_index(conn, chroma_path=str(tmp_path / "chroma_test2"))

    results = search(collection, "findings", top_k=5, resource_type="DiagnosticReport")

    assert all(r["resource_type"] == "DiagnosticReport" for r in results)
