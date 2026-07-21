"""
FastAPI app: one endpoint, POST /search. Index is built once at startup
from whatever's already in bundles.db (run run_fhir_pipeline.py and
summarize.py first so there's actually something to search).
"""
from fastapi import FastAPI, Query

from store import init_db
from search_index import build_index, search as run_search

app = FastAPI(title="Clinical Record Search")

conn = init_db()
collection = build_index(conn)


@app.post("/search")
def search(
    q: str,
    resource_type: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
):
    results = run_search(collection, q, top_k=5, resource_type=resource_type,
                          date_from=date_from, date_to=date_to)
    return {"query": q, "results": results}
