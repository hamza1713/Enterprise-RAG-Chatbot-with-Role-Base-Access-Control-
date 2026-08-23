"""
app/rag_evaluator/no_llm_evaluator.py
────────────────────────────────────────
100% Quota-Free RAGAS-Style Evaluation — no LLM-as-judge calls.

Every metric here is computed locally using:
  • Cosine similarity on Google embeddings (the same model already used by the RAG pipeline)
  • BM25 token-overlap (no network calls at all)
  • ROUGE-L sequence matching

Metrics:
┌──────────────────────────┬────────────────────────────────────────────────────┐
│ Metric                   │ How it's computed (no LLM)                         │
├──────────────────────────┼────────────────────────────────────────────────────┤
│ context_recall           │ cos_sim(mean(context_embeds), reference_embed)     │
│ answer_relevancy         │ cos_sim(question_embed, answer_embed)               │
│ context_precision        │ BM25 score of top retrieved chunk vs question       │
│ faithfulness_token       │ % answer n-grams found in context (ROUGE-L recall) │
│ answer_similarity        │ cos_sim(answer_embed, reference_embed)              │
└──────────────────────────┴────────────────────────────────────────────────────┘

All scores are in [0, 1]. Higher = better.
"""

from __future__ import annotations

import logging
import math
import re
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("FinSight.NoLLMEval")

# ── Thresholds (same gates as LLM-based, recalibrated for embedding similarity) ─
THRESHOLDS = {
    "context_recall":    {"pass": 0.60, "warn": 0.75},
    "answer_relevancy":  {"pass": 0.65, "warn": 0.78},
    "context_precision": {"pass": 0.30, "warn": 0.50},  # BM25 range is different
    "faithfulness_token":{"pass": 0.35, "warn": 0.55},
    "answer_similarity": {"pass": 0.65, "warn": 0.80},
}


# ══════════════════════════════════════════════════════════════════════════════
#  EMBEDDING HELPER  (uses the project's existing Google embedding model)
# ══════════════════════════════════════════════════════════════════════════════

_embed_model = None

def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        try:
            from app.rag.module import google_embeddings  # the project's retrying wrapper
            _embed_model = google_embeddings
        except ImportError:
            # Fallback: build it directly from the config
            from app.core.config import google_api_key
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            _embed_model = GoogleGenerativeAIEmbeddings(
                model="models/gemini-embedding-2-preview",
                google_api_key=google_api_key,
                task_type="retrieval_query",
            )
    return _embed_model


def _embed_texts(texts: list[str], batch_size: int = 10) -> np.ndarray:
    """Embed a list of texts; returns shape (N, D)."""
    model = _get_embed_model()
    vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        embs = model.embed_documents(batch)
        vecs.extend(embs)
        if i + batch_size < len(texts):
            time.sleep(0.2)  # gentle throttle to avoid rate limits
    return np.array(vecs, dtype=np.float32)


def _embed_query(text: str) -> np.ndarray:
    model = _get_embed_model()
    return np.array(model.embed_query(text), dtype=np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ══════════════════════════════════════════════════════════════════════════════
#  BM25 HELPERS  (pure Python, no network)
# ══════════════════════════════════════════════════════════════════════════════

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text.lower())


def _bm25_score(query_tokens: list[str], doc_tokens: list[str],
                k1: float = 1.5, b: float = 0.75, avg_dl: float = 150.0) -> float:
    """Single-document BM25 score (no corpus needed — uses fixed avg_dl)."""
    dl = len(doc_tokens)
    freq: dict[str, int] = {}
    for t in doc_tokens:
        freq[t] = freq.get(t, 0) + 1
    score = 0.0
    for qt in set(query_tokens):
        tf = freq.get(qt, 0)
        if tf == 0:
            continue
        idf = math.log(2.0)  # simplified: treat each query term as moderately rare
        score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
    return score


# ══════════════════════════════════════════════════════════════════════════════
#  ROUGE-L (Longest Common Subsequence based)
# ══════════════════════════════════════════════════════════════════════════════

