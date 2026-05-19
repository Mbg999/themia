# Requirement Verification Questions
**Run ID:** 2026-05-19t09-35-00z-thermia-mvp
**Project:** Thermia — Spanish Legal Document Analyzer
**Pass:** 1 (clarifying questions — await answers before generating requirements.md)

---

<!-- axis: Needs -->
## Question 1: LLM Provider and Model

The retrieval pipeline feeds chunks to an LLM via LangChain for the final reasoning step (summary, implications, citations). Which provider and model should be used?

A) OpenAI (`gpt-4o` or `gpt-4o-mini`)
B) Anthropic Claude (via API — e.g. `claude-sonnet-4-6`)
C) A locally-hosted model via Ollama (e.g. `llama3.1`, `mistral`)
D) Google Gemini
X) Other (please describe after [Answer]: tag below)

[Answer]: X) Groq, llama-3.1-8b-instant, CONTEXT WINDOW (TOKENS): 131,072. MAX COMPLETION TOKENS: 131,072. Documentation: https://console.groq.com/docs/api-reference#responses-create. Use an environment variable for the API key; I will add the value of this manually.
-

---

<!-- axis: Needs -->
## Question 2: Embedding Model and Vector Dimension

The ingestion pipeline generates embeddings stored in pgvector. The embedding model determines the vector dimension (e.g. OpenAI `text-embedding-3-small` → 1536d, `text-embedding-3-large` → 3072d, local models vary). Which embedding model should be used?

A) OpenAI `text-embedding-3-small` (1536 dimensions, good cost/quality balance)
B) OpenAI `text-embedding-ada-002` (1536 dimensions, legacy but stable)
C) A local model via `sentence-transformers` (e.g. `paraphrase-multilingual-mpnet-base-v2` — 768d, Spanish-capable)
D) The same provider as the LLM (auto-match: OpenAI embeddings if OpenAI LLM, etc.)
X) Other (please describe after [Answer]: tag below)

[Answer]: X we will use Cohere embed-multilingual-v3.0 via API, Dimensions: 1024, Context Length 512, Similarity Metric: Cosine Similarity. With documentation available at https://docs.cohere.com/reference/embed. Use an environment variable for the API key; I will add the value of this manually.

---

<!-- axis: Limits -->
## Question 3: Sub-Chunking Token Threshold

The ingestion pipeline sub-chunks articles only "if > X tokens (overlap 50)". What threshold value should X be? This controls how aggressively long articles are split.

A) 512 tokens (aggressive — keeps chunks small for precision)
B) 800 tokens (balanced — typical for legal text with long articles)
C) 1024 tokens (conservative — fewer sub-chunks, preserves more context per chunk)
D) 1500 tokens (minimal splitting — only very long articles get split)
X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

<!-- axis: Needs -->
## Question 4: PDF Text Extraction Library

The `POST /analyze` endpoint extracts text from the uploaded PDF before processing. Which Python library should be used for PDF text extraction?

A) `pdfplumber` (good for structured PDFs with tables; pure Python)
B) `PyMuPDF` / `fitz` (fast, robust; handles complex layouts well)
C) `pypdf` (lightweight; pure Python but less precise on complex layouts)
D) `pdfminer.six` (thorough text extraction; handles multi-column layouts)
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

<!-- axis: Limits -->
## Question 5: Authentication and Access Control

For the MVP, does the `POST /analyze` endpoint (and any other API endpoints) require authentication?

A) No authentication — open endpoint (internal/local use only)
B) Simple API key in the `Authorization` header (`Bearer <key>` from environment variable)
C) Basic HTTP auth (username/password from environment variables)
D) JWT token (requires a login endpoint — adds significant scope)
X) Other (please describe after [Answer]: tag below)

[Answer]: B, simple api key auth, with the key stored in an environment variable. The frontend will include this API key in the `Authorization` header of requests to the backend. This provides a basic level of security for the MVP while keeping implementation straightforward.

