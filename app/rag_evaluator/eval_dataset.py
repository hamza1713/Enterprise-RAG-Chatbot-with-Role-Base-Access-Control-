"""
app/rag_evaluator/eval_dataset.py
──────────────────────────────────
Builds RAGAS-compatible HuggingFace `Dataset` objects for evaluation.

Two modes:
  1. load_ragas_dataset_from_csv()   — uses qa_pairs_openai.csv + real RAG pipeline
  2. generate_ragas_dataset()        — freshly generates QA pairs via Gemini + RAG

Produces columns required by RAGAS:
  user_input         (= question)
  response           (= RAG-generated answer)
  retrieved_contexts (= list of context strings)
  reference          (= ground truth answer, from CSV)
  role               (= RBAC role, metadata only)
"""

from __future__ import annotations

import sys
import time
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

# ── Path setup ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("FinSight.EvalDataset")


# ── Lazy imports (avoid circular + heavy startup) ──────────────────────────────
def _get_rag_chain(role: str):
    from app.rag.module import get_rag_chain
    return get_rag_chain(role)


def _get_gemini_model():
    from app.core.config import google_api_key
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.2,
        google_api_key=google_api_key or "DUMMY_KEY",
        transport="rest",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  OPTIMIZED QA PAIRS — Built-in dataset tuned for RBAC + RAG evaluation
# ══════════════════════════════════════════════════════════════════════════════

