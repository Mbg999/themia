"""
Thermia backend — FastAPI application entry point.
"""
import asyncio
import hmac
import io
import logging
import os
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    app.state.engine = engine
    yield
    tunnel = getattr(engine, "tunnel", None)
    if tunnel is not None:
        tunnel.stop()


app = FastAPI(title="Thermia API", version="0.1.0", lifespan=lifespan)
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

# Read API_KEY once at module load time (startup) — never per-request.
# A missing or too-short key is a hard failure: it means the service was
# misconfigured, not that a particular request is bad.
_API_KEY = os.environ.get("API_KEY", "")
if len(_API_KEY) < 16:
    raise RuntimeError(
        "API_KEY must be at least 16 characters. "
        "Set it in your .env file (see .env.example). "
        "Auth is always enforced — do not leave API_KEY empty or too short."
    )


def _is_legal_text(text: str) -> bool:
    return any(kw in text.lower() for kw in _LEGAL_KEYWORDS)


def _check_auth(authorization: str | None) -> None:
    """Raise HTTP 401 when the bearer token is missing or incorrect.

    Uses constant-time comparison (hmac.compare_digest) to prevent timing
    attacks.  Auth is always enforced regardless of THERMIA_ENV.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    token = authorization[len("Bearer "):]
    if not hmac.compare_digest(token, _API_KEY):
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
    engine = request.app.state.engine

    embedding = get_query_embedding(query_text)
    vector_results, bm25_results = await asyncio.gather(
        asyncio.to_thread(vector_search, engine, embedding, 10),
        asyncio.to_thread(bm25_search, engine, query_text, 10),
    )
    top_docs = rrf_fusion(vector_results, bm25_results, top_n=5)
    context = build_context(top_docs)
    result = await asyncio.to_thread(analyze_with_llm, context, query_text)
    result["fuentes"] = [
        {
            "law_id": doc.metadata_.get("law_id", ""),
            "law_title": doc.metadata_.get("law_title", ""),
            "article": doc.metadata_.get("article", ""),
            "section": doc.metadata_.get("section", ""),
            "hierarchy_path": doc.metadata_.get("hierarchy_path", ""),
            "legal_rank": doc.legal_rank or "",
            "status": doc.status or "",
            "jurisdiction": doc.jurisdiction or "",
            "eli": doc.metadata_.get("eli") or "",
        }
        for doc in top_docs
    ]

    return JSONResponse(content=result)
