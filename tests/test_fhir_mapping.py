from datetime import date
from models import PatientRecord, Demographics
from fhir_mapping import to_patient, to_encounter, to_document_reference, to_diagnostic_report, build_bundle


def _record(record_type="lab", patient_key="abc123"):
    return PatientRecord(
        demographics=Demographics(patient_key=patient_key, name="Jane Doe",
                                   dob=date(1985, 4, 12), gender="female"),
        record_type=record_type,
        record_date=date(2024, 1, 15),
        text="Test note content",
        source_format="json",
    )


def test_to_patient_maps_core_fields():
    rec = _record()
    patient = to_patient(rec)
    assert patient.id == "abc123"
    assert patient.gender == "female"
    assert patient.birthDate == date(1985, 4, 12)


def test_to_encounter_links_to_patient():
    rec = _record()
    encounter = to_encounter(rec, 0)
    assert encounter.__resource_type__ == "Encounter"
    assert encounter.subject.reference == "Patient/abc123"


def test_lab_record_becomes_diagnostic_report_with_encounter():
    rec = _record(record_type="lab")
    report = to_diagnostic_report(rec, 0, encounter_id="abc123-encounter-0")
    assert report.__resource_type__ == "DiagnosticReport"
    assert report.subject.reference == "Patient/abc123"
    assert report.encounter.reference == "Encounter/abc123-encounter-0"


def test_imaging_record_becomes_document_reference_with_encounter():
    rec = _record(record_type="imaging")
    doc = to_document_reference(rec, 0, encounter_id="abc123-encounter-0")
    assert doc.__resource_type__ == "DocumentReference"
    assert doc.subject.reference == "Patient/abc123"
    assert doc.context[0].reference == "Encounter/abc123-encounter-0"


def test_build_bundle_mixes_resource_types_correctly():
    records = [_record(record_type="lab"), _record(record_type="discharge_summary")]
    bundle = build_bundle(records)
    resource_types = [e.resource.__resource_type__ for e in bundle.entry]
    # Patient, then (Encounter, DiagnosticReport) for the lab record,
    # then (Encounter, DocumentReference) for the discharge summary
    assert resource_types == ["Patient", "Encounter", "DiagnosticReport", "Encounter", "DocumentReference"]