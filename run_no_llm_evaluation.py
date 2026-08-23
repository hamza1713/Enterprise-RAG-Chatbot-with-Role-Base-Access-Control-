"""
run_no_llm_evaluation.py
─────────────────────────
Runs the COMPLETE FinSight evaluation WITHOUT any LLM-as-judge calls.
Zero Gemini API quota used by the scorer (only the embedding model).

What it does:
  1. Uses the pre-built evaluation_results_ragas_quick.csv (already has
     retrieved_contexts + responses from the live RAG pipeline)
  2. Scores each sample with embedding-based + statistical metrics
  3. Runs all 6 RBAC security tests (no LLM needed there)
  4. Generates the HTML report
  5. Updates last_eval_status.json

Run from project root:
    python run_no_llm_evaluation.py
"""

import sys, os, json, logging
from pathlib import Path
from datetime import datetime, timezone

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Path setup ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

# Normalize API keys (suppress duplicate-key warning from google-genai)
if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
os.environ.pop("GEMINI_API_KEY", None)
os.environ["ANONYMIZED_TELEMETRY"] = "False"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("FinSight.RunEval")

EVAL_DIR    = PROJECT_ROOT / "app" / "rag_evaluator"
STATUS_JSON = EVAL_DIR / "last_eval_status.json"
REPORT_HTML = EVAL_DIR / "ragas_report.html"
INPUT_CSV   = EVAL_DIR / "evaluation_results_ragas_quick.csv"

started_at = datetime.now(timezone.utc).isoformat()
STATUS_JSON.write_text(json.dumps({
    "status": "running", "started_at": started_at, "error": None,
}, indent=2))

print("\n" + "=" * 65)
print("  FinSight No-LLM Evaluation (Embedding + Statistical Metrics)")
print("=" * 65 + "\n")

# ── STEP 1: Check API key (only used by embedding model) ─────────────────────
api_key = os.environ.get("GOOGLE_API_KEY", "")
if not api_key:
    print("ERROR: GOOGLE_API_KEY not set. Needed for the embedding model.")
    sys.exit(1)
print(f"[Step 1] API key found: {api_key[:10]}...")

# ── STEP 2: Check if pre-built CSV exists ────────────────────────────────────
print(f"\n[Step 2] Checking for pre-built evaluation CSV...")
if not INPUT_CSV.exists():
    print(f"  Pre-built CSV not found at {INPUT_CSV}")
    print("  Building it now from the live RAG pipeline (no LLM scorer)...")
    try:
        from app.rag_evaluator.eval_dataset import load_builtin_dataset_with_rag
        dataset = load_builtin_dataset_with_rag(
            roles=["finance", "hr", "engineering", "marketing"],
            sleep_between_calls=0.5,
        )
        import pandas as pd
        rows = [{
            "user_input":         r["user_input"],
            "retrieved_contexts": str(r["retrieved_contexts"]),
            "response":           r["response"],
            "reference":          r.get("reference", ""),
            "role":               r.get("role", ""),
        } for r in dataset]
        pd.DataFrame(rows).to_csv(INPUT_CSV, index=False)
        print(f"  Built and saved {len(rows)} samples.")
    except Exception as e:
        print(f"  ERROR building dataset: {e}")
        sys.exit(1)
else:
    import pandas as pd
    n = len(pd.read_csv(INPUT_CSV))
    print(f"  Found pre-built CSV with {n} samples. Reusing it.")
    print("  (Skip dataset rebuild — saves all API quota!)")

# ── STEP 3: Run No-LLM Evaluation ────────────────────────────────────────────
print("\n[Step 3] Running quota-free evaluation (embedding + statistical)...")
print("  Metrics: context_recall | answer_relevancy | context_precision")
print("           faithfulness_token | answer_similarity")
print("  No LLM calls — only embedding similarity + token overlap\n")

