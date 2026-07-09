"""
app/rag_evaluator/ragas_evaluator.py
──────────────────────────────────────
Production RAGAS evaluation engine for the FinSight RBAC RAG chatbot.

Uses RAGAS 0.2+ with LangchainLLMWrapper around Gemini (no OpenAI needed).

Metrics evaluated per-role:
  ┌──────────────────────┬──────────────────────────────────────────────────┐
  │ Metric               │ What it measures                                 │
  ├──────────────────────┼──────────────────────────────────────────────────┤
  │ Faithfulness         │ Answer grounded in context (hallucination check) │
  │ AnswerRelevancy      │ Answer pertinence to the question                │
  │ ContextPrecision     │ Retrieved chunks ranked by relevance             │
  │ LLMContextRecall     │ Context covers ground truth information          │
  │ AnswerCorrectness    │ Factual correctness vs ground truth              │
  └──────────────────────┴──────────────────────────────────────────────────┘

Production thresholds (research-backed, conservative for Gemini LLM-as-judge):
  - faithfulness:       >= 0.75  (warning: < 0.85 | critical: < 0.65)
  - answer_relevancy:   >= 0.70  (warning: < 0.75 | critical: < 0.55)
  - context_precision:  >= 0.65  (warning: < 0.70 | critical: < 0.50)
  - context_recall:     >= 0.70  (warning: < 0.75 | critical: < 0.55)
  - answer_correctness: >= 0.60  (warning: < 0.65 | critical: < 0.45)

Rationale for thresholds:
  - Set slightly below the "ideal" (0.90+) to account for Gemini-as-judge
    vs GPT-4 calibration differences (Gemini tends to be stricter)
  - Starting conservative allows baselines to be established first,
    then tightened iteratively as the system improves
  - Two-tier (warning vs critical) prevents noisy CI failures on
    borderline cases while still catching real regressions
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# ── Path setup ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("FinSight.RagasEvaluator")


# ══════════════════════════════════════════════════════════════════════════════
#  THRESHOLD CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

THRESHOLDS = {
    "faithfulness":       {"pass": 0.75, "warn": 0.85},
    "answer_relevancy":   {"pass": 0.70, "warn": 0.75},
    "context_precision":  {"pass": 0.65, "warn": 0.70},
    "context_recall":     {"pass": 0.70, "warn": 0.75},
    "answer_correctness": {"pass": 0.60, "warn": 0.65},
}

# Metrics that require ground_truth (reference)
REFERENCE_REQUIRED_METRICS = {"context_precision", "context_recall", "answer_correctness"}


# ══════════════════════════════════════════════════════════════════════════════
#  LLM / EMBEDDINGS SETUP
# ══════════════════════════════════════════════════════════════════════════════

def _build_ragas_llm():
    """
    Wrap the project's Gemini model with LangchainLLMWrapper so RAGAS
    can use it as the evaluator LLM — no OpenAI key required.
    """
    from app.core.config import google_api_key
    from langchain_google_genai import ChatGoogleGenerativeAI
    from ragas.llms import LangchainLLMWrapper

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.1,   # Low temp for consistent evaluation judgements
        google_api_key=google_api_key or "DUMMY_KEY",
        transport="rest",
    )
    return LangchainLLMWrapper(llm)


def _build_ragas_embeddings():
    """
    Wrap Google embeddings with LangchainEmbeddingsWrapper for RAGAS metrics
    that need semantic similarity (e.g., AnswerRelevancy).
    """
    from app.core.config import google_api_key
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-2-preview",
        google_api_key=google_api_key or "DUMMY_KEY",
        transport="rest",
    )
    return LangchainEmbeddingsWrapper(embeddings)


# ══════════════════════════════════════════════════════════════════════════════
#  CORE EVALUATOR
# ══════════════════════════════════════════════════════════════════════════════

def run_ragas_evaluation(
    dataset: "datasets.Dataset",
    metrics: Optional[list] = None,
    output_csv: str = "evaluation_results_ragas.csv",
    run_per_role: bool = True,
) -> dict:
    """
    Run RAGAS evaluation on the provided dataset.

    Args:
        dataset:      HuggingFace Dataset with user_input/response/
                      retrieved_contexts/reference/role columns.
        metrics:      List of RAGAS metric instances. Defaults to all 5 metrics.
        output_csv:   Path to save full results CSV.
        run_per_role: If True, also compute per-role aggregate scores.

    Returns:
        dict with keys:
          "overall"    → {metric_name: score, ...}
          "per_role"   → {role: {metric_name: score, ...}, ...}
          "pass_fail"  → {metric_name: "PASS"|"WARN"|"FAIL", ...}
          "dataframe"  → pd.DataFrame of per-sample scores
          "csv_path"   → path to saved CSV
    """
    from ragas import evaluate
    # RAGAS 0.4+: LLMContextRecall and AnswerCorrectness moved to ragas.metrics.collections
    try:
        from ragas.metrics.collections import LLMContextRecall, AnswerCorrectness
    except ImportError:
        from ragas.metrics import LLMContextRecall, AnswerCorrectness  # type: ignore[no-redef]
    from ragas.metrics import (
        Faithfulness,
        AnswerRelevancy,
        ContextPrecision,
    )

    # ── Build evaluator LLM and embeddings ─────────────────────────────────────
    logger.info("[RAGAS] Initialising Gemini evaluator LLM and embeddings…")
    ragas_llm   = _build_ragas_llm()
    ragas_embs  = _build_ragas_embeddings()

    # ── Configure metrics with Gemini ──────────────────────────────────────────
    if metrics is None:
        metrics = [
            Faithfulness(llm=ragas_llm),
            AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embs),
            ContextPrecision(llm=ragas_llm),
            LLMContextRecall(llm=ragas_llm),
            AnswerCorrectness(llm=ragas_llm, embeddings=ragas_embs),
        ]

    logger.info(f"[RAGAS] Running evaluation on {len(dataset)} samples "
                f"with {len(metrics)} metrics…")

    # ── Run full evaluation (suppress deprecation — evaluate() still functional) ─
    import warnings as _w
    with _w.catch_warnings():
        _w.filterwarnings("ignore", category=DeprecationWarning, module="ragas")
        result = evaluate(dataset=dataset, metrics=metrics)
    df     = result.to_pandas()

    # ── Save to CSV ────────────────────────────────────────────────────────────
    out_path = Path(__file__).parent / output_csv
    # Re-attach role column if present in original dataset
    if "role" in dataset.column_names and "role" not in df.columns:
        df["role"] = dataset["role"]
    df.to_csv(out_path, index=False)
    logger.info(f"[RAGAS] Results saved to {out_path}")

    # ── Compute overall scores ─────────────────────────────────────────────────
    metric_cols = [c for c in df.columns if c in {
        "faithfulness", "answer_relevancy", "context_precision",
        "context_recall", "answer_correctness"
    }]
    overall = {col: round(float(df[col].mean(skipna=True)), 4) for col in metric_cols}
    logger.info(f"[RAGAS] Overall scores: {overall}")

    # ── Compute per-role scores ────────────────────────────────────────────────
    per_role: dict[str, dict] = {}
    if run_per_role and "role" in df.columns:
        for role, group in df.groupby("role"):
            per_role[str(role)] = {
                col: round(float(group[col].mean(skipna=True)), 4)
                for col in metric_cols
            }
        logger.info(f"[RAGAS] Per-role scores computed for: {list(per_role.keys())}")

    # ── Pass/Fail/Warn gates ───────────────────────────────────────────────────
    pass_fail = _apply_thresholds(overall)
    logger.info(f"[RAGAS] Pass/Fail: {pass_fail}")

    return {
        "overall":   overall,
        "per_role":  per_role,
        "pass_fail": pass_fail,
        "dataframe": df,
        "csv_path":  str(out_path),
    }


def _apply_thresholds(scores: dict[str, float]) -> dict[str, str]:
    """
    Apply production thresholds to each metric score.
    Returns dict of metric → "PASS" | "WARN" | "FAIL"
    """
    result = {}
    for metric, score in scores.items():
        if metric not in THRESHOLDS:
            result[metric] = "PASS"
            continue
        t = THRESHOLDS[metric]
        if score >= t["warn"]:
            result[metric] = "PASS"
        elif score >= t["pass"]:
            result[metric] = "WARN"
        else:
            result[metric] = "FAIL"
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  CONVENIENCE: QUICK EVALUATION (no ground truth needed)
# ══════════════════════════════════════════════════════════════════════════════

def run_quick_evaluation(
    dataset: "datasets.Dataset",
    output_csv: str = "evaluation_results_ragas_quick.csv",
) -> dict:
    """
    Run evaluation using only reference-free metrics (Faithfulness + AnswerRelevancy).
    Useful when ground truth is not available, or for a fast smoke test.
    """
    from ragas.metrics import Faithfulness, AnswerRelevancy
    ragas_llm  = _build_ragas_llm()
    ragas_embs = _build_ragas_embeddings()

    metrics = [
        Faithfulness(llm=ragas_llm),
        AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embs),
    ]

    return run_ragas_evaluation(
        dataset=dataset,
        metrics=metrics,
        output_csv=output_csv,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  CONVENIENCE: FULL PIPELINE (dataset building + evaluation)
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_from_csv(
    csv_path: Optional[str] = None,
    roles: Optional[list[str]] = None,
    max_per_role: int = 15,
    output_csv: str = "evaluation_results_ragas.csv",
) -> dict:
    """
    End-to-end evaluation: load CSV → build RAGAS Dataset → run evaluation.
    This is the main entry point for production runs.
    """
    from app.rag_evaluator.eval_dataset import load_ragas_dataset_from_csv

    logger.info("[RAGAS] Building evaluation dataset from CSV…")
    dataset = load_ragas_dataset_from_csv(
        csv_path=csv_path,
        roles_filter=roles,
        max_per_role=max_per_role,
    )

    return run_ragas_evaluation(dataset=dataset, output_csv=output_csv)


def evaluate_from_builtin(
    roles: Optional[list[str]] = None,
    output_csv: str = "evaluation_results_ragas_builtin.csv",
) -> dict:
    """
    End-to-end evaluation using the built-in curated QA pairs.
    Useful for CI/CD or when no CSV is available.
    """
    from app.rag_evaluator.eval_dataset import load_builtin_dataset_with_rag

    logger.info("[RAGAS] Building evaluation dataset from builtin QA pairs…")
    dataset = load_builtin_dataset_with_rag(roles=roles)

    return run_ragas_evaluation(dataset=dataset, output_csv=output_csv)


# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY PRINTER
# ══════════════════════════════════════════════════════════════════════════════

def print_evaluation_summary(results: dict) -> None:
    """Pretty-print evaluation summary to console."""
    print("\n" + "═" * 60)
    print("  RAGAS EVALUATION SUMMARY — FinSight RBAC RAG Chatbot")
    print("═" * 60)

    print("\n  📊 OVERALL SCORES:")
    for metric, score in results["overall"].items():
        status = results["pass_fail"].get(metric, "N/A")
        icon   = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}.get(status, "ℹ️ ")
        bar    = "█" * int(score * 20) + "░" * (20 - int(score * 20))
        print(f"    {icon} {metric:<22} {bar} {score:.4f}  [{status}]")

    if results.get("per_role"):
        print("\n  🏷️  PER-ROLE SCORES:")
        all_metrics = list(results["overall"].keys())
        header = f"    {'Role':<15}" + "".join(f"{m[:8]:<10}" for m in all_metrics)
        print(header)
        print("    " + "-" * (15 + 10 * len(all_metrics)))
        for role, scores in sorted(results["per_role"].items()):
            row = f"    {role:<15}"
            for m in all_metrics:
                row += f"{scores.get(m, 0.0):<10.4f}"
            print(row)

    overall_status = "PASS" if all(v != "FAIL" for v in results["pass_fail"].values()) else "FAIL"
    print(f"\n  🏁 OVERALL STATUS: {'✅ PASS' if overall_status == 'PASS' else '❌ FAIL'}")
    print(f"  📄 Results saved to: {results['csv_path']}")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    logger.info("Running quick builtin evaluation…")
    results = evaluate_from_builtin(roles=["finance", "hr"])
    print_evaluation_summary(results)
