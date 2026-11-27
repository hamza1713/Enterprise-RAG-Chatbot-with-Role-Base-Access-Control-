"""
app/api/auth.py — Dual Authentication (HttpOnly Cookie + Bearer JWT + Optional OIDC PKCE SSO).
"""

from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import urlparse

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.openfga import get_rebac_service
from app.core.audit import record_audit_event
from app.core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    APP_ENV,
    COOKIE_SECURE,
    CORS_ORIGINS,
    FRONTEND_URL,
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_ENABLED,
    OIDC_ISSUER,
    OIDC_PROVIDER_NAME,
    OIDC_REDIRECT_URI,
    OIDC_ROLE_CLAIM,
    OIDC_ROLE_MAP_JSON,
    OIDC_SCOPES,
    SESSION_COOKIE_NAME,
)
from app.core.limiter import limiter
from app.core.security import create_access_token, decode_access_token, verify_password
from app.db.models import Role, User
from app.db.session import get_db

logger = logging.getLogger("FinSight.auth")

router = APIRouter(tags=["auth"])

_basic = HTTPBasic(auto_error=False)
_bearer = HTTPBearer(auto_error=False)
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_oauth_registry: OAuth | None = None
_oidc_configured_key: tuple[str, str, str] | None = None


class LocalLoginRequest(BaseModel):
    username: str
    password: str


def _origin_from_url(raw: str | None) -> str | None:
    if not raw:
        return None
    parsed = urlparse(raw.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _allowed_origins(request: Request) -> set[str]:
    origins: set[str] = set()
    for item in (*CORS_ORIGINS, FRONTEND_URL):
        o = _origin_from_url(item)
        if o:
            origins.add(o)
    req_origin = _origin_from_url(str(request.base_url))
    if req_origin:
        origins.add(req_origin)
    return origins


def verify_csrf_for_cookie_auth(request: Request) -> None:
    """
    Validate request Origin/Referer for browser state-changing calls authenticated via
    HttpOnly cookie (exempting explicit `Authorization: Bearer` API clients).
    """
    if request.method.upper() not in _MUTATING_METHODS:
        return
    fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site CSRF check failed.")

    allowed = _allowed_origins(request)
    origin = _origin_from_url(request.headers.get("origin"))
    if origin is not None:
        if origin not in allowed:
            raise HTTPException(status_code=403, detail="CSRF origin mismatch.")
        return

    referer_origin = _origin_from_url(request.headers.get("referer"))
    if referer_origin is not None:
        if referer_origin not in allowed:
            raise HTTPException(status_code=403, detail="CSRF referer mismatch.")
        return

    ua = (request.headers.get("user-agent") or "").lower()
    if APP_ENV == "production" and "mozilla/" in ua:
        raise HTTPException(status_code=403, detail="Missing Origin header on cookie mutation.")


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )


def _is_oidc_runtime_enabled() -> bool:
    env_flag = os.getenv("OIDC_ENABLED")
    enabled = (
        env_flag.strip().lower() == "true"
        if env_flag is not None
        else OIDC_ENABLED
    )
    issuer = (os.getenv("OIDC_ISSUER") or OIDC_ISSUER).strip()
    client_id = (os.getenv("OIDC_CLIENT_ID") or OIDC_CLIENT_ID).strip()
    return bool(enabled and issuer and client_id)


def get_oidc_client():
    """Return a lazily registered Authlib OIDC client with PKCE S256."""
    global _oauth_registry, _oidc_configured_key
    issuer = (os.getenv("OIDC_ISSUER") or OIDC_ISSUER).strip().rstrip("/")
    client_id = (os.getenv("OIDC_CLIENT_ID") or OIDC_CLIENT_ID).strip()
    client_secret = (os.getenv("OIDC_CLIENT_SECRET") or OIDC_CLIENT_SECRET).strip()
    scopes = (os.getenv("OIDC_SCOPES") or OIDC_SCOPES or "openid email profile").strip()
    config_key = (issuer, client_id, scopes)
    if _oauth_registry is None or _oidc_configured_key != config_key:
        oauth = OAuth()
        oauth.register(
            name="oidc",
            client_id=client_id,
            client_secret=client_secret or None,
            server_metadata_url=f"{issuer}/.well-known/openid-configuration",
            client_kwargs={
                "scope": scopes,
                "code_challenge_method": "S256",
            },
        )
        _oauth_registry = oauth
        _oidc_configured_key = config_key
    return _oauth_registry.oidc


