"""
app/core/config.py — Centralised settings & API key resolution.

Replaces the old `app/rag_utils/secret_key.py`.  All env-var reads,
model fallback logic, and logging-suppression live here so every
other module has a single, authoritative source for configuration.
"""

import os
import warnings
import logging
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env early so every downstream import sees the variables ──────────────
load_dotenv()

# ── Suppress noisy retry / deprecation warnings ────────────────────────────────
warnings.filterwarnings("ignore", message=r"Retrying.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydantic")
logging.getLogger("langchain_google_genai").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google.generativeai").setLevel(logging.ERROR)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent   # project root

# ── Database settings ──────────────────────────────────────────────────────────
DB_NAME:     str = os.getenv("DB_NAME",     "roles_docs.db")
DUCKDB_NAME: str = os.getenv("DUCKDB_NAME", "structured_queries.duckdb")

DB_PATH:     Path = BASE_DIR / DB_NAME
DUCKDB_DIR:  Path = BASE_DIR / "static" / "data"
DUCKDB_PATH: Path = DUCKDB_DIR / DUCKDB_NAME

UPLOAD_DIR:  Path = BASE_DIR / "static" / "uploads"
RESOURCES_DIR: Path = BASE_DIR / "resources" / "data"

# ── API keys ───────────────────────────────────────────────────────────────────
google_api_key:  str = (
    os.getenv("GOOGLE_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or ""
)
openapi_key:    str = google_api_key          # backward-compat alias
langchain_key:  str = os.getenv("LANGCHAIN_API_KEY") or ""
cohere_api_key: str = os.getenv("COHERE_API_KEY")    or ""

# ── JWT ────────────────────────────────────────────────────────────────────────
JWT_SECRET_PATH: Path = BASE_DIR / "static" / "data" / "jwt_secret.key"
ALGORITHM:                 str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 720   # 12 hours

# ── Allowed CORS origins ───────────────────────────────────────────────────────
CORS_ORIGINS: list[str] = [
    "http://localhost:8501",
    "http://127.0.0.1:8501",
]

# ── Gemini model fallback list ─────────────────────────────────────────────────
GEMINI_MODELS: list[str] = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro-preview",
]


def generate_content_with_fallback(client, prompt: str) -> str:
    """Try each Gemini model in sequence; silently skip failures."""
    last_error: Exception | None = None
    for model_name in GEMINI_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return response.text.strip()
        except Exception as exc:
            last_error = exc
            continue
    raise last_error
