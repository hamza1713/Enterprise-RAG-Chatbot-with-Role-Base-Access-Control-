"""
app/api/health.py — Health & diagnostics endpoints.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/")
def health_check():
    """Basic liveness probe."""
    return {"status": "ok", "service": "FinSight API"}
