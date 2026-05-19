"""
Thermia backend — FastAPI application entry point.
"""
import asyncio
import io
import logging
import os

import pdfplumber
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import app.config  # noqa: F401 — side-effect: load_dotenv()
from app.db.connection import get_engine
from app.retrieval.context_builder import build_context
from app.retrieval.embedder import get_query_embedding
from app.retrieval.fusion import rrf_fusion
from app.retrieval.llm import analyze_with_llm
from app.retrieval.searcher import bm25_search, vector_search

log = logging.getLogger(__name__)

_limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Thermia API", version="0.1.0")
app.state.limiter = _limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:4200").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

_LEGAL_KEYWORDS = {
    "artículo", "ley", "decreto", "código", "título",
    "capítulo", "disposición", "reglamento",
}
_PDF_MAGIC = b"%PDF-"
_MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
# Rate limit for /analyze — override via ANALYZE_RATE_LIMIT env var
_ANALYZE_RATE_LIMIT = os.environ.get("ANALYZE_RATE_LIMIT", "10/minute")


def _is_legal_text(text: str) -> bool:
    return any(kw in text.lower() for kw in _LEGAL_KEYWORDS)


def _check_auth(authorization: str | None) -> None:
    """Raise HTTP 401 when the bearer token is missing or incorrect.

    Auth is skipped entirely when THERMIA_ENV=local so that local development
    with `ng serve` works without nginx in the loop.
    """
    if os.environ.get("THERMIA_ENV") == "local":
        return
    api_key = os.environ.get("API_KEY", "")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    if authorization[len("Bearer "):] != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze")
@_limiter.limit(_ANALYZE_RATE_LIMIT)
async def analyze(
    request: Request,
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Analyze a Spanish legal PDF and return structured legal insights.

    Authentication
    --------------
    Requires ``Authorization: Bearer <API_KEY>`` header (added by nginx in
    Docker deployments; skipped when THERMIA_ENV=local).

    Request body (multipart/form-data)
    -----------------------------------
    file : PDF document (``application/pdf``)

    Responses
    ---------
    200 : Structured analysis JSON
    401 : Missing or invalid bearer token
    413 : PDF exceeds 10 MB
    422 : Non-PDF file or non-legal / empty document
    429 : Rate limit exceeded
    """
    _check_auth(authorization)

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=422, detail="El archivo debe ser un PDF válido.")

    pdf_bytes = await file.read()

    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="El archivo PDF no puede superar los 10 MB.")

    # Validate PDF magic bytes — content-type header is trivially spoofable
    if not pdf_bytes.startswith(_PDF_MAGIC):
        raise HTTPException(status_code=422, detail="El archivo debe ser un PDF válido.")

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages_text = [p.extract_text() or "" for p in pdf.pages]
    full_text = "\n".join(pages_text).strip()

    if not full_text or not _is_legal_text(full_text):
        raise HTTPException(
            status_code=422,
            detail="El documento no contiene contenido legal reconocible.",
        )

    _QUERY_CHAR_LIMIT = 2000
    if len(full_text) > _QUERY_CHAR_LIMIT:
        log.warning("PDF text truncated from %d to %d chars for embedding.", len(full_text), _QUERY_CHAR_LIMIT)
    query_text = full_text[:_QUERY_CHAR_LIMIT]
    engine = get_engine()
    loop = asyncio.get_event_loop()

    try:
        embedding = get_query_embedding(query_text)
        vector_results, bm25_results = await asyncio.gather(
            loop.run_in_executor(None, vector_search, engine, embedding, 10),
            loop.run_in_executor(None, bm25_search, engine, query_text, 10),
        )
        top_docs = rrf_fusion(vector_results, bm25_results, top_n=5)
        context = build_context(top_docs)
        result = await loop.run_in_executor(None, analyze_with_llm, context, query_text)
    finally:
        tunnel = getattr(engine, "tunnel", None)
        if tunnel is not None:
            tunnel.stop()

    return JSONResponse(content=result)
