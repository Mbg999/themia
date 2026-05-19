# Unit Spec: `retrieval-api`
**Run ID:** 2026-05-19t09-35-00z-thermia-mvp
**Layer:** 1 | **Dependencies:** `db-layer`

---

## Purpose
The core FastAPI application that accepts a PDF upload, extracts its text, runs hybrid vector+BM25 search with RRF fusion against the `documents` table, builds a structured context string, calls the Groq LLM via LangChain, and returns a structured Spanish-language legal analysis.

## Responsibilities
- FastAPI app skeleton with health endpoint and CORS
- API key authentication middleware (`Authorization: Bearer <THERMIA_API_KEY>`)
- `POST /analyze`: multipart PDF upload → pdfplumber extraction → legal guard → intent detection → search → RRF → context → LLM → response
- Legal content guard (keyword heuristic; HTTP 422 for empty or non-legal PDFs)
- Intent detection (simple heuristic: detect law name patterns)
- Vector search (pgvector cosine, top-20 with metadata filters, query embedding via Cohere `input_type="search_query"`)
- BM25 search (tsvector `ts_rank_cd`, top-20, same metadata filters)
- RRF fusion (`score = Σ 1/(60 + rank_i)`) + deduplication by `(source_file, article)`
- Context builder (exact format: `[{law_title} | Artículo {article} | {section}]\n\n{content}\n\n---`)
- LangChain chain: Groq `llama-3.1-8b-instant`, structured output (Pydantic `AnalysisResult`)
- Error responses: HTTP 401 (auth), HTTP 422 (guard), HTTP 503 (LLM failure) — all with Spanish messages
- Startup validation: assert `vector_dims(embedding) = 1024` in `documents` table

## Public Interfaces
| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | none | Health check `{"status": "ok"}` |
| `/analyze` | POST | Bearer | Multipart PDF upload → structured analysis JSON |

**`POST /analyze` response schema:**
```json
{
  "analysis": {
    "resumen": "string",
    "implicaciones_legales": ["string"],
    "fundamento_juridico": ["string"]
  },
  "metadata": {
    "chunks_used": 5,
    "processing_time_ms": 1200
  }
}
```

## Internal Dependencies
| Unit | What it consumes |
|---|---|
| `db-layer` | `get_engine()` + `Document` model |

## External Dependencies
| Package | Version (pinned) | Purpose |
|---|---|---|
| `fastapi` | latest stable | Web framework |
| `uvicorn` | latest stable | ASGI server |
| `python-multipart` | latest stable | Multipart form parsing |
| `pdfplumber` | latest stable | PDF text extraction |
| `cohere` | latest stable | Query embedding (`search_query` input type) |
| `langchain` | latest stable | LLM chain orchestration |
| `langchain-groq` | latest stable | Groq provider for LangChain |
| `pydantic` | `>=2.0` | Structured output schema + request validation |

## Tasks
| Task | Description |
|---|---|
| API-T1 | FastAPI app skeleton (main.py, router, CORS, GET /health) |
| API-T2 | API key auth middleware (Bearer token; HTTP 401 on failure) |
| API-T3 | POST /analyze: multipart PDF upload + pdfplumber extraction |
| API-T4 | Legal content guard (keyword heuristic; HTTP 422) |
| API-T5 | Intent detection (law name pattern matching; metadata filter prep) |
| API-T6 | Vector search (pgvector cosine, top-20, metadata filters, Cohere `search_query` embedding) |
| API-T7 | BM25 search (tsvector ts_rank_cd, top-20, same filters; assert ts_rank_cd > 0 for known legal phrase) |
| API-T8 | RRF fusion + deduplication by `(source_file, article)` |
| API-T9 | Context builder (exact `[law | article | section]\n\ncontent\n\n---` format) |
| API-T10 | LangChain Groq chain (llama-3.1-8b-instant, Pydantic AnalysisResult, Spanish prompt) |
| API-T11 | HTTP 503 error handler for LLM failures (rate limit / timeout / quota) |
| API-T12 | Unit tests: auth (3 cases), guard (3 cases), RRF deduplication, context format |

## Acceptance Criteria (rolled up)
- [ ] `GET /health` returns `{"status": "ok"}`
- [ ] Request without `Authorization` header returns HTTP 401 with Spanish JSON
- [ ] Request with wrong key returns HTTP 401
- [ ] Request with empty PDF text returns HTTP 422 with guard message
- [ ] Request with non-legal content returns HTTP 422 with out-of-scope message
- [ ] Valid Spanish legal PDF returns HTTP 200 with all 3 analysis sections non-empty and in Spanish
- [ ] RRF result list has no duplicate `(source_file, article)` pairs
- [ ] RRF scores computed from rank positions (not raw similarity scores)
- [ ] Context string matches exact format for each chunk
- [ ] `AnalysisResult` Pydantic model has `resumen: str`, `implicaciones_legales: list[str]`, `fundamento_juridico: list[str]`
- [ ] LLM error returns HTTP 503 with Spanish message (no traceback)
- [ ] Startup validates `vector_dims(embedding) = 1024`
- [ ] `pytest tests/test_api.py` passes (auth 3 cases, guard 3 cases, RRF, context format)

## Definition of Done
- All tasks complete with green tests
- Manual integration test: upload a real Spanish legal PDF, receive valid response
- No `GROQ_API_KEY` or `COHERE_API_KEY` hardcoded
- All error responses return JSON (not HTML or plain text)
