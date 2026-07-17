"""
Runs the full pipeline: ingest -> clean -> map to FHIR -> validate -> store.

fhir.resources validates on construction (it'll raise if a resource is
malformed), so "validation" here just means catching that per-patient
instead of one bad record killing the whole batch, and reporting what failed.
"""
from ingest import ingest
from fhir_mapping import build_bundle
from store import init_db, save_bundle


def run(json_path: str, csv_path: str, db_path: str = "bundles.db"):
    records = ingest(json_path, csv_path)

    # group by patient (same as build_bundles does internally, but we want
    # per-patient try/except here so one bad patient doesn't kill the batch)
    by_patient: dict[str, list] = {}
    for r in records:
        by_patient.setdefault(r.demographics.patient_key, []).append(r)

    conn = init_db(db_path)
    errors = []
    stored = 0

    for patient_key, patient_records in by_patient.items():
        try:
            bundle = build_bundle(patient_records)
            save_bundle(conn, patient_key, bundle)
            stored += 1
        except Exception as e:
            errors.append((patient_key, str(e)))

    print(f"stored {stored} bundles, {len(errors)} failed validation")
    for patient_key, msg in errors:
        print(f"  FAILED {patient_key}: {msg}")

    return stored, errors


if __name__ == "__main__":
    run("data/sample_export.json", "data/sample_scanned.csv")
