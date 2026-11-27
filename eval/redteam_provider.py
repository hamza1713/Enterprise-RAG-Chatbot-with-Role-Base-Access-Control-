"""
eval/redteam_provider.py — Promptfoo Python provider bridge for FinSight OWASP LLM red-teaming.

Supports offline guardrail/SQL-AST/ReBAC simulation OR live HTTP API probing when
FINSIGHT_REDTEAM_BASE_URL + credentials are configured cleanly.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.rag.csv_query import extract_tables_from_sql, is_safe_query
from app.rag.guardrails import (
    check_direct_jailbreak,
    redact_sensitive_output,
    scan_text_for_injection,
)


def _evaluate_offline(prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    vars_dict = dict(context.get("vars") or {})
    scenario = str(vars_dict.get("scenario", "chat")).lower()

    if scenario == "direct_jailbreak":
        refusal = check_direct_jailbreak(prompt)
        return {
            "output": refusal or f"ALLOWED:{prompt}",
            "metadata": {"blocked": bool(refusal), "scenario": scenario},
        }

    if scenario == "indirect_doc":
        scan = scan_text_for_injection(prompt)
        return {
            "output": scan.sanitized_text,
            "metadata": {"flagged": scan.flagged, "reasons": scan.reasons, "scenario": scenario},
        }

    if scenario == "output_redaction":
        res = redact_sensitive_output(prompt)
        return {
            "output": res.text,
            "metadata": {"redacted": res.redacted, "categories": res.categories, "scenario": scenario},
        }

    if scenario == "sql_sandbox":
        allowed_tables = [str(t).lower() for t in (vars_dict.get("allowed_tables") or ["hr_data"])]
        if not is_safe_query(prompt):
            return {
                "output": "SQL_BLOCKED: Disallowed SQL AST statement or function.",
                "metadata": {"allowed": False, "reason": "unsafe_ast", "scenario": scenario},
            }
        tables = extract_tables_from_sql(prompt)
        unauthorized = [t for t in tables if t.lower() not in allowed_tables]
        if not tables or unauthorized:
            return {
                "output": f"SQL_BLOCKED: Unauthorized table access attempted ({unauthorized}).",
                "metadata": {
                    "allowed": False,
                    "reason": "unauthorized_table",
                    "tables": tables,
                    "scenario": scenario,
                },
            }
        return {
            "output": f"SQL_ALLOWED:{prompt}",
            "metadata": {"allowed": True, "tables": tables, "scenario": scenario},
        }

    refusal = check_direct_jailbreak(prompt)
    if refusal:
        return {"output": refusal, "metadata": {"blocked": True, "scenario": scenario}}
    res = redact_sensitive_output(prompt)
    return {"output": res.text, "metadata": {"blocked": False, "redacted": res.redacted}}


def _evaluate_live_http(prompt: str, context: dict[str, Any], base_url: str) -> dict[str, Any]:
    import httpx

    vars_dict = dict(context.get("vars") or {})
    username = str(vars_dict.get("username") or os.getenv("FINSIGHT_REDTEAM_USER", "hr_user"))
    password = str(vars_dict.get("password") or os.getenv("FINSIGHT_REDTEAM_PASSWORD", ""))
    if not password:
        return {"error": "FINSIGHT_REDTEAM_PASSWORD required when FINSIGHT_REDTEAM_BASE_URL is set."}

    with httpx.Client(base_url=base_url.rstrip("/"), timeout=45.0) as client:
        login_resp = client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        if login_resp.status_code != 200:
            return {"error": f"Login failed ({login_resp.status_code})"}
        token = login_resp.json().get("access_token", "")
        chat_resp = client.post(
            "/chat",
            json={"question": prompt, "history": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        if chat_resp.status_code != 200:
            return {"error": f"Chat failed ({chat_resp.status_code}): {chat_resp.text}"}
        body = chat_resp.json()
        return {
            "output": str(body.get("answer", "")),
            "metadata": {"mode": body.get("mode"), "sources": body.get("sources", [])},
        }


def call_api(
    prompt: str,
    options: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Promptfoo Python provider entry point."""
    del options
    ctx = context or {}
    base_url = os.getenv("FINSIGHT_REDTEAM_BASE_URL", "").strip()
    if base_url and str((ctx.get("vars") or {}).get("mode", "")).lower() == "live":
        return _evaluate_live_http(prompt, ctx, base_url)
    return _evaluate_offline(prompt, ctx)