---

<!-- axis: Context -->
## Question 6: Docker Compose Services

"Everything must run locally with Docker." What services should the `docker-compose.yml` define?

A) `postgres` + `thermia-back` only (frontend served separately with `ng serve`)
B) `postgres` + `thermia-back` + `thermia-front` (nginx serving Angular build)
C) `postgres` + `thermia-back` + `thermia-front` + `pgadmin` (DB admin UI for local dev)
D) Only `postgres` — both apps run natively outside Docker (Docker = DB only)
X) Other (please describe after [Answer]: tag below)

[Answer]: X): `thermia-back` + `thermia-front` (nginx serving Angular build). Just use localhost for development, we will deploy this to a VPS with docker. The postgres is already on the VPS, localhost development must connect to it via SSH, and via localhost for production. Use environment variables for the connection configuration; I will add the value of this manually.

---

<!-- axis: Expectations -->
## Question 7: API Response JSON Structure

The `POST /analyze` endpoint must return a structured response. What JSON schema should the response follow?

A) Flat object: `{ "summary": "...", "implications": ["..."], "citations": ["..."], "error": null }`
B) Nested sections: `{ "analysis": { "resumen": "...", "implicaciones_legales": ["..."], "fundamento_juridico": ["..."] }, "metadata": { "chunks_used": 5, "processing_time_ms": 1200 } }`
C) Keep it minimal for MVP — single `result` string with markdown formatting
D) Match the LLM output directly — let the LLM define the JSON via a structured output prompt
X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

<!-- axis: Acceptance -->
## Question 8: Ingestion Script Behavior (Re-runs)

The ingestion pipeline clones the GitHub repo and processes `.md` files. If the script is run multiple times, how should it handle already-ingested documents?

A) Truncate and re-ingest everything (simple; safe but slow on re-runs)
B) Upsert by `source_file` + `article` — replace existing chunks for the same article (idempotent re-runs)
C) Skip files already present — only ingest new files (fast re-runs; no updates to changed content)
D) Add a `--reset` flag — default is skip, `--reset` triggers full re-ingest
X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

<!-- axis: Risks -->
## Question 9: LLM Cost and Quotas

If using a cloud LLM provider (OpenAI, Claude, Gemini), there are per-request costs and rate limits. How should the MVP handle LLM API errors (rate limits, quota exceeded, timeout)?

A) Return a clear Spanish error message to the user: "El servicio de análisis no está disponible temporalmente."
B) Retry up to 3 times with exponential backoff before returning an error
C) Return a partial result (summary only, no implications) if the full LLM call fails
D) No special handling — let the HTTP 500 surface to the frontend (MVP simplicity)
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

<!-- axis: Unknowns -->
## Question 10: SSH Tunnel Configuration for Local Development

`sshtunnel` is specified for local development to connect to the database. What is the SSH tunnel topology?

A) Tunnel to a remote PostgreSQL server (e.g. on a dev VM or cloud instance) — the DB does not run locally
B) Tunnel to expose a Docker-internal PostgreSQL outside the container network for tools like pgAdmin
C) The `sshtunnel` is a future-proofing measure — for MVP the DB runs fully locally via Docker Compose without a tunnel
D) Tunnel to a specific bastion host + private DB (provide details after [Answer]:)
X) Other (please describe after [Answer]: tag below)

[Answer]: A, the database runs on a remote server (VPS), and the local development environment connects to it via an SSH tunnel. The `sshtunnel` library will be used to establish this connection, allowing the backend service running locally to interact with the remote PostgreSQL database securely. For production, the backend will connect to the same database directly without a tunnel, as it will be deployed on the same VPS.

---

*Answer by filling in the letter (A/B/C/D/X) after each `[Answer]:` tag. For X, add your description on the same or next line. You can also combine letters (e.g., "A + D") if multiple options apply.*