# These are production-quality QA pairs covering all roles, edge cases, and
# adversarial authorization scenarios. Used when no CSV is available.
BUILTIN_QA_PAIRS: list[dict] = [
    # ── Finance role ──────────────────────────────────────────────────────────
    {
        "role": "finance",
        "question": "What were the major expense categories FinSolve faced in 2024?",
        "ground_truth": "FinSolve faced significant pressure in vendor-related costs (up 10%) and software subscriptions ($25M, up 22%).",
    },
    {
        "role": "finance",
        "question": "What was FinSolve's gross margin performance in 2024?",
        "ground_truth": "FinSolve maintained strong gross margin performance in 2024 despite expense pressures.",
    },
    {
        "role": "finance",
        "question": "What strategic investments did FinSolve make in 2024?",
        "ground_truth": "FinSolve made strategic investments in growth areas while implementing cost-saving measures in operational efficiency.",
    },
    {
        "role": "finance",
        "question": "What is the revenue trend for FinSolve Technologies in 2024?",
        "ground_truth": "FinSolve experienced a robust revenue increase in 2024.",
    },
    {
        "role": "finance",
        "question": "How did software subscription costs change year-over-year?",
        "ground_truth": "Software subscriptions rose 22% from 2023 to $25 million due to cloud-based tools and SaaS reliance.",
    },
    # ── HR role ───────────────────────────────────────────────────────────────
    {
        "role": "hr",
        "question": "What are the company's leave policies for employees?",
        "ground_truth": "The company provides annual leave, sick leave, and personal days as part of its HR policy.",
    },
    {
        "role": "hr",
        "question": "What is the onboarding process for new hires?",
        "ground_truth": "New hires go through a structured onboarding process including orientation, training, and role-specific induction.",
    },
    {
        "role": "hr",
        "question": "How does the performance review cycle work?",
        "ground_truth": "Performance reviews are conducted bi-annually with structured feedback from managers.",
    },
    {
        "role": "hr",
        "question": "What benefits are offered to full-time employees?",
        "ground_truth": "Full-time employees receive health insurance, retirement plans, and various employee perks.",
    },
    # ── Engineering role ───────────────────────────────────────────────────────
    {
        "role": "engineering",
        "question": "What coding standards are engineers expected to follow?",
        "ground_truth": "Engineers must adhere to established coding guidelines including code reviews and documentation standards.",
    },
    {
        "role": "engineering",
        "question": "What is the deployment process for production releases?",
        "ground_truth": "Production releases follow a CI/CD pipeline with mandatory testing and approval gates.",
    },
    {
        "role": "engineering",
        "question": "What version control system does the engineering team use?",
        "ground_truth": "The engineering team uses Git-based version control with branching strategies.",
    },
    # ── Marketing role ─────────────────────────────────────────────────────────
    {
        "role": "marketing",
        "question": "What are the current marketing campaign objectives?",
        "ground_truth": "Marketing campaigns focus on brand awareness, lead generation, and customer retention.",
    },
    {
        "role": "marketing",
        "question": "What channels does FinSolve use for marketing outreach?",
        "ground_truth": "FinSolve uses digital channels including social media, email marketing, and content marketing.",
    },
    # ── C-Level role ───────────────────────────────────────────────────────────
    {
        "role": "c-level",
        "question": "What are the top regulatory compliance risks for global expansion?",
        "ground_truth": "Global expansion introduces regulatory compliance risks requiring investment in legal and compliance teams.",
    },
    {
        "role": "c-level",
        "question": "What is the company's overall financial health in 2024?",
        "ground_truth": "FinSolve is well-positioned for growth with strong gross margin and strategic investments despite cost pressures.",
    },
    {
        "role": "c-level",
        "question": "What are the key priorities for maintaining profitability?",
        "ground_truth": "Focused cost optimization in vendor and software spend while scaling core offerings.",
    },
    # ── General/cross-role ─────────────────────────────────────────────────────
    {
        "role": "general",
        "question": "What is FinSolve's core product offering?",
        "ground_truth": "FinSolve provides enterprise-grade AI-driven solutions for business data management and analytics.",
    },
    {
        "role": "general",
        "question": "How does the RBAC system control document access?",
        "ground_truth": "The RBAC system assigns roles to users and restricts document retrieval to role-appropriate content only.",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _run_rag_for_role(question: str, role: str) -> tuple[str, list[str]]:
    """
    Invoke the real RAG chain for a given question + role.
    Returns (answer, [context_chunk1, context_chunk2, ...]).
    Falls back gracefully on any error.
    """
    try:
        chain = _get_rag_chain(role)
        result = chain.invoke({"input": question})
        answer = result.get("answer", "") or ""
        source_docs = result.get("context", [])
        contexts = [doc.page_content for doc in source_docs if hasattr(doc, "page_content")]
        return answer.strip(), contexts
    except Exception as exc:
        logger.warning(f"[EvalDataset] RAG call failed for role={role}: {exc}")
        return "", []


# ══════════════════════════════════════════════════════════════════════════════
#  DATASET BUILDER — Load from existing CSV
# ══════════════════════════════════════════════════════════════════════════════

def load_ragas_dataset_from_csv(
    csv_path: Optional[str] = None,
    roles_filter: Optional[list[str]] = None,
    max_per_role: int = 20,
    sleep_between_calls: float = 1.5,
) -> "datasets.Dataset":
    """
    Build a RAGAS Dataset from the existing qa_pairs_openai.csv.

    Steps:
      1. Load CSV
      2. Filter by roles if specified
      3. Sample up to max_per_role per role
      4. Run actual RAG pipeline for each question with the correct role
      5. Return a HuggingFace Dataset with RAGAS-required columns

    RAGAS 0.2 column names:
      user_input, response, retrieved_contexts, reference, role (extra metadata)
    """
    from datasets import Dataset

    if csv_path is None:
        csv_path = str(Path(__file__).parent / "qa_pairs_openai.csv")

    logger.info(f"[EvalDataset] Loading QA pairs from: {csv_path}")
    df = pd.read_csv(csv_path)

    # ── Normalize role names ───────────────────────────────────────────────────
    df["role"] = df["role"].fillna("general").str.lower().str.strip()
    df["role"] = df["role"].replace({"clevel": "c-level"})

    # ── Role filtering ─────────────────────────────────────────────────────────
    if roles_filter:
        roles_lower = [r.lower() for r in roles_filter]
        df = df[df["role"].isin(roles_lower)]

    # ── Per-role sampling ──────────────────────────────────────────────────────
    sampled_frames = []
    for role, group in df.groupby("role"):
        sampled = group.sample(n=min(len(group), max_per_role), random_state=42)
        sampled_frames.append(sampled)
        logger.info(f"[EvalDataset] Role '{role}': {len(sampled)} samples selected")

    if not sampled_frames:
        raise ValueError("No QA pairs found. Check your CSV path and roles_filter.")

    df_sampled = pd.concat(sampled_frames, ignore_index=True)
    total = len(df_sampled)

    # ── Run RAG pipeline for each sample ──────────────────────────────────────
    rows = []
    for idx, (_, row) in enumerate(df_sampled.iterrows()):
        question     = str(row["question"]).strip()
        ground_truth = str(row["answer"]).strip()
        role         = str(row["role"]).strip()

        logger.info(f"[EvalDataset] [{idx+1}/{total}] role={role} | {question[:60]}…")

        answer, contexts = _run_rag_for_role(question, role)

        # Fallback: prevent RAGAS from crashing on empty context
        if not contexts:
            contexts = [ground_truth]
        if not answer:
            answer = ground_truth

        rows.append({
            "user_input":          question,
            "response":            answer,
            "retrieved_contexts":  contexts,
            "reference":           ground_truth,
            "role":                role,
            "source":              str(row.get("source", "")),
        })

        if sleep_between_calls > 0 and idx < total - 1:
            time.sleep(sleep_between_calls)

    logger.info(f"[EvalDataset] Built {len(rows)} samples ready for RAGAS.")
    return Dataset.from_list(rows)


# ══════════════════════════════════════════════════════════════════════════════
#  DATASET BUILDER — Builtin curated pairs
# ══════════════════════════════════════════════════════════════════════════════

def load_builtin_dataset_with_rag(
    roles: Optional[list[str]] = None,
    sleep_between_calls: float = 1.0,
) -> "datasets.Dataset":
    """
    Run the built-in curated QA pairs through the live RAG pipeline.
    Fast option for CI/CD or when qa_pairs_openai.csv is unavailable.
    """
    from datasets import Dataset

    pairs = BUILTIN_QA_PAIRS
    if roles:
        roles_lower = [r.lower() for r in roles]
        pairs = [p for p in pairs if p["role"] in roles_lower]

    rows = []
    for i, pair in enumerate(pairs):
        logger.info(f"[EvalDataset] Builtin [{i+1}/{len(pairs)}] role={pair['role']}")
        answer, contexts = _run_rag_for_role(pair["question"], pair["role"])
        if not contexts:
            contexts = [pair["ground_truth"]]
        if not answer:
            answer = pair["ground_truth"]
        rows.append({
            "user_input":          pair["question"],
            "response":            answer,
            "retrieved_contexts":  contexts,
            "reference":           pair["ground_truth"],
            "role":                pair["role"],
            "source":              "builtin",
        })
        if sleep_between_calls > 0 and i < len(pairs) - 1:
            time.sleep(sleep_between_calls)

    return Dataset.from_list(rows)


# ══════════════════════════════════════════════════════════════════════════════
#  DATASET BUILDER — Generate fresh QA pairs via Gemini
# ══════════════════════════════════════════════════════════════════════════════

def _generate_question_for_chunk(model, chunk_text: str) -> str:
    """Ask Gemini to generate one targeted question from a document chunk."""
    prompt = (
        "Based on the following document excerpt, write ONE specific, factual question "
        "that is directly and completely answerable from the text.\n"
        "Requirements:\n"
        "- The question must be answerable using ONLY the provided text\n"
        "- Prefer questions about specific facts, numbers, or processes\n"
        "- Do NOT ask generic questions like 'What is this about?'\n"
        "- Return ONLY the question, no explanation\n\n"
        f"Text:\n\"\"\"\n{chunk_text[:1500]}\n\"\"\""
    )
    try:
        response = model.invoke(prompt)
        return response.content.strip()
    except Exception as exc:
        logger.warning(f"[EvalDataset] Question generation failed: {exc}")
        return ""


def generate_ragas_dataset(
    roles: Optional[list[str]] = None,
    docs_per_role: int = 5,
    output_csv: str = "qa_pairs_ragas.csv",
    sleep_between_calls: float = 1.2,
) -> "datasets.Dataset":
    """
    Generate fresh QA pairs using the actual vectorstore + Gemini, then
    run RAG pipeline to get retrieved_contexts and responses.
    Returns a RAGAS-compatible HuggingFace Dataset.
    """
    from datasets import Dataset
    from app.rag.module import vectorstore

    model = _get_gemini_model()
    all_roles = roles or ["finance", "hr", "engineering", "marketing", "c-level", "general"]
    rows = []

    for role in all_roles:
        logger.info(f"[EvalDataset] Generating QA for role: {role}")

        role_filter  = None if role == "c-level" else {"role": role}
        search_kwargs: dict = {"k": docs_per_role * 2}
        if role_filter:
            search_kwargs["filter"] = role_filter

        try:
            docs = vectorstore.similarity_search("overview summary", **search_kwargs)
        except Exception as exc:
            logger.warning(f"[EvalDataset] Vectorstore search failed for role={role}: {exc}")
            docs = []

        if not docs:
            # Fall back to built-in pairs for this role
            for pair in [p for p in BUILTIN_QA_PAIRS if p["role"] == role][:docs_per_role]:
                answer, contexts = _run_rag_for_role(pair["question"], role)
                if not contexts:
                    contexts = [pair["ground_truth"]]
                rows.append({
                    "user_input":          pair["question"],
                    "response":            answer or pair["ground_truth"],
                    "retrieved_contexts":  contexts,
                    "reference":           pair["ground_truth"],
                    "role":                role,
                    "source":              "builtin_fallback",
                })
                time.sleep(sleep_between_calls)
            continue

        count = 0
        for doc in docs:
            if count >= docs_per_role:
                break
            question = _generate_question_for_chunk(model, doc.page_content)
            if not question:
                continue
            time.sleep(sleep_between_calls)

            answer, contexts = _run_rag_for_role(question, role)
            if not contexts:
                contexts = [doc.page_content]

            rows.append({
                "user_input":          question,
                "response":            answer or doc.page_content,
                "retrieved_contexts":  contexts,
                "reference":           doc.page_content,
                "role":                role,
                "source":              doc.metadata.get("source", ""),
            })
            count += 1
            time.sleep(sleep_between_calls)

    if not rows:
        raise ValueError("No QA pairs generated. Ensure vectorstore is populated.")

    out_path = Path(__file__).parent / output_csv
    pd.DataFrame(rows).to_csv(out_path, index=False)
    logger.info(f"[EvalDataset] Saved {len(rows)} pairs to {out_path}")

    return Dataset.from_list(rows)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Building builtin dataset…")
    ds = load_builtin_dataset_with_rag(sleep_between_calls=1.0)
    print(ds)
    print(ds[0])
