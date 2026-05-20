# API Documentation — Thermia

## Base URL
`http://localhost:8000` (local development)

## Endpoints

### `GET /health`
Health check endpoint.

**Response** `200 OK`
```json
{
  "status": "ok"
}
```

---

### `POST /analyze`
Analyze a Spanish legal PDF and return structured legal insights.

**Authentication**: `Authorization: Bearer <API_KEY>` header (required)

**Rate Limit**: 10 requests per minute (configurable via `ANALYZE_RATE_LIMIT` env var)

**Request** (multipart/form-data):
| Field | Type | Description |
|-------|------|-------------|
| `file` | File (application/pdf) | PDF document to analyze. Max 10 MB. |

**Response** `200 OK`:
```json
{
  "resumen": "Breve resumen del contenido legal relevante",
  "implicaciones_legales": [
    "Implicación legal 1",
    "Implicación legal 2"
  ],
  "fundamento_juridico": [
    "LEY X - Artículo Y: Descripción del fundamento"
  ],
  "fuentes": [
    {
      "law_id": "BOE-A-2023-001",
      "law_title": "Ley de Ejemplo",
      "article": "Artículo 1",
      "section": "Título I",
      "hierarchy_path": "BOE-A-2023-001 > Título I > Artículo 1",
      "legal_rank": "ley",
      "status": "vigente",
      "jurisdiction": "ES",
      "eli": "eli/es/l/2023/001"
    }
  ]
}
```

**Error Responses**:
| Status | Description |
|--------|-------------|
| 401 | Missing or invalid Authorization header |
| 413 | PDF exceeds 10 MB |
| 422 | Non-PDF file, empty document, or non-legal content |
| 429 | Rate limit exceeded |

---

## Internal APIs (Not HTTP — Used by retrieval pipeline)

### `app.retrieval.embedder.get_query_embedding(text: str) -> list[float]`
Generates a 1024-dimensional embedding vector for a query string.

**Current behavior**: Calls Cohere `embed-multilingual-v3.0` with `input_type="search_query"`.
**Target behavior**: Calls Ollama bge-m3 via HTTP POST to `https://ollama.cvbooster.es/api/embeddings`.

### `app.retrieval.embedder.get_cohere_pool() -> KeyPool`
Returns/initializes the module-level KeyPool singleton for Cohere API keys.

### `app.retrieval.searcher.vector_search(engine, embedding, top_k, only_active) -> list[Document]`
Performs pgvector cosine similarity search with `Vector(1024)`.

### `app.retrieval.searcher.bm25_search(engine, query_text, top_k, only_active) -> list[Document]`
Performs PostgreSQL full-text search with Spanish language configuration.

### `app.retrieval.fusion.rrf_fusion(vector_results, bm25_results, top_n) -> list`
Combines vector and BM25 results using Reciprocal Rank Fusion with `k=60`.

### `app.retrieval.context_builder.build_context(chunks) -> str`
Formats Document objects into a structured prompt string.

### `app.retrieval.llm.analyze_with_llm(context, query) -> dict`
Calls Groq llama-3.1-8b-instant via LangChain for legal analysis.
Returns structured JSON with `resumen`, `implicaciones_legales`, `fundamento_juridico`.

---

## Ingestion Script (`scripts/ingest.py`) — CLI

**Usage**: `python scripts/ingest.py [--reset]`

**Arguments**:
| Argument | Description |
|----------|-------------|
| `--reset` | Truncate the documents table before ingesting |

**Environment Variables**:
| Variable | Purpose |
|----------|---------|
| `COHERE_API_KEYS` | JSON array of Cohere API keys |
| `DATABASE_URL` | PostgreSQL connection URL |
| `THERMIA_ENV` | "local" or "production" |

## Embedding API Contract (For Migration)

The following internal API signatures are stable and must be preserved after migration:

```python
# embedder.py — public interface
def get_query_embedding(text: str) -> list[float]: ...

# ingest.py — public interface (used by tests)
def generate_embeddings(client, texts: list[str], *, pool=None) -> list[list[float]]: ...
```

Both functions must continue to produce 1024-dimensional float vectors.