def _lcs_length(a: list[str], b: list[str]) -> int:
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0
    # DP — use rolling array for memory efficiency
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev = curr
    return prev[n]


def _rouge_l_recall(hypothesis: str, reference: str) -> float:
    """What fraction of reference tokens appear (in order) in hypothesis."""
    h_toks = _tokenize(hypothesis)
    r_toks = _tokenize(reference)
    if not r_toks:
        return 0.0
    lcs = _lcs_length(h_toks, r_toks)
    return lcs / len(r_toks)


# ══════════════════════════════════════════════════════════════════════════════
#  PER-SAMPLE SCORING
# ══════════════════════════════════════════════════════════════════════════════

def score_sample(
    question: str,
    answer: str,
    contexts: list[str],
    reference: Optional[str] = None,
) -> dict[str, float]:
    """
    Compute all quota-free metrics for one QA sample.
    Returns a dict of metric_name → float score ∈ [0, 1].
    """
    results: dict[str, float] = {}

    # ── 1. Answer Relevancy (embedding cosine) ────────────────────────────────
    try:
        q_emb = _embed_query(question)
        a_emb = _embed_query(answer)
        results["answer_relevancy"] = max(0.0, _cosine(q_emb, a_emb))
    except Exception as e:
        logger.warning(f"answer_relevancy failed: {e}")
        results["answer_relevancy"] = float("nan")

    # ── 2. Context Recall  (mean context cosine to reference) ─────────────────
    if reference and contexts:
        try:
            ref_emb = _embed_query(reference)
            ctx_embs = _embed_texts(contexts)
            sims = [_cosine(ce, ref_emb) for ce in ctx_embs]
            results["context_recall"] = float(np.mean(sims))
        except Exception as e:
            logger.warning(f"context_recall failed: {e}")
            results["context_recall"] = float("nan")
    else:
        results["context_recall"] = float("nan")

    # ── 3. Context Precision (BM25 — best chunk vs question) ──────────────────
    if contexts:
        try:
            q_toks = _tokenize(question)
            scores = [_bm25_score(q_toks, _tokenize(c)) for c in contexts]
            best_bm25 = max(scores)
            # Normalize to [0, 1] via sigmoid-like transform (range ~0-20)
            results["context_precision"] = float(1 / (1 + math.exp(-0.3 * (best_bm25 - 3))))
        except Exception as e:
            logger.warning(f"context_precision failed: {e}")
            results["context_precision"] = float("nan")
    else:
        results["context_precision"] = 0.0

    # ── 4. Faithfulness (token overlap: answer n-grams in context) ────────────
    if contexts:
        try:
            full_context = " ".join(contexts)
            results["faithfulness_token"] = _rouge_l_recall(full_context, answer)
        except Exception as e:
            logger.warning(f"faithfulness_token failed: {e}")
            results["faithfulness_token"] = float("nan")
    else:
        results["faithfulness_token"] = 0.0

    # ── 5. Answer Similarity (embedding cosine to reference) ──────────────────
    if reference:
        try:
            ref_emb2 = _embed_query(reference)
            a_emb2 = _embed_query(answer)
            results["answer_similarity"] = max(0.0, _cosine(a_emb2, ref_emb2))
        except Exception as e:
            logger.warning(f"answer_similarity failed: {e}")
            results["answer_similarity"] = float("nan")
    else:
        results["answer_similarity"] = float("nan")

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  BATCH EVALUATION — reads the already-built CSV (no re-running RAG)
# ══════════════════════════════════════════════════════════════════════════════

