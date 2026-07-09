"""
app/core/security.py — JWT creation/verification and bcrypt authentication.

Extracted from the old monolithic `app/main.py`.  Only FastAPI-agnostic
logic lives here; the HTTP dependency wrappers are in `app/api/auth.py`.
"""

import os
import secrets
import logging

import bcrypt
import jwt
from datetime import datetime, timedelta, timezone

from .config import JWT_SECRET_PATH, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

logger = logging.getLogger("FinSight.security")

# ── Load or generate the JWT signing secret ────────────────────────────────────
if os.getenv("JWT_SECRET"):
    JWT_SECRET: str = os.getenv("JWT_SECRET")
elif JWT_SECRET_PATH.exists():
    JWT_SECRET = JWT_SECRET_PATH.read_text(encoding="utf-8").strip()
else:
    JWT_SECRET = secrets.token_hex(32)
    JWT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    JWT_SECRET_PATH.write_text(JWT_SECRET, encoding="utf-8")
    logger.info("[Security] Generated new JWT secret and saved to disk.")


# ══════════════════════════════════════════════════════════════════════════════
#  JWT helpers
# ══════════════════════════════════════════════════════════════════════════════

def create_access_token(data: dict) -> str:
    """Encode a JWT with an expiry timestamp."""
    to_encode = data.copy()
    expire    = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT.
    Raises jwt.PyJWTError on failure — callers convert to HTTP 401.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])


# ══════════════════════════════════════════════════════════════════════════════
#  bcrypt helpers
# ══════════════════════════════════════════════════════════════════════════════

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False
