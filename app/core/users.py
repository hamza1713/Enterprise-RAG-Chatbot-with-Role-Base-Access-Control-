"""
app/core/users.py — Default role & user seeding in PostgreSQL.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.authz.openfga import get_rebac_service
from app.core.config import APP_ENV
from app.core.security import hash_password
from app.db.models import Role, User
from app.db.session import sync_session

logger = logging.getLogger("FinSight.users")

_DEFAULT_USERS: list[tuple[str, str, str]] = [
    ("admin",       os.getenv("ADMIN_PASSWORD",       "admin123"),       "C-Level"),
    ("marketing",   os.getenv("MARKETING_PASSWORD",   "marketing123"),   "Marketing"),
    ("hr",          os.getenv("HR_PASSWORD",           "hr123"),          "HR"),
    ("finance",     os.getenv("FINANCE_PASSWORD",      "finance123"),     "Finance"),
    ("engineering", os.getenv("ENGINEERING_PASSWORD",  "engineering123"), "Engineering"),
]

_SYSTEM_ROLES: frozenset[str] = frozenset({"c-level", "general"})
_DEFAULT_ROLES: list[str] = ["C-Level", "Marketing", "HR", "Finance", "Engineering", "General"]


def _seed_roles_and_users(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(724901)"))

    roles_to_seed = (
        ["C-Level", "General"]
        if APP_ENV == "production"
        else _DEFAULT_ROLES
    )
    for role_name in roles_to_seed:
        existing_role = session.scalar(
            select(Role).where(func.lower(Role.role_name) == role_name.lower())
        )
        if existing_role is None:
            session.add(
                Role(
                    role_name=role_name,
                    is_system=role_name.lower() in _SYSTEM_ROLES,
                )
            )
        elif role_name.lower() in _SYSTEM_ROLES and not existing_role.is_system:
            existing_role.is_system = True

    session.flush()

    for username, plain_pw, role in _DEFAULT_USERS:
        if APP_ENV == "production" and username != "admin":
            continue

        existing_user = session.scalar(
            select(User).where(func.lower(User.username) == username.lower())
        )
        if existing_user is None:
            if APP_ENV == "production":
                plain_pw = os.getenv("ADMIN_PASSWORD", "")
                if len(plain_pw) < 14 or plain_pw == "admin123":
                    raise RuntimeError(
                        "Initial production setup requires an ADMIN_PASSWORD of at least 14 characters."
                    )
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(plain_pw),
                    role_name=role,
                    is_active=True,
                    token_version=1,
                )
            )
            session.flush()
        get_rebac_service().sync_user_roles(
            session,
            existing_user.username if existing_user else username,
            existing_user.role_name if existing_user else role,
            is_active=bool(existing_user.is_active) if existing_user else True,
            created_by="seed",
        )


def seed_default_users(session: Session | None = None) -> None:
    """
    Insert default roles and users idempotently.
    Existing account passwords are never overwritten on application startup.
    """
    if session is not None:
        _seed_roles_and_users(session)
        session.commit()
    else:
        with sync_session() as db:
            _seed_roles_and_users(db)
            db.commit()
    logger.info("[Users] Default users and roles seeded.")
