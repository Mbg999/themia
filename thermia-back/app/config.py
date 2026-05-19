"""
Application configuration.
All settings are read from environment variables.
python-dotenv is used to load a .env file when present.
"""
import os

from dotenv import load_dotenv

load_dotenv()

THERMIA_ENV: str = os.environ.get("THERMIA_ENV", "production")

# Direct PostgreSQL URL (production path)
DATABASE_URL: str = os.environ.get("DATABASE_URL", "")

# SSH tunnel settings (local path)
SSH_HOST: str = os.environ.get("SSH_HOST", "")
SSH_USER: str = os.environ.get("SSH_USER", "")
SSH_PASSWORD: str = os.environ.get("SSH_PASSWORD", "")
SSH_REMOTE_BIND_PORT: str = os.environ.get("SSH_REMOTE_BIND_PORT", "5432")

# Database credentials (local path — tunnelled connection)
DB_USER: str = os.environ.get("DB_USER", "")
DB_PASSWORD: str = os.environ.get("DB_PASSWORD", "")
DB_NAME: str = os.environ.get("DB_NAME", "")

# Cohere API key (ingestion pipeline)
COHERE_API_KEY: str = os.environ.get("COHERE_API_KEY", "")

# Retrieval API auth token
API_KEY: str = os.environ.get("API_KEY", "")

# Groq LLM API key
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")

# CORS — comma-separated list of allowed origins
CORS_ORIGINS: str = os.environ.get("CORS_ORIGINS", "http://localhost:4200")
