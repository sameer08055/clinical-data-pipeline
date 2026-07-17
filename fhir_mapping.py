"""
Maps our cleaned PatientRecord objects to FHIR R4 resources.

Mapping decision: "lab" records become DiagnosticReport (structured result
data), everything else (imaging, discharge_summary, etc) becomes
DocumentReference (it's fundamentally a note/document). Four resource
types total - Patient, DocumentReference, DiagnosticReport, Encounter.

Encounter decision: source records have no visit/encounter ID at all
(no field for it), so we can't group multiple records into one real visit
without guessing. Instead we synthesize one Encounter per record - each
note/lab/imaging result is treated as its own encounter. This is a
simplification flagged in the README; a real Epic export would carry an
actual encounter ID we'd map 1:1 instead of fabricating one.

One function per resource type, no generic "field mapper" abstraction -
there's only 4 of these and they don't share enough structure to be
worth unifying.
"""
from itertools import groupby
from datetime import datetime, timezone

from fhir.resources.patient import Patient
from fhir.resources.documentreference import DocumentReference, DocumentReferenceContent
from fhir.resources.attachment import Attachment
from fhir.resources.diagnosticreport import DiagnosticReport
from fhir.resources.encounter import Encounter
from fhir.resources.coding import Coding
from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.reference import Reference
from fhir.resources.humanname import HumanName
from fhir.resources.codeableconcept import CodeableConcept

from models import PatientRecord


def to_patient(record: PatientRecord) -> Patient:
    demo = record.demographics
    # HumanName wants given/family split - we only ever collected a single
    # "name" string from source data, so we just put the whole thing in
    # `text` rather than pretending we can reliably split "Jane Doe" into
    # given/family (that breaks on real-world names anyway).
    return Patient(
        id=demo.patient_key,
        name=[HumanName(text=demo.name)],
        gender=demo.gender,
        birthDate=demo.dob,
    )


def to_encounter(record: PatientRecord, index: int) -> Encounter:
    # Synthetic - see module docstring. "ambulatory" is a reasonable default
    # class since our source data gives no signal about inpatient vs outpatient.
    return Encounter(
        id=f"{record.demographics.patient_key}-encounter-{index}",
        status="finished",
        class_fhir=[CodeableConcept(coding=[Coding(code="AMB", display="ambulatory")])],
        subject=Reference(reference=f"Patient/{record.demographics.patient_key}"),
    )


def to_document_reference(record: PatientRecord, index: int, encounter_id: str) -> DocumentReference:
    # FHIR R4 requires DocumentReference.content (1..*) - it's how the
    # resource actually points at the document. We don't have a real file to
    # attach, so we embed the note text directly as the attachment content.
    attachment = Attachment(contentType="text/plain", title=record.text[:100])
    return DocumentReference(
        id=f"{record.demographics.patient_key}-doc-{index}",
        status="current",
        subject=Reference(reference=f"Patient/{record.demographics.patient_key}"),
        date=_to_fhir_datetime(record.record_date),
        type=CodeableConcept(text=record.record_type),
        description=record.text[:200],  # keep it short, this is a summary field not the full note
        content=[DocumentReferenceContent(attachment=attachment)],
        context=[Reference(reference=f"Encounter/{encounter_id}")],
    )


def to_diagnostic_report(record: PatientRecord, index: int, encounter_id: str) -> DiagnosticReport:
    return DiagnosticReport(
        id=f"{record.demographics.patient_key}-report-{index}",
        status="final",
        code=CodeableConcept(text=record.record_type),
        subject=Reference(reference=f"Patient/{record.demographics.patient_key}"),
        encounter=Reference(reference=f"Encounter/{encounter_id}"),
        effectiveDateTime=_to_fhir_datetime(record.record_date),
        conclusion=record.text[:200],
    )


def _to_fhir_datetime(d):
    # FHIR wants a timezone-aware datetime, our records only carry a plain
    # date - midnight UTC is fine, we just don't know the real time of day.
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def build_bundle(patient_records: list[PatientRecord]) -> Bundle:
    """One patient's records in, one FHIR Bundle out."""
    patient_key = patient_records[0].demographics.patient_key
    patient = to_patient(patient_records[0])

    entries = [BundleEntry(resource=patient, fullUrl=f"Patient/{patient_key}")]

    for i, record in enumerate(patient_records):
        encounter = to_encounter(record, i)
        entries.append(BundleEntry(resource=encounter, fullUrl=f"Encounter/{encounter.id}"))

        if record.record_type == "lab":
            resource = to_diagnostic_report(record, i, encounter.id)
        else:
            resource = to_document_reference(record, i, encounter.id)
        entries.append(BundleEntry(resource=resource, fullUrl=f"{resource.__resource_type__}/{resource.id}"))

    return Bundle(type="collection", entry=entries)


def build_bundles(records: list[PatientRecord]) -> dict[str, Bundle]:
    """Groups records by patient and builds one Bundle each. Returns {patient_key: Bundle}."""
    records_sorted = sorted(records, key=lambda r: r.demographics.patient_key)
    bundles = {}
    for patient_key, group in groupby(records_sorted, key=lambda r: r.demographics.patient_key):
        bundles[patient_key] = build_bundle(list(group))
    return bundles