# Clinical Record Search

An AI-powered pipeline that ingests messy EHR exports, normalizes them to
HL7 FHIR R4, generates clinical summaries with an LLM, and exposes a
semantic search UI so a clinician can find relevant records in seconds.

## What's in here

```
.
├── models.py              # canonical Pydantic schema (Task 1)
├── ingest.py              # JSON/CSV loaders + cleaning (Task 1)
├── fhir_mapping.py        # Patient/Encounter/DocumentReference/DiagnosticReport mapping (Task 2)
├── store.py                # SQLite storage for bundles + summary cache
├── run_fhir_pipeline.py   # ties ingestion -> FHIR mapping -> storage together
├── summarize.py           # Groq-powered clinical summarization + caching (Task 3)
├── search_index.py        # chromadb + sentence-transformers indexing/search (Task 4)
├── api.py                 # FastAPI app exposing POST /search
├── frontend/index.html   # clinician search UI (Task 5)
├── data/                  # sample messy JSON/CSV EHR exports
└── tests/                 # pytest suite, one file per module
```

## Setup

**1. Clone and create a virtual environment**
```bash
git clone <this-repo-url>
cd clinical-data-pipeline
python3 -m venv venv
source venv/bin/activate
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```
Note: `chromadb` and `sentence-transformers` pull in torch and related
packages, so this install is noticeably heavier than a typical Python
project - expect it to take a few minutes.

**3. Set up your API key**
```bash
cp .env.example .env
```
Then edit `.env` and add your key:
```
GROQ_API_KEY=your-real-key-here
```
Get a free key at [console.groq.com](https://console.groq.com). (The
summarizer is written against Groq's OpenAI-compatible API - swapping to
Claude or OpenAI directly is a small, isolated change in `summarize.py`,
see Design Decisions below.)

## Running it end to end

Run these in order - each step depends on the SQLite data the previous
one wrote:

```bash
# 1. Ingest the sample data, clean it, map to FHIR, store in bundles.db
python3 run_fhir_pipeline.py

# 2. Generate (and cache) AI summaries for each patient
python3 summarize.py

# 3. Build the search index from the stored bundles + summaries
python3 search_index.py

# 4. Start the API
python3 -m uvicorn api:app --reload
```

Then open `frontend/index.html` directly in a browser (double-click it,
or `open frontend/index.html` on macOS) - it's a static file, no dev
server needed. It talks to the API at `http://127.0.0.1:8000`.

## Running the tests

```bash
pytest tests/ -v
```

All external calls are mocked in tests (`summarize._call_llm` and the
Anthropic/Groq client are never actually hit), so the suite runs fully
offline except for a one-time download of the `all-MiniLM-L6-v2` embedding
model on first run.

## Design decisions

**Patient identity.** Source records don't always agree on MRN formatting
(`MRN-00123` vs `00123`), so a raw MRN can't be trusted as the join key.
We derive our own `patient_key` as a hash of normalized MRN + name. This
is a real simplification - a production system would need proper patient
matching (an MPI), not a hash.

**Encounter is synthesized, not real.** FHIR R4 wants `DocumentReference`
and `DiagnosticReport` to reference an `Encounter` (a visit), but our
source data has no visit/encounter ID at all. Rather than skip the
reference or guess at grouping records into visits, we create one
synthetic `Encounter` per record - each note/lab/imaging result is treated
as its own encounter. A real Epic export would carry an actual encounter
ID we'd map 1:1 instead.

**Resource type mapping.** `lab` records become `DiagnosticReport`
(structured result data); everything else (`imaging`, `discharge_summary`)
becomes `DocumentReference` (it's fundamentally a note). Simple if/else,
not a generic dispatcher - there are only two branches.

**LLM provider.** The task spec named Claude or OpenAI; we used Groq's
OpenAI-compatible endpoint instead, since it has a genuinely free tier and
no billing setup required for a take-home project. This was a one-line
swap in practice (`anthropic` client -> `openai` client pointed at
`https://api.groq.com/openai/v1`) since the request/response shape is
close to identical - see `summarize.py`'s `_call_llm` function if you want
to switch it back.

**Summary caching.** Summaries are cached in SQLite, keyed by a hash of
`patient_id + extracted clinical text`. Re-running the pipeline on
unchanged data costs zero additional API calls; if a patient's records
change, the hash changes and a fresh summary is generated.

**Search indexing granularity.** Each individual clinical record
(`DocumentReference`/`DiagnosticReport`) is embedded as its own searchable
chunk, plus one more chunk per patient for the AI summary. This lets a
search match either the exact wording of a raw note, or a clinical concept
that only appears in the LLM's synthesized summary (e.g. searching
"hypertension" can match a summary's diagnosis list even if that word never
appears in any single raw record).

**No ORM, no service layers.** SQLite access is raw `sqlite3`, one table
for bundles and one for the summary cache - not worth a SQLAlchemy layer
for two tables. Same reasoning for chromadb and the FastAPI route: direct
calls, no repository pattern.

## Known limitations / what I'd improve with more time

- Patient matching is a hash, not real MPI logic - won't catch harder
  cases like a name typo or maiden-name changes.
- Encounters are fabricated per-record rather than reflecting real visits,
  since source data has no visit grouping signal.
- The search index has to be rebuilt manually after new data is ingested
  (`python3 search_index.py`) - no file-watching or automatic re-indexing.
- Summary quality was spot-checked manually against the source records for
  the 3 sample patients (verified chief concern, diagnoses, and dates
  matched the underlying FHIR data) - a production system would want a
  more systematic eval set and a rubric for clinical accuracy, not manual
  spot-checks.
