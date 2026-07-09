"""
app/ui/constants.py — Shared UI constants (API URL, paths, role colours).
"""

import os
from pathlib import Path

API_URL       = "http://localhost:8000"
LOGIN_TIMEOUT = 8

BASE_DIR: str = str(Path(__file__).resolve().parent.parent.parent)  # project root
DB_PATH: str  = os.path.join(BASE_DIR, os.getenv("DB_NAME", "roles_docs.db"))

ROLE_COLORS: dict[str, str] = {
    "C-Level":     "#F59E0B",
    "HR":          "#10B981",
    "Finance":     "#3B82F6",
    "Engineering": "#A78BFA",
    "Marketing":   "#EC4899",
    "General":     "#64748B",
}
