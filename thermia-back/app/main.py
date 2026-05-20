"""
Thermia backend — FastAPI application entry point.
"""
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
from app.retrieval.analysis_pipeline import run_analysis
from app.retrieval.embedder import _validate_host as _validate_ollama_host

log = logging.getLogger(__name__)

_limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_ollama_host(os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    engine = get_engine()
    app.state.engine = engine
    yield
    tunnel = getattr(engine, "tunnel", None)
    if tunnel is not None:
        tunnel.stop()


app = FastAPI(title="Thermia API", version="0.3.0", lifespan=lifespan)
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
    422 : Non-PDF file  / empty document
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

    _QUERY_CHAR_LIMIT = 2000
    if len(full_text) > _QUERY_CHAR_LIMIT:
        log.warning("PDF text truncated from %d to %d chars for embedding.", len(full_text), _QUERY_CHAR_LIMIT)
    query_text = full_text[:_QUERY_CHAR_LIMIT]

    if not query_text:
        raise HTTPException(
            status_code=422,
            detail="El documento no contiene contenido legal reconocible.",
        )

    result = await run_analysis(request.app.state.engine, query_text)
    return JSONResponse(content=result)


@app.post("/analyze/text")
@_limiter.limit(_ANALYZE_RATE_LIMIT)
async def analyze_text(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Analyze a Spanish legal text and return structured legal insights.

    Authentication
    --------------
    Requires ``Authorization: Bearer <API_KEY>`` header (added by nginx in
    Docker deployments; skipped when THERMIA_ENV=local).

    Request body (application/json)
    --------------------------------
    text : Legal text to analyze (string)

    Responses
    ---------
    200 : Structured analysis JSON
    401 : Missing or invalid bearer token
    413 : Text exceeds limit
    422 : Empty or missing text
    429 : Rate limit exceeded
    """
    _check_auth(authorization)

    body = await request.json()
    if not body or "text" not in body:
        raise HTTPException(status_code=422, detail="El cuerpo de la solicitud debe contener un campo 'text'.")

    text = body["text"]

    _QUERY_CHAR_LIMIT = 2000
    if len(text) > _QUERY_CHAR_LIMIT:
        log.warning("Text truncated from %d to %d chars for embedding.", len(text), _QUERY_CHAR_LIMIT)
    query_text = text.strip()[:_QUERY_CHAR_LIMIT]

    if not query_text:
        raise HTTPException(status_code=422, detail="El texto no contiene contenido legal reconocible.")

    result = await run_analysis(request.app.state.engine, query_text)
    return JSONResponse(content=result)
