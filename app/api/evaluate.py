"""
app/api/evaluate.py
─────────────────────
FastAPI router for the RAGAS evaluation API.

Endpoints:
  POST /evaluate         — Run full or selective evaluation (c-level only)
  GET  /evaluate/status  — Get last evaluation status
  GET  /evaluate/report  — Download the HTML report

All endpoints require c-level role authorization.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.api.auth import get_current_user

logger = logging.getLogger("FinSight.EvaluateAPI")
router = APIRouter(prefix="/evaluate", tags=["Evaluation"])

# ── Paths ──────────────────────────────────────────────────────────────────────
EVAL_DIR         = Path(__file__).resolve().parent.parent / "rag_evaluator"
RAGAS_CSV        = EVAL_DIR / "evaluation_results_ragas.csv"
SECURITY_JSON    = EVAL_DIR / "rbac_security_report.json"
REPORT_HTML      = EVAL_DIR / "ragas_report.html"
STATUS_JSON      = EVAL_DIR / "last_eval_status.json"

# ── In-memory run lock (prevent concurrent evaluations) ────────────────────────
_eval_lock   = threading.Lock()
_eval_running = False


# ══════════════════════════════════════════════════════════════════════════════
#  REQUEST / RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════════════════

class EvaluateRequest(BaseModel):
    mode: Literal["full", "quality_only", "security_only"] = "full"
    roles: Optional[list[str]] = None
    max_per_role: int = 15
    use_builtin_dataset: bool = False


class EvaluateStatus(BaseModel):
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    overall: Optional[dict]
    pass_fail: Optional[dict]
    rbac_overall: Optional[str]
    report_available: bool


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH GUARD — c-level only
# ══════════════════════════════════════════════════════════════════════════════

def _require_clevel(current_user: dict = Depends(get_current_user)):
    role = (current_user.get("role") or "").lower()
    if role != "c-level":
        raise HTTPException(
            status_code=403,
            detail="Evaluation endpoints are restricted to c-level administrators."
        )
    return current_user


# ══════════════════════════════════════════════════════════════════════════════
#  BACKGROUND EVALUATION WORKER
# ══════════════════════════════════════════════════════════════════════════════

def _save_status(data: dict) -> None:
    STATUS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_status() -> dict:
    if STATUS_JSON.exists():
        try:
            return json.loads(STATUS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"status": "never_run"}


def _run_evaluation_background(
    mode: str,
    roles: Optional[list[str]],
    max_per_role: int,
    use_builtin: bool,
) -> None:
    global _eval_running

    started_at = datetime.now(timezone.utc).isoformat()
    _save_status({"status": "running", "started_at": started_at})
    logger.info(f"[Evaluate] Starting evaluation | mode={mode} roles={roles}")

    ragas_results   = None
    security_report = None

    try:
        # ── Quality evaluation ─────────────────────────────────────────────────
        if mode in ("full", "quality_only"):
            from app.rag_evaluator.ragas_evaluator import (
                evaluate_from_csv, evaluate_from_builtin
            )
            if use_builtin:
                ragas_results = evaluate_from_builtin(
                    roles=roles,
                    output_csv="evaluation_results_ragas.csv",
                )
            else:
                ragas_results = evaluate_from_csv(
                    roles=roles,
                    max_per_role=max_per_role,
                    output_csv="evaluation_results_ragas.csv",
                )

        # ── RBAC security evaluation ───────────────────────────────────────────
        if mode in ("full", "security_only"):
            from app.rag_evaluator.rbac_security_eval import run_all_security_tests
            security_report = run_all_security_tests(
                output_json="rbac_security_report.json",
                skip_ragas_test=(mode == "security_only"),
            )

        # ── Generate HTML report ───────────────────────────────────────────────
        from app.rag_evaluator.eval_report import generate_html_report
        generate_html_report(
            ragas_results=ragas_results,
            security_report=security_report,
            output_path=str(REPORT_HTML),
        )

        # ── Save status ────────────────────────────────────────────────────────
        completed_at = datetime.now(timezone.utc).isoformat()
        status_data = {
            "status":           "completed",
            "started_at":       started_at,
            "completed_at":     completed_at,
            "overall":          ragas_results.get("overall") if ragas_results else None,
            "pass_fail":        ragas_results.get("pass_fail") if ragas_results else None,
            "rbac_overall":     security_report.get("overall_status") if security_report else None,
            "report_available": REPORT_HTML.exists(),
        }
        _save_status(status_data)
        logger.info("[Evaluate] Evaluation completed successfully.")

    except Exception as exc:
        logger.error(f"[Evaluate] Evaluation failed: {exc}", exc_info=True)
        _save_status({
            "status":       "failed",
            "started_at":   started_at,
            "error":        str(exc),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    finally:
        with _eval_lock:
            _eval_running = False


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "",
    summary="Trigger RAGAS evaluation",
    description=(
        "Runs the RAGAS quality evaluation and/or RBAC security test suite. "
        "C-level role required. Runs in background — poll /evaluate/status for results."
    ),
)
async def trigger_evaluation(
    request: EvaluateRequest,
    background_tasks: BackgroundTasks,
    _user: dict = Depends(_require_clevel),
):
    global _eval_running

    with _eval_lock:
        if _eval_running:
            raise HTTPException(
                status_code=409,
                detail="An evaluation is already running. Check /evaluate/status."
            )
        _eval_running = True

    background_tasks.add_task(
        _run_evaluation_background,
        request.mode,
        request.roles,
        request.max_per_role,
        request.use_builtin_dataset,
    )

    return {
        "message":   "Evaluation started in background.",
        "mode":      request.mode,
        "roles":     request.roles or "all",
        "status_url": "/evaluate/status",
        "report_url": "/evaluate/report",
    }


@router.get(
    "/status",
    summary="Get last evaluation status",
    response_model=None,
)
async def get_evaluation_status(_user: dict = Depends(_require_clevel)):
    status = _load_status()
    status["report_available"] = REPORT_HTML.exists()
    return JSONResponse(content=status)


@router.get(
    "/report",
    summary="Download the HTML evaluation report",
    response_class=HTMLResponse,
)
async def get_evaluation_report(_user: dict = Depends(_require_clevel)):
    if not REPORT_HTML.exists():
        raise HTTPException(
            status_code=404,
            detail="No report available. Run POST /evaluate first."
        )
    return HTMLResponse(
        content=REPORT_HTML.read_text(encoding="utf-8"),
        status_code=200,
    )


@router.get(
    "/results",
    summary="Get latest RAGAS scores as JSON",
)
async def get_evaluation_results(_user: dict = Depends(_require_clevel)):
    status = _load_status()
    if status.get("status") not in ("completed",):
        raise HTTPException(
            status_code=404,
            detail=f"No completed evaluation. Current status: {status.get('status', 'unknown')}"
        )

    result = {
        "ragas_scores":   status.get("overall"),
        "pass_fail":      status.get("pass_fail"),
        "rbac_status":    status.get("rbac_overall"),
        "completed_at":   status.get("completed_at"),
    }

    # Attach security report summary if available
    if SECURITY_JSON.exists():
        try:
            security = json.loads(SECURITY_JSON.read_text(encoding="utf-8"))
            result["rbac_summary"] = security.get("summary")
        except Exception:
            pass

    return JSONResponse(content=result)
