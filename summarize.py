"""
Turns a patient's FHIR Bundle into a short clinical summary using an LLM.

Design notes:
- We extract just the clinically relevant text (document descriptions,
  diagnostic report conclusions, dates) rather than dumping the raw FHIR
  JSON at the model - that's mostly boilerplate (identifiers, meta, coding
  systems) that wastes tokens and adds noise.
- Using Groq here (OpenAI-compatible API, fast + free tier) rather than
  calling Anthropic/OpenAI directly - it's a one-line swap since Groq
  implements the same chat completions shape via the `openai` SDK.
- The model is asked to return fixed-key JSON so the frontend doesn't need
  to parse free-form prose.
- Cached by hash(patient_id + extracted text) so re-running the pipeline on
  unchanged data doesn't re-spend API calls.
"""
import os
import json
import hashlib
from dotenv import load_dotenv
from openai import OpenAI
from fhir.resources.bundle import Bundle

from store import init_db

load_dotenv()  # picks up GROQ_API_KEY from a local .env file, not committed

MODEL = "openai/gpt-oss-120b"  # Groq's current general-purpose model; update if deprecated

SYSTEM_PROMPT = """You are summarizing a patient's clinical record history for a clinician.
Respond with ONLY a JSON object (no markdown, no preamble) with exactly these keys:
- chief_concern: string, one sentence
- key_diagnoses: list of strings
- recent_records: list of strings, each like "2024-01-15 (lab): short description"
- flagged_anomalies: list of strings, empty list if nothing notable
- disclaimer: always exactly "AI-generated summary, not a clinical decision"

Keep the whole thing clinically accurate and under 200 words total. Do not invent
information that isn't present in the records provided."""


def _extract_clinical_text(bundle: Bundle) -> str:
    """Pulls out just the human-readable clinical content from a Bundle."""
    lines = []
    for entry in bundle.entry:
        resource = entry.resource
        rtype = resource.__resource_type__
        if rtype == "DocumentReference":
            date = resource.date.date().isoformat() if resource.date else "unknown date"
            doc_type = resource.type.text if resource.type else "document"
            lines.append(f"{date} ({doc_type}): {resource.description}")
        elif rtype == "DiagnosticReport":
            date = resource.effectiveDateTime.date().isoformat() if resource.effectiveDateTime else "unknown date"
            report_type = resource.code.text if resource.code else "report"
            lines.append(f"{date} ({report_type}): {resource.conclusion}")
    return "\n".join(lines)


def _record_hash(patient_id: str, clinical_text: str) -> str:
    return hashlib.sha256(f"{patient_id}|{clinical_text}".encode()).hexdigest()


def _call_llm(clinical_text: str) -> dict:
    client = OpenAI(
        api_key=os.environ.get("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
    )
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=500,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": clinical_text},
        ],
    )
    raw = response.choices[0].message.content.strip()
    # models sometimes wrap JSON in ```json fences despite instructions - strip if present
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # don't let a malformed response crash the whole batch - surface it as-is
        return {
            "chief_concern": "Summary generation failed to parse",
            "key_diagnoses": [],
            "recent_records": [],
            "flagged_anomalies": [],
            "disclaimer": "AI-generated summary, not a clinical decision",
            "_raw_response": raw,
        }


def get_or_generate_summary(conn, patient_id: str, bundle: Bundle) -> dict:
    clinical_text = _extract_clinical_text(bundle)
    record_hash = _record_hash(patient_id, clinical_text)

    cached = conn.execute(
        "SELECT summary_json FROM summaries WHERE patient_id = ? AND record_hash = ?",
        (patient_id, record_hash),
    ).fetchone()
    if cached:
        return json.loads(cached[0])

    summary = _call_llm(clinical_text)

    conn.execute(
        "INSERT OR REPLACE INTO summaries (patient_id, record_hash, summary_json) VALUES (?, ?, ?)",
        (patient_id, record_hash, json.dumps(summary)),
    )
    conn.commit()
    return summary


if __name__ == "__main__":
    from store import all_patient_ids, get_bundle

    conn = init_db()
    for patient_id in all_patient_ids(conn):
        bundle = get_bundle(conn, patient_id)
        summary = get_or_generate_summary(conn, patient_id, bundle)
        print(f"--- {patient_id} ---")
        print(json.dumps(summary, indent=2))