eval_results = None
try:
    from app.rag_evaluator.no_llm_evaluator import run_no_llm_evaluation
    eval_results = run_no_llm_evaluation(
        csv_path=str(INPUT_CSV),
        output_csv="evaluation_results_no_llm.csv",
        sleep_between_samples=0.3,
    )

    print("\n  EVALUATION SCORES (No LLM-as-judge):")
    print("  " + "-" * 55)
    for metric, score in eval_results["overall"].items():
        status = eval_results["pass_fail"].get(metric, "N/A")
        icon = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}.get(status, "[?]")
        bar_len = int(score * 20) if score == score else 0  # NaN check
        bar = "#" * bar_len + "-" * (20 - bar_len)
        print(f"  {icon} {metric:<25} {bar} {score:.4f}")
    print("  " + "-" * 55)

    if eval_results.get("per_role"):
        print("\n  PER-ROLE BREAKDOWN:")
        all_metrics = list(eval_results["overall"].keys())
        for role, scores in sorted(eval_results["per_role"].items()):
            print(f"    {role:<15}", end="")
            for m in all_metrics:
                s = scores.get(m, float("nan"))
                print(f"  {m[:10]}: {s:.3f}", end="")
            print()

    print(f"\n  Samples evaluated: {eval_results['n_samples']}")
    n_pass = sum(1 for v in eval_results["pass_fail"].values() if v == "PASS")
    n_warn = sum(1 for v in eval_results["pass_fail"].values() if v == "WARN")
    n_fail = sum(1 for v in eval_results["pass_fail"].values() if v == "FAIL")
    overall_ok = n_fail == 0
    print(f"  Gates: {n_pass} PASS | {n_warn} WARN | {n_fail} FAIL")
    print(f"  Overall RAG Quality: {'PASS' if overall_ok else 'NEEDS IMPROVEMENT'}")

except Exception as e:
    log.error(f"No-LLM evaluation failed: {e}", exc_info=True)
    print(f"\n  ERROR: {e}")
    eval_results = None

# ── STEP 4: RBAC Security Tests (no LLM needed) ──────────────────────────────
print("\n[Step 4] Running RBAC security tests (no LLM)...")
security_report = None
try:
    from app.rag_evaluator.rbac_security_eval import run_all_security_tests
    security_report = run_all_security_tests(
        output_json="rbac_security_report.json",
        skip_ragas_test=True,   # skip Test 6 which needs LLM
    )
    summary = security_report.get("summary", {})
    print(f"  Overall: {security_report['overall_status']}")
    print(f"  {summary.get('passed',0)} passed | {summary.get('warned',0)} warned | {summary.get('failed',0)} failed")
except Exception as e:
    log.error(f"RBAC security evaluation failed: {e}", exc_info=True)
    print(f"  ERROR: {e}")
    security_report = None

# ── STEP 5: Generate HTML Report ─────────────────────────────────────────────
print("\n[Step 5] Generating HTML report...")
try:
    # Adapt results format for the report generator
    report_ragas_fmt = None
    if eval_results:
        report_ragas_fmt = {
            "overall":   eval_results["overall"],
            "per_role":  eval_results.get("per_role", {}),
            "pass_fail": eval_results["pass_fail"],
            "dataframe": None,
            "csv_path":  eval_results["csv_path"],
        }
    from app.rag_evaluator.eval_report import generate_html_report
    report_path = generate_html_report(
        ragas_results=report_ragas_fmt,
        security_report=security_report,
        output_path=str(REPORT_HTML),
    )
    print(f"  Report: {report_path}")
except Exception as e:
    print(f"  Report generation error (non-fatal): {e}")

# ── STEP 6: Save status ───────────────────────────────────────────────────────
completed_at = datetime.now(timezone.utc).isoformat()
STATUS_JSON.write_text(json.dumps({
    "status":           "completed",
    "started_at":       started_at,
    "completed_at":     completed_at,
    "evaluation_mode":  "no_llm_embedding_statistical",
    "overall":          eval_results.get("overall")  if eval_results else None,
    "per_role":         eval_results.get("per_role") if eval_results else None,
    "pass_fail":        eval_results.get("pass_fail") if eval_results else None,
    "n_samples":        eval_results.get("n_samples") if eval_results else 0,
    "rbac_overall":     security_report.get("overall_status") if security_report else None,
    "report_available": REPORT_HTML.exists(),
}, indent=2, ensure_ascii=False))

print("\n" + "=" * 65)
print("  EVALUATION COMPLETE")
print("=" * 65)
if eval_results:
    print(f"  Results CSV: {EVAL_DIR / 'evaluation_results_no_llm.csv'}")
if REPORT_HTML.exists():
    print(f"  HTML Report: {REPORT_HTML}")
print(f"  Status JSON: {STATUS_JSON}")
print()
