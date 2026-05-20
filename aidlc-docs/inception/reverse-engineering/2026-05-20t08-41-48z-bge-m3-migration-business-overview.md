# Business Overview — Thermia

## Domain

Thermia is a **legal-tech RAG (Retrieval-Augmented Generation) platform** focused on Spanish law. It enables users to upload PDF documents containing Spanish legal text and receive structured analysis: summaries, legal implications, and juridical foundations — all grounded in a curated corpus of Spanish legislation.

## Core Capabilities

1. **PDF Analysis** (`POST /analyze`)
   - Accepts a Spanish legal PDF document
   - Extracts text via OCR-free PDF parsing (pdfplumber)
   - Detects legal content via keyword matching (law, decree, article, etc.)
   - Retrieves relevant legislation from a vector + full-text search database
   - Generates a structured analysis via Groq LLM (llama-3.1-8b-instant)

2. **Legal Corpus Ingestion** (`scripts/ingest.py`)
   - Clones the [legalize-es](https://github.com/legalize-dev/legalize-es) repository of Spanish legal markdown documents
   - Parses hierarchical legal structure (H1=law, H2=section, H3+=article)
   - Chunks articles with token-aware splitting (800-token threshold, 512-token sub-chunks, 50-token overlap)
   - Generates embeddings via Cohere embed-multilingual-v3.0 (1024 dimensions)
   - Upserts idempotently into PostgreSQL/pgvector via deterministic UUID5 keys

3. **Hybrid Search**
   - Vector similarity search (pgvector cosine) — semantic understanding
   - BM25 full-text search (PostgreSQL tsvector) — keyword matching
   - Reciprocal Rank Fusion (RRF) to merge and rank results

## User Types

| User Type | Role | Interaction |
|-----------|------|-------------|
| **Legal Professional** | End user | Uploads PDFs via API, receives structured legal analysis |
| **System Administrator** | Operator | Runs ingestion pipeline, manages API keys, monitors rate limits |
| **Developer** | Maintainer | Deploys backend, manages Cohere/Groq keys, configures environment |

## Business Goals

- **Reduce cost**: Migrate from paid Cohere API (embed-multilingual-v3.0) to self-hosted bge-m3 via Ollama, eliminating per-request API costs
- **Maintain quality**: Preserve 1024-dimensional embedding vectors compatible with the existing pgvector index
- **Simplify operations**: Remove API key rotation complexity (KeyPool) when using a self-hosted model
- **Spanish legal focus**: Provide accurate, citation-grounded analysis of Spanish legal documents
- **Idempotent ingestion**: Allow re-running the ingestion pipeline without creating duplicate records

## Current Pain Points (Context for Migration)

- Cohere API costs scale with ingestion volume and query volume
- KeyPool complexity adds operational overhead (key rotation, cool-down windows)
- Rate limits (100 calls/min on trial keys, 429 errors) require retry logic throughout the pipeline
- Two different `input_type` parameters (`search_query` in embedder.py vs `search_document` in ingest.py) create subtle inconsistency risk

## Migration Target

- **Model**: bge-m3 (BAAI General Embedding) via Ollama
- **Endpoint**: `https://ollama.cvbooster.es/api/embeddings`
- **Dimension**: 1024 (compatible with existing pgvector `Vector(1024)` schema)
- **Key benefit**: Zero per-embedding cost, no rate limits, no API key management