def extract_oidc_role(claims: dict, available_roles: list[str]) -> str:
    """
    Resolve an IdP group/role claim through explicit `OIDC_ROLE_MAP_JSON` into a valid
    FinSight role, always failing closed to `'General'` if unmapped.
    """
    raw_map = (os.getenv("OIDC_ROLE_MAP_JSON") or OIDC_ROLE_MAP_JSON or "{}").strip()
    try:
        role_map = {str(k).strip().lower(): str(v).strip() for k, v in json.loads(raw_map).items()}
    except Exception:
        role_map = {}

    by_lower = {r.lower(): r for r in available_roles}
    claim_key = (os.getenv("OIDC_ROLE_CLAIM") or OIDC_ROLE_CLAIM or "groups").strip()
    raw_claim = claims.get(claim_key)
    if isinstance(raw_claim, str):
        claim_vals = [raw_claim]
    elif isinstance(raw_claim, list):
        claim_vals = [str(v) for v in raw_claim]
    else:
        claim_vals = []

    for val in claim_vals:
        mapped = role_map.get(val.strip().lower(), val.strip())
        if mapped.lower() in by_lower:
            return by_lower[mapped.lower()]

    return by_lower.get("general", "General")


async def provision_or_update_oidc_user(
    db: AsyncSession,
    *,
    sub: str,
    preferred_username: str | None,
    email: str | None,
    role_name: str,
) -> User:
    """
    Isolate OIDC identities strictly by `(auth_provider='oidc', oidc_sub=sub)` so a
    username string can never collide with or take over a local password account.
    """
    existing = await db.scalar(
        select(User).where(User.auth_provider == "oidc", User.oidc_sub == sub)
    )
    if existing is not None:
        if not existing.is_active:
            raise HTTPException(status_code=403, detail="Account has been deactivated.")
        old_role = existing.role_name
        existing.email = email or existing.email
        if existing.role_name.lower() != role_name.lower():
            existing.role_name = role_name
            existing.token_version = int(existing.token_version or 1) + 1
        await db.flush()
        await get_rebac_service().async_user_roles(
            db,
            existing.username,
            existing.role_name,
            is_active=True,
            previous_role=old_role,
            created_by="oidc",
        )
        await db.commit()
        await db.refresh(existing)
        return existing

    raw_base = (
        preferred_username
        or (email.split("@", 1)[0] if email and "@" in email else "")
        or f"sso_{sub[:10]}"
    )
    clean_base = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_base.strip()).strip("._-") or "sso_user"
    clean_base = clean_base[:48]
    candidate = clean_base if len(clean_base) >= 3 else f"sso_{clean_base}"

    collision = await db.scalar(
        select(User).where(func.lower(User.username) == candidate.lower())
    )
    if collision is not None:
        sub_slug = re.sub(r"[^a-z0-9]", "", sub.lower())[:8] or "oidc"
        candidate = f"{candidate[:45]}_{sub_slug}"

    new_user = User(
        username=candidate,
        password_hash="!oidc-managed!",
        role_name=role_name,
        email=email,
        auth_provider="oidc",
        oidc_sub=sub,
        is_active=True,
        token_version=1,
    )
    db.add(new_user)
    await db.flush()
    await get_rebac_service().async_user_roles(
        db,
        new_user.username,
        new_user.role_name,
        is_active=True,
        created_by="oidc",
    )
    await db.commit()
    await db.refresh(new_user)
    return new_user


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Validate Bearer JWT or HttpOnly session cookie against active DB user and token_version.
    Enforces origin CSRF verification when authenticating via browser cookie on mutations.
    """
    used_cookie = False
    token = credentials.credentials if credentials is not None else None
    if not token:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        used_cookie = bool(token)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    if used_cookie:
        verify_csrf_for_cookie_auth(request)

    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
        role = payload.get("role")
        tv = payload.get("tv")
        if not username or not role or tv is None:
            raise HTTPException(status_code=401, detail="Invalid authentication token payload.")

        user = await db.scalar(
            select(User).where(func.lower(User.username) == str(username).lower())
        )
        if (
            user is None
            or not user.is_active
            or user.role_name.lower() != str(role).lower()
            or int(user.token_version) != int(tv)
        ):
            raise HTTPException(
                status_code=401,
                detail="Account access has changed. Please sign in again.",
            )
        return {
            "username": user.username,
            "role": user.role_name,
            "auth_provider": getattr(user, "auth_provider", "local") or "local",
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token.",
        )


async def _verify_local_credentials(
    db: AsyncSession, username: str, password: str
) -> dict:
    clean_username = (username or "").strip()
    user = await db.scalar(
        select(User).where(func.lower(User.username) == clean_username.lower())
    )
    if (
        user is None
        or getattr(user, "auth_provider", "local") != "local"
        or not verify_password(password, user.password_hash)
    ):
        await record_audit_event(
            username=clean_username or "unknown",
            user_role=user.role_name if user is not None else "unknown",
            auth_provider="local",
            event_type="auth_login",
            outcome="deny",
            ai_disclosure=False,
        )
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if not user.is_active:
        await record_audit_event(
            username=user.username,
            user_role=user.role_name,
            auth_provider="local",
            event_type="auth_login",
            outcome="deny",
            ai_disclosure=False,
        )
        raise HTTPException(status_code=401, detail="Account has been deactivated.")
    return {
        "username": user.username,
        "role": user.role_name,
        "token_version": user.token_version,
        "auth_provider": "local",
    }


async def _authenticate_basic(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication credentials required.")
    return await _verify_local_credentials(db, credentials.username, credentials.password)


@router.get("/auth/providers")
async def get_auth_providers():
    """Advertise enabled login mechanisms cleanly to the frontend LoginPage."""
    return {
        "local_enabled": True,
        "oidc_enabled": _is_oidc_runtime_enabled(),
        "provider_name": os.getenv("OIDC_PROVIDER_NAME") or OIDC_PROVIDER_NAME,
    }


@router.get("/login")
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    user: dict = Depends(_authenticate_basic),
):
    """Exchange HTTP Basic credentials for an HttpOnly session cookie + Bearer token."""
    token = create_access_token(
        {
            "sub": user["username"],
            "role": user["role"],
            "tv": user["token_version"],
            "auth_provider": user["auth_provider"],
        }
    )
    _set_session_cookie(response, token)
    await record_audit_event(
        username=user["username"],
        user_role=user["role"],
        auth_provider=user["auth_provider"],
        event_type="auth_login",
        outcome="allow",
        ai_disclosure=False,
    )
    return {
        "message": f"Welcome {user['username']}!",
        "username": user["username"],
        "role": user["role"],
        "auth_provider": user["auth_provider"],
        "access_token": token,
    }


@router.post("/auth/login")
@limiter.limit("5/minute")
async def local_login(
    request: Request,
    response: Response,
    body: LocalLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """JSON login endpoint issuing HttpOnly cookie + optional Bearer token for SPA/clients."""
    user = await _verify_local_credentials(db, body.username, body.password)
    token = create_access_token(
        {
            "sub": user["username"],
            "role": user["role"],
            "tv": user["token_version"],
            "auth_provider": user["auth_provider"],
        }
    )
    _set_session_cookie(response, token)
    await record_audit_event(
        username=user["username"],
        user_role=user["role"],
        auth_provider=user["auth_provider"],
        event_type="auth_login",
        outcome="allow",
        ai_disclosure=False,
    )
    return {
        "user": {
            "username": user["username"],
            "role": user["role"],
            "auth_provider": user["auth_provider"],
        },
        "role": user["role"],
        "access_token": token,
        "token_type": "bearer",
    }


@router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Return active authenticated session principal for cookie-based SPA hydration."""
    return user


