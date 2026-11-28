"""
app/rag_evaluator/cli.py — Unified evaluation CLI replacing root runner scripts.

Usage:
    python -m app.rag_evaluator.cli --mode full
    python -m app.rag_evaluator.cli --mode no-llm
    python -m app.rag_evaluator.cli --mode security
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv

from app.core.config import EVAL_OUTPUT_DIR, google_api_key
from app.core.logging_config import configure_logging
from app.rag_evaluator.eval_report import generate_html_report

logger = logging.getLogger("FinSight.EvalCLI")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.rag_evaluator.cli",
        description="Unified FinSight RAGAS & Security Evaluation Runner",
    )
    parser.add_argument(
        "--mode",
        choices=("full", "no-llm", "security"),
        default="full",
        help="Evaluation suite mode: full (RAGAS + Security), no-llm (embedding/BM25), or security only.",
    )
    parser.add_argument(
        "--roles",
        nargs="+",
        default=["finance", "hr", "engineering", "marketing"],
        help="Target department roles for dataset/quality evaluation.",
    )
    parser.add_argument(
        "--skip-ragas-leakage",
        action="store_true",
        help="Skip Test 6 LLM-based cross-role leakage score inside security suite.",
    )
    return parser.parse_args(argv)


def run_cli(
    *,
    mode: str = "full",
    roles: list[str] | None = None,
    skip_ragas_leakage: bool = False,
) -> dict[str, Any]:
    """Execute requested evaluation mode cleanly and persist status/report artifacts."""
    load_dotenv()
    configure_logging()
    os.environ["ANONYMIZED_TELEMETRY"] = "False"

    target_roles = roles or ["finance", "hr", "engineering", "marketing"]
    started_at = datetime.now(timezone.utc).isoformat()
    status_path = EVAL_OUTPUT_DIR / "last_eval_status.json"
    report_path = EVAL_OUTPUT_DIR / "ragas_report.html"

    key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or google_api_key or "").strip()
    if mode in ("full", "no-llm") and not key:
        raise RuntimeError("GOOGLE_API_KEY is required for full or no-llm evaluation modes.")

    quality_results: dict[str, Any] | None = None
    security_report: dict[str, Any] | None = None

    if mode == "full":
        from app.rag_evaluator.eval_dataset import load_builtin_dataset_with_rag
        from app.rag_evaluator.ragas_evaluator import run_quick_evaluation

        logger.info("[EvalCLI] Running full RAGAS quality suite for roles=%s", target_roles)
        dataset = load_builtin_dataset_with_rag(roles=target_roles, sleep_between_calls=0.5)
        quality_results = run_quick_evaluation(
            dataset=dataset,
            output_csv="evaluation_results_ragas_quick.csv",
        )
    elif mode == "no-llm":
        import pandas as pd
        from app.rag_evaluator.eval_dataset import load_builtin_dataset_with_rag
        from app.rag_evaluator.no_llm_evaluator import run_no_llm_evaluation

        input_csv = EVAL_OUTPUT_DIR / "evaluation_results_ragas_quick.csv"
        if not input_csv.is_file():
            logger.info("[EvalCLI] Building quick dataset CSV prior to no-llm scoring...")
            dataset = load_builtin_dataset_with_rag(roles=target_roles, sleep_between_calls=0.5)
            rows = [
                {
                    "user_input": r["user_input"],
                    "retrieved_contexts": str(r["retrieved_contexts"]),
                    "response": r["response"],
                    "reference": r.get("reference", ""),
                    "role": r.get("role", ""),
                }
                for r in dataset
            ]
            pd.DataFrame(rows).to_csv(input_csv, index=False)

        raw = run_no_llm_evaluation(
            csv_path=str(input_csv),
            output_csv="evaluation_results_no_llm.csv",
            sleep_between_samples=0.3,
        )
        quality_results = {
            "overall": raw["overall"],
            "per_role": raw.get("per_role", {}),
            "pass_fail": raw["pass_fail"],
            "dataframe": None,
            "csv_path": raw["csv_path"],
        }

    from app.rag_evaluator.rbac_security_eval import run_all_security_tests

    security_report = run_all_security_tests(
        output_json="rbac_security_report.json",
        skip_ragas_test=(mode != "full" or skip_ragas_leakage),
    )

    generate_html_report(
        ragas_results=quality_results,
        security_report=security_report,
        output_path=str(report_path),
    )

    payload: dict[str, Any] = {
        "status": "completed",
        "mode": mode,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "overall": quality_results.get("overall") if quality_results else None,
        "per_role": quality_results.get("per_role") if quality_results else None,
        "pass_fail": quality_results.get("pass_fail") if quality_results else None,
        "rbac_overall": security_report.get("overall_status") if security_report else None,
        "rbac_summary": security_report.get("summary") if security_report else None,
        "report_available": Path(report_path).is_file(),
    }
    status_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "[EvalCLI] Evaluation completed: mode=%s rbac=%s report=%s",
        mode,
        payload["rbac_overall"],
        report_path,
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = _parse_args(argv)
    try:
        result = run_cli(
            mode=args.mode,
            roles=args.roles,
            skip_ragas_leakage=args.skip_ragas_leakage,
        )
        return 0 if result.get("rbac_overall", "PASS") == "PASS" else 1
    except Exception as exc:
        logger.error("[EvalCLI] Evaluation failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
