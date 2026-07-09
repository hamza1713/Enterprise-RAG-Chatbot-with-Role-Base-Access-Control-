"""
app/core/users.py — Default user seeding helpers.

Moved out of the old monolithic main.py so startup logic is testable.
"""

import logging
import os

from .database import get_db_conn
from .security import hash_password, verify_password

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
    If a user already exists with the correct password hash, it is left
    unchanged.  If the hash is wrong (e.g. after a password env-var change),
    the hash is updated.
    """
    conn = get_db_conn()
    c    = conn.cursor()

    for role_name in _DEFAULT_ROLES:
        c.execute("INSERT OR IGNORE INTO roles (role_name) VALUES (?)", (role_name,))

    for username, plain_pw, role in _DEFAULT_USERS:
        c.execute("SELECT password FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        if not row:
            c.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, hash_password(plain_pw), role),
            )
        elif not verify_password(plain_pw, row[0]):
            c.execute(
                "UPDATE users SET password=? WHERE username=?",
                (hash_password(plain_pw), username),
            )

    conn.commit()
    conn.close()
    logger.info("[Users] Default users and roles seeded.")
