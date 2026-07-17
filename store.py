"""
Stores FHIR Bundles as JSON blobs in SQLite. One table, no ORM -
sqlalchemy would be overkill for storing/retrieving one JSON blob per patient.
"""
import sqlite3
import json
from fhir.resources.bundle import Bundle

DB_PATH = "bundles.db"


def init_db(path: str = DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bundles (
            patient_id TEXT PRIMARY KEY,
            bundle_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def save_bundle(conn, patient_id: str, bundle: Bundle):
    conn.execute(
        "INSERT OR REPLACE INTO bundles (patient_id, bundle_json) VALUES (?, ?)",
        (patient_id, bundle.model_dump_json()),
    )
    conn.commit()


def get_bundle(conn, patient_id: str) -> Bundle | None:
    row = conn.execute("SELECT bundle_json FROM bundles WHERE patient_id = ?", (patient_id,)).fetchone()
    if row is None:
        return None
    return Bundle(**json.loads(row[0]))


def all_patient_ids(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT patient_id FROM bundles").fetchall()]
