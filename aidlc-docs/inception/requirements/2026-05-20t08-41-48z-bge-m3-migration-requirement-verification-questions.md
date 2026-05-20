# Requirement Verification Questions
**Run ID:** 2026-05-20t08-41-48z-bge-m3-migration
**Project:** Thermia — Cohere → bge-m3 Embedding Migration
**Pass:** 1 (clarifying questions — await answers before generating requirements.md)

---

<!-- axis: Purpose -->
## Question 1: Primary Success Metric

The stated driver for this migration is "Cohere API costs are too high." What is the primary success metric?

A) Cost reduction — eliminate Cohere per-embedding fees entirely
B) Simplified operations — remove KeyPool, API key rotation, rate-limit handling
C) Both equally important — cost reduction AND ops simplification
D) Embedding quality — bge-m3 must match or exceed Cohere retrieval quality
X) Other (please describe after [Answer]: tag below)

[Answer]: C

---

<!-- axis: Needs -->
## Question 2: Ollama Error Handling

The current Cohere embedder has retry logic (3 delays: 10s, 30s, 60s) followed by API key rotation for 429 rate limits. For the self-hosted Ollama endpoint, what error handling strategy should be used?

A) No retries — fail fast and let the calling code handle errors
B) Simple retry — 2 retries with fixed 5s delay, then raise
C) Exponential backoff — 3 retries (1s, 4s, 9s), then raise
D) Circuit breaker — fail fast after N consecutive failures within a time window
X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

<!-- axis: Needs -->
## Question 3: HTTP Client and Connection Configuration

What HTTP client library and timeout configuration should be used for the Ollama API calls?

A) `httpx` with default timeout (5s) — already a dev dependency, async-capable
B) `httpx` with configurable timeout via environment variable (e.g. `OLLAMA_TIMEOUT`)
C) `requests` with 30s timeout — simplest, synchronous (consistent with current asyncio.to_thread pattern)
D) `urllib.request` — no additional dependency, minimal approach
X) Other (please describe after [Answer]: tag below)

[Answer]: X can we use the ollama client? https://github.com/ollama/ollama-python

---

<!-- axis: Needs -->
## Question 4: KeyPool Simplification Scope

The KeyPool module manages API key rotation for both Cohere and Groq. For this migration:

A) Remove Cohere-related code from KeyPool entirely; keep Groq key management unchanged
B) Remove the entire KeyPool module; migrate Groq to inline env-var reading (breaking KeyPool's shared pattern)
C) Keep KeyPool structure but strip Cohere-specific logic; leave Groq pool as-is (least invasive)
D) Do NOT remove KeyPool for Cohere yet — keep the pool structure but simplify to a single "key" for now
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

<!-- axis: Needs -->
## Question 5: Ingestion Batching and Rate Control

The current Cohere ingestion pipeline batches 50 texts per API call with 1s inter-batch sleep. Ollama's `/api/embeddings` endpoint processes one prompt at a time. How should ingestion embedding be structured?

A) One request per chunk — no batching, no rate limiting (simple; Ollama is self-hosted)
B) Sequential with throttling — one request at a time but with configurable delay between calls
C) Concurrent with worker pool — use an `httpx` connection pool to send N concurrent requests (e.g. 4–8 workers)
D) Keep batching approach — only if the RE doc assumption that batching is unsupported is verified; allow fallback to single if unsupported
X) Other (please describe after [Answer]: tag below)

[Answer]: X: check if we can batch https://docs.ollama.com/capabilities/embeddings, otherwhise, B
example: import ollama

batch = ollama.embed(
  model='embeddinggemma',
  input=[
    'The quick brown fox jumps over the lazy dog.',
    'The five boxing wizards jump quickly.',
    'Jackdaws love my big sphinx of quartz.',
  ]
)
print(len(batch['embeddings']))  # number of vectors


---

<!-- axis: Expectations -->
## Question 6: Latency and Performance Expectations

The self-hosted Ollama endpoint at `https://ollama.cvbooster.es/api/embeddings` may have different latency than Cohere's API. What performance expectations apply?

A) Embedding latency is not critical — same user experience as before is acceptable
B) Query-time embedding must be <500ms per call to maintain current response times
C) Up to 2x Cohere latency is acceptable for cost savings (the bottleneck is the LLM call anyway)
D) Ingestion throughput is the priority — batch re-embedding must complete within a reasonable time
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

<!-- axis: Limits -->
## Question 7: Explicit Migration Scope Boundaries

What is explicitly out of scope for this migration?

A) Changing the vector dimension (must stay 1024d — compatible with bge-m3)
B) Changing the database schema or pgvector index
C) Modifying the searcher, fusion, context_builder, or LLM modules
D) Introducing a new embedding abstraction layer / interface
E) Re-ingesting all documents (existing embeddings remain valid assuming same dimension)
F) All of the above — strictly a provider swap, no other changes
X) Other (please describe after [Answer]: tag below)

[Answer]: F

---

<!-- axis: Acceptance -->
## Question 8: Verification and Rollback

How should we verify the migration was successful, and what is the rollback strategy?

A) All unit tests pass with new mocks; manual endpoint test confirms same-quality results; rollback = revert commit + keep old Cohere key
B) Run ingestion pipeline end-to-end with bge-m3; compare query results with Cohere-generated results side-by-side for a sample of queries
C) Staged rollout — deploy bge-m3 to staging first, validate, then production; keep Cohere keys active during transition
D) No rollback needed — keep Cohere code as dead code for one release cycle, then clean up
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

*Answer by filling in the letter (A/B/C/D/X) after each `[Answer]:` tag. For X, add your description on the same or next line. You can also combine letters (e.g., "A + D") if multiple options apply.*
