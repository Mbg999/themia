# Interaction Diagrams — Thermia

## Flow 1: Query-Time Embedding (POST /analyze → get_query_embedding)

**Current (Cohere)** — This flow is the primary migration target.

```mermaid
sequenceDiagram
    participant Client as HTTP Client
    participant FastAPI as FastAPI (main.py)
    participant Embedder as embedder.py
    participant KeyPool as key_pool.py
    participant Cohere as Cohere API

    Client->>FastAPI: POST /analyze (PDF + Bearer token)
    FastAPI->>FastAPI: _check_auth(), validate PDF, extract text
    FastAPI->>Embedder: get_query_embedding(query_text)
    
    Note over Embedder: Loop: 3 in-key retries
    
    Embedder->>KeyPool: get_cohere_pool().current()
    KeyPool-->>Embedder: active_api_key
    Embedder->>Embedder: _get_client() → cohere.Client(active_key)
    
    loop Retry up to 3 times (10s, 30s, 60s)
        Embedder->>Cohere: client.embed(texts=[text], model="embed-multilingual-v3.0", input_type="search_query")
        alt Success
            Cohere-->>Embedder: embeddings (1024-d vector)
            Embedder-->>FastAPI: list[float] (1024)
        else 429 Rate Limit
            Cohere-->>Embedder: 429 error
            Embedder->>Embedder: classify_failure() → RATE_LIMIT_429
            Note over Embedder: sleep(delay) and retry
        else 400/401/403
            Cohere-->>Embedder: error
            Embedder->>Embedder: classify_failure() → None → re-raise
        end
    end
    
    Note over Embedder: After budget exhausted:
    Embedder->>KeyPool: mark_failed(reason)
    KeyPool->>KeyPool: rotate to next key, set cool-down
    KeyPool-->>Embedder: new active_key (or AllKeysExhaustedError)
    
    Embedder->>Embedder: _get_client() → rebuilt with new key
    Embedder->>Cohere: client.embed(texts=[text], ...) — ONE final attempt
    Cohere-->>Embedder: embeddings
    
    FastAPI->>FastAPI: vector_search() + bm25_search() + rrf_fusion()
    FastAPI->>FastAPI: build_context() + analyze_with_llm()
    FastAPI-->>Client: JSON response (200 OK)
```

**Target (Ollama bge-m3)**:
```mermaid
sequenceDiagram
    participant Client as HTTP Client
    participant FastAPI as FastAPI (main.py)
    participant Embedder as embedder.py
    participant Ollama as Ollama bge-m3

    Client->>FastAPI: POST /analyze (PDF + Bearer token)
    FastAPI->>FastAPI: _check_auth(), validate PDF, extract text
    FastAPI->>Embedder: get_query_embedding(query_text)
    
    Note over Embedder: No retry, no key rotation
    
    Embedder->>Ollama: POST /api/embeddings {model: "bge-m3", prompt: text}
    Ollama-->>Embedder: {embedding: [0.1, 0.2, ...]} (1024-d)
    Embedder-->>FastAPI: list[float] (1024)
    
    FastAPI->>FastAPI: vector_search() + bm25_search() + rrf_fusion()
    FastAPI->>FastAPI: build_context() + analyze_with_llm()
    FastAPI-->>Client: JSON response (200 OK)
```

---

## Flow 2: Ingestion Pipeline Embedding

**Current (Cohere)** — This flow is also a migration target.