def run_no_llm_evaluation(
    csv_path: Optional[str] = None,
    output_csv: str = "evaluation_results_no_llm.csv",
    sleep_between_samples: float = 0.3,
) -> dict:
    """
    Full evaluation using the already-built evaluation CSV.
    No LLM calls — only embedding API + local computation.

    Args:
        csv_path:  path to input CSV (defaults to evaluation_results_ragas_quick.csv)
        output_csv: where to save per-sample scores
        sleep_between_samples: seconds to sleep between samples (avoid embed rate limits)

    Returns:
        {
          "overall":  {metric: score, ...},
          "per_role": {role: {metric: score, ...}, ...},
          "pass_fail":{metric: "PASS"|"WARN"|"FAIL", ...},
          "csv_path": str,
          "n_samples": int,
        }
    """
    EVAL_DIR = Path(__file__).parent

    if csv_path is None:
        # Use the pre-built evaluation CSV which already has retrieved_contexts + response
        csv_path = str(EVAL_DIR / "evaluation_results_ragas_quick.csv")

    logger.info(f"[NoLLMEval] Loading dataset from {csv_path}")
    df = pd.read_csv(csv_path)

    # Normalise column names
    col_map = {
        "user_input": "question",
        "response": "answer",
        "reference": "reference",
        "retrieved_contexts": "contexts",
        "role": "role",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    required = {"question", "answer", "contexts"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    logger.info(f"[NoLLMEval] Scoring {len(df)} samples (no LLM calls)...")

    rows = []
    for idx, row in df.iterrows():
        question  = str(row.get("question", ""))
        answer    = str(row.get("answer", ""))
        reference = str(row.get("reference", "")) if pd.notna(row.get("reference")) else None
        role      = str(row.get("role", "unknown"))

        # Parse contexts — stored as string repr of list in CSV
        raw_ctx = row.get("contexts", "[]")
        if isinstance(raw_ctx, str):
            try:
                import ast
                contexts = ast.literal_eval(raw_ctx)
            except Exception:
                contexts = [raw_ctx]
        else:
            contexts = list(raw_ctx) if raw_ctx else []

        logger.info(f"[NoLLMEval] Sample {idx+1}/{len(df)} (role={role})")

        scores = score_sample(question=question, answer=answer,
                              contexts=contexts, reference=reference)
        scores["role"] = role
        scores["question"] = question[:120]
        rows.append(scores)

        if sleep_between_samples > 0 and idx < len(df) - 1:
            time.sleep(sleep_between_samples)

    result_df = pd.DataFrame(rows)

    # ── Overall scores ─────────────────────────────────────────────────────────
    metric_cols = [c for c in result_df.columns
                   if c not in ("role", "question")]
    overall = {m: float(result_df[m].mean(skipna=True)) for m in metric_cols}

    # ── Per-role scores ────────────────────────────────────────────────────────
    per_role: dict = {}
    if "role" in result_df.columns:
        for role, grp in result_df.groupby("role"):
            per_role[str(role)] = {m: float(grp[m].mean(skipna=True))
                                   for m in metric_cols}

    # ── Pass/Fail gates ────────────────────────────────────────────────────────
    pass_fail: dict = {}
    for m, score in overall.items():
        if math.isnan(score):
            pass_fail[m] = "FAIL"
        elif m in THRESHOLDS:
            t = THRESHOLDS[m]
            if score >= t["warn"]:
                pass_fail[m] = "PASS"
            elif score >= t["pass"]:
                pass_fail[m] = "WARN"
            else:
                pass_fail[m] = "FAIL"
        else:
            pass_fail[m] = "PASS" if score >= 0.60 else "WARN"

    # ── Save ───────────────────────────────────────────────────────────────────
    out_path = EVAL_DIR / output_csv
    result_df.to_csv(out_path, index=False)
    logger.info(f"[NoLLMEval] Results saved → {out_path}")

    return {
        "overall":   overall,
        "per_role":  per_role,
        "pass_fail": pass_fail,
        "csv_path":  str(out_path),
        "n_samples": len(result_df),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  THRESHOLD HELPER (reused by tests)
# ══════════════════════════════════════════════════════════════════════════════

def _apply_thresholds(scores: dict) -> dict:
    """Return PASS/WARN/FAIL for each metric."""
    result = {}
    for m, score in scores.items():
        if math.isnan(score):
            result[m] = "FAIL"
        elif m in THRESHOLDS:
            t = THRESHOLDS[m]
            if score >= t["warn"]:
                result[m] = "PASS"
            elif score >= t["pass"]:
                result[m] = "WARN"
            else:
                result[m] = "FAIL"
        else:
            result[m] = "PASS" if score >= 0.60 else "WARN"
    return result
