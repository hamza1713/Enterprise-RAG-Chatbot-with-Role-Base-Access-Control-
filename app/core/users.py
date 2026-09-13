"""
app/core/users.py — Default user seeding helpers.

Moved out of the old monolithic main.py so startup logic is testable.
"""

import logging
import os

from .database import get_db_conn
from .security import hash_password
from .config import APP_ENV

logger = logging.getLogger("FinSight.users")

_DEFAULT_USERS: list[tuple[str, str, str]] = [
    ("admin",       os.getenv("ADMIN_PASSWORD",       "admin123"),       "C-Level"),
    ("marketing",   os.getenv("MARKETING_PASSWORD",   "marketing123"),   "Marketing"),
    ("Hamza",       os.getenv("HAMZA_PASSWORD",        "marketing123"),   "Marketing"),
    ("hr",          os.getenv("HR_PASSWORD",           "hr123"),          "HR"),
    ("finance",     os.getenv("FINANCE_PASSWORD",      "finance123"),     "Finance"),
    ("engineering", os.getenv("ENGINEERING_PASSWORD",  "engineering123"), "Engineering"),
]

_DEFAULT_ROLES: list[str] = ["C-Level", "Marketing", "HR", "Finance", "Engineering", "General"]


def seed_default_users() -> None:
    """
    Insert default roles and users if they don't exist yet.
    Existing account passwords are never overwritten on application startup.
    Production seeds only an explicitly configured administrator account.
    """
    conn = get_db_conn()
    c    = conn.cursor()

    for role_name in _DEFAULT_ROLES:
        c.execute("INSERT OR IGNORE INTO roles (role_name) VALUES (?)", (role_name,))

    for username, plain_pw, role in _DEFAULT_USERS:
        if APP_ENV == 'production' and username != 'admin':
            continue
        c.execute("SELECT password FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        if not row:
            if APP_ENV == 'production':
                plain_pw = os.getenv('ADMIN_PASSWORD', '')
                if len(plain_pw) < 14 or plain_pw == 'admin123':
                    conn.close()
                    raise RuntimeError('Initial production setup requires an ADMIN_PASSWORD of at least 14 characters.')
            c.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, hash_password(plain_pw), role),
            )

    conn.commit()
    conn.close()
    logger.info("[Users] Default users and roles seeded.")