```mermaid
sequenceDiagram
    participant CLI as scripts/ingest.py
    participant GitRepo as legalize-es (GitHub)
    participant Cohere as Cohere API
    participant KeyPool as key_pool.py
    participant DB as PostgreSQL/pgvector

    CLI->>GitRepo: clone/pull repo (pinned commit)
    GitRepo-->>CLI: .md files
    
    loop Each .md file
        CLI->>CLI: parse_legal_structure() → chunks with metadata
        CLI->>CLI: build_embedding_text() → prefixed strings
        
        Note over CLI: Batch size: 50, inter-batch sleep: 1s
        
        loop Each batch
            CLI->>Cohere: generate_embeddings() with pool
            
            Note over CLI: In-key retries (3 delays)
            
            CLI->>Cohere: client.embed(texts=batch, model="embed-multilingual-v3.0", input_type="search_document")
            
            alt Success
                Cohere-->>CLI: embeddings (list of 1024-d vectors)
            else 429
                Note over CLI: classify_failure() → pool.mark_failed() → rotate
                CLI->>Cohere: rebuild client with new key, retry batch
            end
            
            CLI->>CLI: time.sleep(_EMBED_INTER_BATCH_SLEEP)
        end
        
        CLI->>DB: upsert_documents() → session.merge() with deterministic UUID
    end
    
    CLI-->>CLI: Log summary (total chunks, failed files)
```

**Target (Ollama bge-m3)**:
```mermaid
sequenceDiagram
    participant CLI as scripts/ingest.py
    participant GitRepo as legalize-es (GitHub)
    participant Ollama as Ollama bge-m3
    participant DB as PostgreSQL/pgvector

    CLI->>GitRepo: clone/pull repo (pinned commit)
    GitRepo-->>CLI: .md files
    
    loop Each .md file
        CLI->>CLI: parse_legal_structure() → chunks with metadata
        CLI->>CLI: build_embedding_text() → prefixed strings
        
        Note over CLI: No batch size limit, no inter-batch sleep
        
        loop Each text
            CLI->>Ollama: POST /api/embeddings {model: "bge-m3", prompt: text}
            Ollama-->>CLI: {embedding: [...]}} (1024-d)
        end
        
        CLI->>DB: upsert_documents() → session.merge() with deterministic UUID
    end
    
    CLI-->>CLI: Log summary (total chunks, failed files)
```

---

## Flow 3: Full RAG Analysis Pipeline

This flow shows the complete chain from PDF upload to structured legal analysis.

```mermaid
sequenceDiagram
    participant Client as HTTP Client
    participant API as FastAPI (main.py)
    participant Embed as embedder.py
    participant Vector as searcher.py (vector)
    participant BM25 as searcher.py (bm25)
    participant Fusion as fusion.py
    participant Ctx as context_builder.py
    participant LLM as llm.py (Groq)

    Client->>API: POST /analyze (PDF)
    API->>API: Validate auth, file type, size, legal content
    
    par Embedding
        API->>Embed: get_query_embedding(truncated_text)
        Embed-->>API: 1024-d embedding
    end
    
    API->>API: asyncio.gather()
    
    par Vector Search
        API->>Vector: vector_search(engine, embedding, top_k=10)
        Vector->>Vector: SET LOCAL ivfflat.probes = 10
        Vector->>Vector: SELECT ... ORDER BY embedding <=> cast(..., Vector(1024))
        Vector-->>API: 10 Document ORM objects
    and BM25 Search
        API->>BM25: bm25_search(engine, query_text, top_k=10)
        BM25->>BM25: plainto_tsquery('spanish', query_text)
        BM25-->>API: 10 Document ORM objects
    end
    
    API->>Fusion: rrf_fusion(vector_results, bm25_results, top_n=5)
    Fusion-->>API: 5 merged, deduplicated Documents
    
    API->>Ctx: build_context(top_docs)
    Ctx-->>API: Formatted context string
    
    API->>LLM: analyze_with_llm(context, query_text)
    Note over LLM: KeyPool rotation on GROQ_DAILY_QUOTA
    
    LLM->>LLM: _invoke_and_parse() → JSON
    
    alt Success
        LLM-->>API: {resumen, implicaciones, fundamento}
    else GROQ_DAILY_QUOTA
        LLM->>LLM: pool.mark_failed() → rotate key
        LLM->>LLM: retry once with new key
        LLM-->>API: {resumen, implicaciones, fundamento}
    end
    
    API->>API: Build "fuentes" array from top_docs
    API-->>Client: 200 JSON response
```
