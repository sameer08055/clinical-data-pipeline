"""
Loads raw JSON/CSV exports and turns them into PatientRecord objects.

Design note: both loaders just produce a list of plain dicts with the same
rough keys (mrn, name, dob, gender, record_type, record_date, text). All the
actual cleaning happens in one place (clean_record) so we don't have to
duplicate cleaning logic per source format.
"""
import csv
import json
import hashlib
from datetime import date
from dateutil import parser as dateparser

from models import PatientRecord, Demographics

GENDER_MAP = {
    "m": "male", "male": "male", "1": "male",
    "f": "female", "female": "female", "2": "female",
    "u": "unknown", "unknown": "unknown",
}


def load_json(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def load_csv(path: str) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def _parse_date(raw: str | None) -> tuple[date | None, str]:
    """Returns (parsed_date_or_None, reason_if_it_failed)."""
    if not raw:
        return None, "missing"
    try:
        return dateparser.parse(raw).date(), ""
    except (dateparser.ParserError, ValueError, OverflowError):
        return None, f"unparseable date: {raw!r}"


def _patient_key(mrn: str | None, name: str) -> str:
    # We don't fully trust MRNs to be consistent across records (formatting
    # varies, and sometimes a record just won't have one), so the "real" id
    # we use downstream is a hash of MRN + normalized name. Good enough for
    # this exercise - a real system would need actual patient matching (MPI).
    basis = f"{mrn or ''}|{name.strip().lower()}"
    return hashlib.sha1(basis.encode()).hexdigest()[:12]


def clean_record(raw: dict, source_format: str, seen: set[str]) -> PatientRecord | None:
    audit: list[str] = []

    name = (raw.get("name") or "").strip()
    if not name:
        # can't build a patient key without a name, and a nameless record
        # isn't useful for the summary/search tasks either - drop it
        return None

    mrn_raw = raw.get("mrn")
    mrn = mrn_raw.replace("MRN-", "").strip() if mrn_raw else None
    if mrn != mrn_raw:
        audit.append(f"mrn: stripped prefix ({mrn_raw!r} -> {mrn!r})")

    dob, dob_reason = _parse_date(raw.get("dob"))
    if dob_reason:
        audit.append(f"dob: {dob_reason}")

    gender_raw = (raw.get("gender") or "").strip().lower()
    gender = GENDER_MAP.get(gender_raw, "unknown")
    if gender_raw and gender != gender_raw:
        audit.append(f"gender: mapped {gender_raw!r} -> {gender!r}")

    record_date, rd_reason = _parse_date(raw.get("record_date"))
    if rd_reason:
        audit.append(f"record_date: {rd_reason}")

    text = (raw.get("text") or "").strip()

    # dedup: same patient + same record content = same record.
    # `seen` is passed in by the caller rather than kept as global state,
    # so tests/callers control their own dedup scope instead of sharing one.
    dedup_key = hashlib.sha1(f"{mrn}|{name}|{record_date}|{text}".encode()).hexdigest()
    if dedup_key in seen:
        return None
    seen.add(dedup_key)

    demo = Demographics(
        patient_key=_patient_key(mrn, name),
        mrn=mrn,
        name=name,
        dob=dob,
        gender=gender,
    )

    return PatientRecord(
        demographics=demo,
        record_type=raw.get("record_type", "unknown"),
        record_date=record_date,
        text=text,
        source_format=source_format,
        audit_log=audit,
    )


def ingest(json_path: str, csv_path: str) -> list[PatientRecord]:
    seen: set[str] = set()
    records = []
    for raw in load_json(json_path):
        rec = clean_record(raw, "json", seen)
        if rec:
            records.append(rec)
    for raw in load_csv(csv_path):
        rec = clean_record(raw, "csv", seen)
        if rec:
            records.append(rec)
    return records


if __name__ == "__main__":
    recs = ingest("data/sample_export.json", "data/sample_scanned.csv")
    print(f"ingested {len(recs)} records")
    for r in recs:
        print(f"  - {r.demographics.name} ({r.demographics.patient_key}) [{r.record_type}] audit={len(r.audit_log)} entries")
