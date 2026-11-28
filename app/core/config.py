"""
app/core/config.py — Centralised settings, Postgres/ObjectStorage config & API key resolution.
"""

import logging
import os
import warnings
from pathlib import Path
from dotenv import load_dotenv

# Load .env early so every downstream module sees the variables
load_dotenv()

# Suppress noisy retry / deprecation warnings
warnings.filterwarnings("ignore", message=r"Retrying.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydantic")
logging.getLogger("langchain_google_genai").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google.generativeai").setLevel(logging.ERROR)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent  # project root

UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "static" / "uploads")))
RESOURCES_DIR: Path = BASE_DIR / "resources" / "data"
EVAL_OUTPUT_DIR: Path = Path(os.getenv("EVAL_OUTPUT_DIR", str(BASE_DIR / "static" / "evaluation")))
EVAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def normalize_database_url(raw_url: str) -> str:
    """Normalize postgresql URLs to the SQLAlchemy + psycopg v3 dialect."""
    url = (raw_url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_psycopg_conninfo(raw_url: str | None = None) -> str:
    """Return a plain postgresql:// DSN compatible with psycopg_pool & AsyncPostgresSaver."""
    url = normalize_database_url(raw_url or get_database_url())
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://"):]
    return url


def get_database_url() -> str:
    """Read DATABASE_URL (or TEST_DATABASE_URL in tests) dynamically and normalize dialect."""
    raw = (
        os.getenv("DATABASE_URL")
        or os.getenv("TEST_DATABASE_URL")
        or "postgresql+psycopg://postgres:postgres@localhost:5432/finsight"
    )
    return normalize_database_url(raw)


DATABASE_URL: str = get_database_url()

# ── Object Storage (S3 / MinIO or Local Dev Vault) ─────────────────────────────
STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "s3").strip().lower()
S3_ENDPOINT_URL: str = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000").strip()
S3_BUCKET: str = os.getenv("S3_BUCKET", "finsight-documents").strip()
S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY", "").strip()
S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY", "").strip()
S3_REGION: str = os.getenv("S3_REGION", "us-east-1").strip()

# ── Docling-Serve PDF / OCR Sidecar ────────────────────────────────────────────
DOCLING_SERVE_URL: str = os.getenv("DOCLING_SERVE_URL", "").strip().rstrip("/")
DOCLING_TIMEOUT_SECONDS: float = float(os.getenv("DOCLING_TIMEOUT_SECONDS", "120"))

# ── Embeddings & Contextual Retrieval ──────────────────────────────────────────
EMBEDDING_DIMENSIONS: int = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
CONTEXTUAL_RETRIEVAL_ENABLED: bool = (
    os.getenv("CONTEXTUAL_RETRIEVAL_ENABLED", "true").strip().lower() == "true"
)

# ── API keys ───────────────────────────────────────────────────────────────────
google_api_key: str = (
    os.getenv("GOOGLE_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or ""
)
if google_api_key:
    os.environ["GOOGLE_API_KEY"] = google_api_key
    os.environ.pop("GEMINI_API_KEY", None)

_genai_client = None


def get_genai_client():
    """Return a lazily initialized thread-safe google-genai Client."""
    global _genai_client
    if _genai_client is None:
        import threading

        lock = getattr(get_genai_client, "_lock", None)
        if lock is None:
            lock = threading.Lock()
            get_genai_client._lock = lock
        with lock:
            if _genai_client is None:
                key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or google_api_key
                if not key:
                    raise RuntimeError("GOOGLE_API_KEY is not configured")
                from google import genai

                _genai_client = genai.Client(api_key=key)
    return _genai_client


langchain_key: str = os.getenv("LANGCHAIN_API_KEY") or ""
cohere_api_key: str = os.getenv("COHERE_API_KEY") or ""

# ── JWT & Runtime Environment Validation ───────────────────────────────────────
JWT_SECRET_PATH: Path = BASE_DIR / "static" / "data" / "jwt_secret.key"
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 720  # 12 hours
APP_ENV: str = os.getenv("APP_ENV", "development").strip().lower()

# ── Allowed CORS origins ───────────────────────────────────────────────────────
_cors_env = os.getenv("CORS_ORIGINS")
if _cors_env:
    CORS_ORIGINS: list[str] = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]
else:
    CORS_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ]

# ── Redis, Caching & Rate Limiting ─────────────────────────────────────────────
REDIS_URL: str = os.getenv("REDIS_URL", "").strip()
RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

if APP_ENV == "production":
    if len(os.getenv("JWT_SECRET", "")) < 32:
        raise RuntimeError("Production requires a JWT_SECRET of at least 32 characters.")
    if not os.getenv("CORS_ORIGINS"):
        raise RuntimeError("Production requires explicit CORS_ORIGINS.")
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("Production requires explicit DATABASE_URL.")
    if not os.getenv("REDIS_URL"):
        raise RuntimeError("Production requires explicit REDIS_URL.")
    has_iam_role = bool(
        os.getenv("AWS_WEB_IDENTITY_TOKEN_FILE")
        or os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
        or os.getenv("S3_USE_IAM_ROLE", "").lower() == "true"
    )
    if STORAGE_BACKEND == "s3" and not ((S3_ACCESS_KEY and S3_SECRET_KEY) or has_iam_role):
        raise RuntimeError(
            "Production requires S3_ACCESS_KEY/S3_SECRET_KEY or IAM role credentials when STORAGE_BACKEND=s3."
        )