@router.post("/auth/logout")
async def logout(
    request: Request,
    response: Response,
    revoke_all: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Clear HttpOnly session cookie and optionally bump token_version across devices."""
    verify_csrf_for_cookie_auth(request)
    if revoke_all:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if not token:
            auth_hdr = request.headers.get("authorization") or ""
            if auth_hdr.lower().startswith("bearer "):
                token = auth_hdr[7:].strip()
        if token:
            try:
                payload = decode_access_token(token)
                uname = payload.get("sub")
                if uname:
                    u = await db.scalar(
                        select(User).where(func.lower(User.username) == str(uname).lower())
                    )
                    if u is not None:
                        u.token_version = int(u.token_version or 1) + 1
                        await db.commit()
            except Exception:
                pass
    _clear_session_cookie(response)
    return {"message": "Signed out."}


@router.get("/auth/oidc/login")
async def oidc_login(request: Request):
    """Start OIDC Authorization Code + PKCE (S256) login redirect."""
    if not _is_oidc_runtime_enabled():
        raise HTTPException(status_code=404, detail="OIDC SSO is not enabled.")
    redirect_uri = (
        os.getenv("OIDC_REDIRECT_URI") or OIDC_REDIRECT_URI or str(request.url_for("oidc_callback"))
    ).strip()
    oidc = get_oidc_client()
    return await oidc.authorize_redirect(request, redirect_uri)


@router.get("/auth/oidc/callback", name="oidc_callback")
async def oidc_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Complete OIDC PKCE callback, provision/sync user + OpenFGA tuples, set HttpOnly cookie."""
    if not _is_oidc_runtime_enabled():
        raise HTTPException(status_code=404, detail="OIDC SSO is not enabled.")
    frontend_base = (os.getenv("FRONTEND_URL") or FRONTEND_URL or "http://localhost:5173").rstrip("/")
    oidc = get_oidc_client()
    try:
        token_resp = await oidc.authorize_access_token(request)
    except Exception as exc:
        logger.warning(f"[Auth.OIDC] Callback token exchange failed: {type(exc).__name__}")
        return RedirectResponse(
            url=f"{frontend_base}/login?sso_error=token_exchange_failed",
            status_code=302,
        )

    claims = dict(token_resp.get("userinfo") or {})
    if not claims and hasattr(oidc, "parse_id_token"):
        try:
            claims = dict(await oidc.parse_id_token(request, token_resp) or {})
        except Exception:
            claims = {}

    sub = str(claims.get("sub") or "").strip()
    if not sub:
        return RedirectResponse(url=f"{frontend_base}/login?sso_error=missing_sub", status_code=302)

    roles = list(await db.scalars(select(Role.role_name)))
    role_name = extract_oidc_role(claims, roles)
    try:
        user_obj = await provision_or_update_oidc_user(
            db,
            sub=sub,
            preferred_username=claims.get("preferred_username") or claims.get("name"),
            email=claims.get("email"),
            role_name=role_name,
        )
    except HTTPException:
        return RedirectResponse(
            url=f"{frontend_base}/login?sso_error=account_disabled",
            status_code=302,
        )

    session_jwt = create_access_token(
        {
            "sub": user_obj.username,
            "role": user_obj.role_name,
            "tv": user_obj.token_version,
            "auth_provider": "oidc",
        }
    )
    redirect = RedirectResponse(url=f"{frontend_base}/chat", status_code=302)
    _set_session_cookie(redirect, session_jwt)
    await record_audit_event(
        username=user_obj.username,
        user_role=user_obj.role_name,
        auth_provider="oidc",
        event_type="auth_login",
        outcome="allow",
        ai_disclosure=False,
    )
    return redirect
