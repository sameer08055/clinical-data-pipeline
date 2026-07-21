"""
Builds a chromadb collection from everything we've got: each individual
clinical record (DocumentReference/DiagnosticReport) becomes one searchable
chunk, plus one more chunk per patient for the AI summary.

Using chromadb's built-in SentenceTransformerEmbeddingFunction rather than
calling sentence-transformers ourselves and feeding raw vectors in - chroma
already wraps that, no need to manage embeddings by hand.
"""
from datetime import datetime, date
import json
import chromadb
from chromadb.utils import embedding_functions

from store import init_db, all_patient_ids, get_bundle
from summarize import get_or_generate_summary

CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "clinical_records"


def _date_epoch(d: date | None) -> int:
    if d is None:
        return 0
    return int(datetime(d.year, d.month, d.day).timestamp())


def _patient_name(bundle) -> str:
    patient = next(e.resource for e in bundle.entry if e.resource.__resource_type__ == "Patient")
    return patient.name[0].text if patient.name else "Unknown"


def build_index(conn, chroma_path: str = CHROMA_PATH):
    client = chromadb.PersistentClient(path=chroma_path)
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    collection = client.get_or_create_collection(
        COLLECTION_NAME, embedding_function=ef, metadata={"hnsw:space": "cosine"}
    )

    ids, documents, metadatas = [], [], []

    for patient_id in all_patient_ids(conn):
        bundle = get_bundle(conn, patient_id)
        patient_name = _patient_name(bundle)

        for entry in bundle.entry:
            resource = entry.resource
            rtype = resource.__resource_type__

            if rtype == "DocumentReference":
                d = resource.date.date() if resource.date else None
                text = resource.description or ""
            elif rtype == "DiagnosticReport":
                d = resource.effectiveDateTime.date() if resource.effectiveDateTime else None
                text = resource.conclusion or ""
            else:
                continue  # Patient/Encounter resources aren't independently searchable

            ids.append(resource.id)
            documents.append(text)
            metadatas.append({
                "patient_id": patient_id,
                "patient_name": patient_name,
                "resource_type": rtype,
                "date": d.isoformat() if d else "",
                "date_epoch": _date_epoch(d),
            })

        # also index the AI summary - lets a search match on diagnoses/concerns
        # even if that exact wording never appears in a single raw record.
        # We store the full structured summary as JSON in metadata too, since
        # the frontend detail drawer needs recent_records/anomalies/disclaimer,
        # not just the short text we embed on.
        summary = get_or_generate_summary(conn, patient_id, bundle)
        summary_text = summary.get("chief_concern", "") + " " + " ".join(summary.get("key_diagnoses", []))
        ids.append(f"{patient_id}-summary")
        documents.append(summary_text)
        metadatas.append({
            "patient_id": patient_id,
            "patient_name": patient_name,
            "resource_type": "Summary",
            "date": "",
            "date_epoch": 0,
            "summary_json": json.dumps(summary),
        })

    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    return collection


def search(collection, query: str, top_k: int = 5, resource_type: str | None = None,
           date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    conditions = []
    if resource_type:
        conditions.append({"resource_type": resource_type})
    if date_from or date_to:
        date_range = {}
        if date_from:
            date_range["$gte"] = _date_epoch(date.fromisoformat(date_from))
        if date_to:
            date_range["$lte"] = _date_epoch(date.fromisoformat(date_to))
        conditions.append({"date_epoch": date_range})

    where = None
    if len(conditions) > 1:
        where = {"$and": conditions}
    elif conditions:
        where = conditions[0]

    results = collection.query(query_texts=[query], n_results=top_k, where=where)

    out = []
    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]
    for i in range(len(ids)):
        # cosine distance is 0 (identical) to 2 (opposite) - flip to a 0-1 "relevance" score
        relevance = round(max(0.0, 1 - distances[i] / 2), 3)
        out.append({**metas[i], "text": docs[i], "relevance_score": relevance})
    return out


if __name__ == "__main__":
    conn = init_db()
    collection = build_index(conn)
    print(f"indexed {collection.count()} chunks")
    for r in search(collection, "appendectomy follow up"):
        print(r)