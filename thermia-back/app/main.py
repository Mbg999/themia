"""
Thermia backend — FastAPI application entry point.
"""
import io
import os

import pdfplumber
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Load configuration (triggers python-dotenv .env loading)
from app.config import THERMIA_ENV  # noqa: F401

app = FastAPI(title="Thermia API", version="0.1.0")

_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:4200").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Spanish legal keywords used for content heuristic
_LEGAL_KEYWORDS = {
    "artículo", "ley", "decreto", "código", "título",
    "capítulo", "disposición", "reglamento",
}


def _is_legal_text(text: str) -> bool:
    """Return True if *text* contains at least one Spanish legal keyword."""
    lowered = text.lower()
    return any(kw in lowered for kw in _LEGAL_KEYWORDS)


def _check_auth(authorization: str | None) -> None:
    """Raise HTTP 401 when the bearer token is missing or incorrect."""
    api_key = os.environ.get("API_KEY", "")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@app.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Analyze a Spanish legal PDF and return structured legal insights.

    Authentication
    --------------
    Requires ``Authorization: Bearer <API_KEY>`` header.

    Request body (multipart/form-data)
    -----------------------------------
    file : PDF document (``application/pdf``)

    Responses
    ---------
    200 : Structured analysis JSON
    401 : Missing or invalid bearer token
    422 : Non-PDF file or non-legal / empty document
    """
    # --- Auth ---
    _check_auth(authorization)

    # --- File type guard ---
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=422,
            detail="El archivo debe ser un PDF válido.",
        )

    # --- File size guard (before reading into memory) ---
    _MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
    pdf_bytes = await file.read()
    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail="El archivo PDF no puede superar los 10 MB.",
        )

    # --- Extract text ---
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages_text = [p.extract_text() or "" for p in pdf.pages]
    full_text = "\n".join(pages_text).strip()

    # --- Legal-content guard ---
    if not full_text or not _is_legal_text(full_text):
        raise HTTPException(
            status_code=422,
            detail="El documento no contiene contenido legal reconocible.",
        )

    # --- Lazy imports of retrieval modules (keeps startup fast) ---
    from app.retrieval.embedder import get_query_embedding
    from app.retrieval.searcher import bm25_search, vector_search
    from app.retrieval.fusion import rrf_fusion
    from app.retrieval.context_builder import build_context
    from app.retrieval.llm import analyze_with_llm
    from app.db.connection import get_engine

    # Use first 2000 chars as the query (avoids oversized embedding input)
    query_text = full_text[:2000]

    engine = get_engine()
    try:
        embedding = get_query_embedding(query_text)
        vector_results = vector_search(engine, embedding, top_k=10)
        bm25_results = bm25_search(engine, query_text, top_k=10)
        top_docs = rrf_fusion(vector_results, bm25_results, top_n=5)
        context = build_context(top_docs)
        result = analyze_with_llm(context, query_text)
    finally:
        # Stop SSH tunnel if one was created (local env)
        tunnel = getattr(engine, "tunnel", None)
        if tunnel is not None:
            tunnel.stop()

    return JSONResponse(content=result)
