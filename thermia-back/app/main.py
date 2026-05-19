"""
Thermia backend — FastAPI application entry point.
"""
from fastapi import FastAPI

# Load configuration (triggers python-dotenv .env loading)
from app.config import THERMIA_ENV  # noqa: F401

app = FastAPI(title="Thermia API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
