from ingest import clean_record


def test_missing_name_gets_dropped():
    raw = {"mrn": "MRN-123", "name": "", "dob": "1990-01-01", "gender": "F",
           "record_type": "lab", "record_date": "2024-01-01", "text": "..."}
    assert clean_record(raw, "json", seen=set()) is None


def test_inconsistent_date_formats_all_parse():
    formats = ["1985-04-12", "04/12/1985", "12-Apr-1985"]
    seen = set()
    for i, d in enumerate(formats):
        raw = {"mrn": f"MRN-{i}", "name": f"Test Patient {i}", "dob": d,
               "gender": "F", "record_type": "lab", "record_date": "2024-01-01", "text": "x"}
        rec = clean_record(raw, "json", seen)
        assert rec.demographics.dob.isoformat() == "1985-04-12", f"failed on {d!r}"


def test_conflicting_mrn_format_same_patient():
    seen = set()
    raw1 = {"mrn": "MRN-00123", "name": "Jane Doe", "dob": "1985-04-12", "gender": "F",
            "record_type": "lab", "record_date": "2024-01-01", "text": "note 1"}
    raw2 = {"mrn": "00123", "name": "Jane Doe", "dob": "1985-04-12", "gender": "F",
            "record_type": "imaging", "record_date": "2024-01-02", "text": "note 2"}
    rec1 = clean_record(raw1, "json", seen)
    rec2 = clean_record(raw2, "csv", seen)
    assert rec1.demographics.patient_key == rec2.demographics.patient_key


def test_exact_duplicate_record_is_dropped():
    seen = set()
    raw = {"mrn": "MRN-999", "name": "Dup Patient", "dob": "1970-01-01", "gender": "M",
           "record_type": "lab", "record_date": "2024-01-01", "text": "same note"}
    first = clean_record(dict(raw), "csv", seen)
    second = clean_record(dict(raw), "csv", seen)
    assert first is not None
    assert second is None


def test_unparseable_date_logged_not_crashed():
    raw = {"mrn": "MRN-1", "name": "Test", "dob": "1990-01-01", "gender": "F",
           "record_type": "lab", "record_date": "not a date", "text": "x"}
    rec = clean_record(raw, "json", seen=set())
    assert rec.record_date is None
    assert any("unparseable" in a for a in rec.audit_log)
