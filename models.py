"""
Canonical shape every record gets normalized into, regardless of whether
it came in as JSON or CSV. Everything downstream (FHIR mapping, summaries,
search) reads from this, not from the raw source formats.
"""
from datetime import date
from typing import Optional
from pydantic import BaseModel


class Demographics(BaseModel):
    patient_key: str  # our own stable id, not the source MRN (see clean_record)
    mrn: Optional[str] = None
    name: str
    dob: Optional[date] = None
    gender: Optional[str] = None  # normalized to FHIR's male/female/other/unknown


class PatientRecord(BaseModel):
    demographics: Demographics
    record_type: str  # "lab", "imaging", "discharge_summary", etc
    record_date: Optional[date] = None
    text: str  # the actual note/report content
    source_format: str  # "json" or "csv", just for debugging
    audit_log: list[str] = []  # e.g. "mrn: stripped prefix (MRN-00123 -> 00123)"
