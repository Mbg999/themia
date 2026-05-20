Build an MVP called Thermia.

It is an application to:
- analyze Spanish legal documents.
- extract legal implications.
- generate explanations understandable for non-expert users.
- all texts and outputs will be only in Spanish.

The system must be a hybrid RAG with PostgreSQL + pgvector.

STACK REQUIRED
Backend
* FastAPI
* LangChain
* SQLAlchemy
* PostgreSQL
* pgvector extension
* sshtunnel <- only for local development, to connect to the database
* Pytest for unit tests

Frontend
* Angular (single view)
* Custom SCSS (use DESIGN.md)
* Unit tests with vitest.

Stack details
- monorepo GREENFIELD:
  - you already have thermia-front created with Angular 21.2.0 (latest) generated with ng new thermia-front.
  - for backend create thermia-back with FastAPI, you must create it from scratch, since there is no template for this use case.
- Latest compatible versions possible.
- use environment variables.
- well documented code in English.
- ask me about any Stack detail, dependencies, etc, make me part of the process.
- git is initialized at the root of the monorepo (/.git/).


GENERAL ARCHITECTURE
The system has 2 pipelines:

1.- INGESTION PIPELINE
- implement script executable manually.

- schema:
[
GITHUB CLONE
https://github.com/legalize-dev/legalize-es
↓
SCAN .md FILES
↓
PARSE LEGAL STRUCTURE
(law → title → article)
↓
CHUNKING BY ARTICLES
↓
SUB-CHUNKING if > X tokens (overlap 50)
↓
GENERATE EMBEDDINGS
↓
GENERATE ENRICHED METADATA
↓
STORE IN POSTGRESQL (pgvector + tsvector)
]

- CHUNKING RULES
* 1 chunk = 1 legal article
* sub-chunks only if the article is long
* always preserve legal hierarchy
Example:

Law
 ├── Title I
 │   ├── Article 1 → chunk
 │   ├── Article 2 → chunk

- METADATA
Each chunk must include:

{
  "law_id": "",
  "law_title": "",
  "article": "",
  "section": "",
  "chunk_type": "article",
  "source_file": "",
  "jurisdiction": "ES",
  "year": 0,
  "hierarchy_path": ""
}

- TEXT FORMAT FOR EMBEDDINGS
Always:
[LAW X - ARTICLE Y - TITLE Z]

article text...

- DATABASE
Use SQLAlchemy + migrations.
Table:
* documents
    * id
    * content
    * embedding (vector)
    * tsvector
    * metadata (jsonb)

2.- RETRIEVAL PIPELINE
- Implement FastAPI endpoint: POST /analyze, this must accept and validate that a .pdf document is provided

- flow schema:
[
QUERY
↓
Intent detection (simple MVP heuristic)
↓
Metadata filtering (jurisdiction, type)
↓
VECTOR SEARCH (pgvector)
↓
BM25 SEARCH (tsvector)
↓
RRF FUSION (reciprocal rank fusion)
↓
TOP CHUNKS
↓
CONTEXT BUILDER (with formatted metadata)
↓
LLM reasoning (LangChain)
↓
RESPONSE
]

- RETRIEVAL RULES
* always apply metadata filters if they exist
* merge results with RRF (no direct score summation)
* remove duplicates by article_id

- CONTEXT BUILDER
Mandatory format:

[LAW | ARTICLE | SECTION]

content

---

- REQUIRED LLM OUTPUT
Must return:
1. Simple summary
2. Legal implications
3. Legal basis (exact citations)

- create a guard, if the pdf file text is empty or not related to legal content, the system must return a message stating that it cannot process the request because it is outside its scope.

- FRONTEND (ANGULAR)
Single view:
* PDF upload input
* “analyze” button
* render structured result

- DESIGN SYSTEM
Read DESIGN.md and apply it mandatorily.

- RESTRICTIONS
* No overengineering, keep it simple
* No microservices
* MVP first
* Everything must run locally with Docker
* Avoid unnecessary abstractions
