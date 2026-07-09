"""
app/api/auth.py — Authentication endpoints.

Handles:  GET /login   POST (future: refresh, logout)
JWT dependency (get_current_user) used by all other routers.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials

from app.core.database import get_db_conn
from app.core.security import create_access_token, decode_access_token, verify_password

logger = logging.getLogger("FinSight.auth")

router = APIRouter(tags=["auth"])

_basic  = HTTPBasic()
_bearer = HTTPBearer()


# ── Dependency: verify Bearer JWT and return {username, role} ─────────────────
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    token = credentials.credentials
    try:
        payload  = decode_access_token(token)
        username = payload.get("sub")
        role     = payload.get("role")
        if not username or not role:
            raise HTTPException(status_code=401, detail="Invalid authentication token payload.")
        return {"username": username, "role": role}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token.")


# ── Dependency: HTTP Basic auth (login endpoint only) ─────────────────────────
def _authenticate_basic(credentials: HTTPBasicCredentials = Depends(_basic)) -> dict:
    username = credentials.username.strip()
    password = credentials.password.strip()

    conn = get_db_conn()
    row  = conn.execute(
        "SELECT password, role FROM users WHERE username=?", (username,)
    ).fetchone()
    conn.close()

    if not row or not verify_password(password, row[0]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return {"username": username, "role": row[1]}


# ── Routes ────────────────────────────────────────────────────────────────────
@router.get("/login")
def login(user: dict = Depends(_authenticate_basic)):
    """Exchange HTTP Basic credentials for a JWT access token."""
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return {
        "message":      f"Welcome {user['username']}!",
        "role":         user["role"],
        "access_token": token,
    }