# ── Runtime model & proxy configuration (env-overridable) ──────────────────────
GEMINI_CHAT_MODEL: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.8-flash")
GEMINI_LIGHT_MODEL: str = os.getenv("GEMINI_LIGHT_MODEL", "gemini-3.5-flash-lite")
GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
COHERE_RERANK_MODEL: str = os.getenv("COHERE_RERANK_MODEL", "rerank-v3.5")

TRUSTED_PROXY_IPS: list[str] = [
    entry.strip()
    for entry in os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1/32,::1/128").split(",")
    if entry.strip()
]

# ── OpenFGA ReBAC Sidecar & Phase 2 Agentic Settings ──────────────────────────
OPENFGA_API_URL: str = os.getenv("OPENFGA_API_URL", "").strip().rstrip("/")
OPENFGA_API_TOKEN: str = os.getenv("OPENFGA_API_TOKEN", "").strip()
OPENFGA_STORE_NAME: str = os.getenv("OPENFGA_STORE_NAME", "finsight").strip() or "finsight"
OPENFGA_STORE_ID: str = os.getenv("OPENFGA_STORE_ID", "").strip()
OPENFGA_MODEL_ID: str = os.getenv("OPENFGA_MODEL_ID", "").strip()

PROMPT_INJECTION_GUARD_MODE: str = (
    os.getenv("PROMPT_INJECTION_GUARD_MODE", "filter_and_flag").strip().lower()
)
SQL_MAX_RETRIES: int = int(os.getenv("SQL_MAX_RETRIES", "2"))
AGENT_MAX_LOOPS: int = int(os.getenv("AGENT_MAX_LOOPS", "1"))

# ── Dual Auth: Cookies + Optional OIDC PKCE SSO ───────────────────────────────
SESSION_COOKIE_NAME: str = os.getenv("SESSION_COOKIE_NAME", "finsight_session").strip()
COOKIE_SECURE: bool = os.getenv(
    "COOKIE_SECURE",
    "true" if os.getenv("APP_ENV", "development").strip().lower() == "production" else "false",
).strip().lower() == "true"
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173").strip().rstrip("/")
OIDC_ENABLED: bool = os.getenv("OIDC_ENABLED", "false").strip().lower() == "true"
OIDC_PROVIDER_NAME: str = os.getenv("OIDC_PROVIDER_NAME", "Enterprise SSO").strip()
OIDC_ISSUER: str = os.getenv("OIDC_ISSUER", "").strip().rstrip("/")
OIDC_CLIENT_ID: str = os.getenv("OIDC_CLIENT_ID", "").strip()
OIDC_CLIENT_SECRET: str = os.getenv("OIDC_CLIENT_SECRET", "").strip()
OIDC_REDIRECT_URI: str = os.getenv(
    "OIDC_REDIRECT_URI", "http://localhost:8000/auth/oidc/callback"
).strip()
OIDC_SCOPES: str = os.getenv("OIDC_SCOPES", "openid email profile").strip()
OIDC_ROLE_CLAIM: str = os.getenv("OIDC_ROLE_CLAIM", "groups").strip()
OIDC_ROLE_MAP_JSON: str = os.getenv("OIDC_ROLE_MAP_JSON", "{}").strip()

# ── Runtime Observability, Telemetry & Audit Configuration ───────────────────────
LOG_FORMAT: str = os.getenv(
    "LOG_FORMAT", "json" if APP_ENV == "production" else "text"
).strip().lower()
OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "finsight-api").strip() or "finsight-api"
OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip().rstrip("/")
METRICS_ENABLED: bool = os.getenv("METRICS_ENABLED", "true").strip().lower() == "true"
METRICS_AUTH_TOKEN: str = os.getenv("METRICS_AUTH_TOKEN", "").strip()
AUDIT_STORE_PROMPT_PREVIEW: bool = (
    # Off by default in production: audit rows keep only a prompt hash unless explicitly opted in.
    os.getenv(
        "AUDIT_STORE_PROMPT_PREVIEW", "false" if APP_ENV == "production" else "true"
    ).strip().lower() == "true"
)

# ── Gemini model fallback list ─────────────────────────────────────────────────
GEMINI_MODELS: list[str] = list(dict.fromkeys([
    GEMINI_CHAT_MODEL,
    GEMINI_LIGHT_MODEL,
    "gemini-2.5-flash",
]))


def generate_content_with_fallback(
    client,
    prompt: str,
    preferred_model: str | None = None,
    config=None,
) -> str:
    """Try each Gemini model in sequence (optionally prioritizing preferred_model)."""
    candidates = (
        list(dict.fromkeys([preferred_model, *GEMINI_MODELS]))
        if preferred_model
        else GEMINI_MODELS
    )
    last_error: Exception | None = None
    for model_name in candidates:
        try:
            kwargs = {"model": model_name, "contents": prompt}
            if config is not None:
                kwargs["config"] = config
            response = client.models.generate_content(**kwargs)
            return response.text.strip()
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise RuntimeError("No Gemini models configured")


def generate_structured_with_fallback(
    client,
    prompt: str,
    schema_model,
    preferred_model: str | None = None,
):
    """Call Gemini JSON structured output and validate directly against Pydantic schema_model."""
    from google.genai import types

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=schema_model.model_json_schema(),
        temperature=0.1,
    )
    raw_json = generate_content_with_fallback(
        client,
        prompt,
        preferred_model=preferred_model,
        config=config,
    )
    return schema_model.model_validate_json(raw_json)
