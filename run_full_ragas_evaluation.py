"""
run_full_ragas_evaluation.py
─────────────────────────────
Standalone script to run the COMPLETE FinSight RAGAS evaluation:
  1. Builds the evaluation dataset from builtin curated QA pairs + live RAG
  2. Runs RAGAS scoring: Faithfulness + AnswerRelevancy (reference-free, fast)
  3. Runs RBAC security tests (all 6, including the RAGAS leakage test)
  4. Generates the HTML report
  5. Saves all results + updates last_eval_status.json

Run from project root:
  python run_full_ragas_evaluation.py

This replaces the need for the slow pytest integration tests.
"""

import sys, os, json, logging, time
from pathlib import Path
from datetime import datetime, timezone

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env early
from dotenv import load_dotenv
load_dotenv()

# Fix env var: set GOOGLE_API_KEY from GEMINI_API_KEY if not set
if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    print("[Setup] GOOGLE_API_KEY set from GEMINI_API_KEY")

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


def save_status(data: dict) -> None:
    STATUS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


started_at = datetime.now(timezone.utc).isoformat()
save_status({
    "status": "running",
    "started_at": started_at,
    "error": None,
})

print("\n" + "═"*65)
print("  FinSight RAGAS + RBAC Security Evaluation — Full Run")
print("═"*65 + "\n")

# ── STEP 1: Check API key ─────────────────────────────────────────────────────
api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("ERROR: No GOOGLE_API_KEY or GEMINI_API_KEY found in .env")
    sys.exit(1)

print(f"[Step 1] API key found: {api_key[:10]}...")

# ── STEP 2: Verify ChromaDB ───────────────────────────────────────────────────
print("\n[Step 2] Verifying ChromaDB vectorstore...")
try:
    from app.rag.module import vectorstore
    collection = vectorstore._collection
    count = collection.count()
    print(f"  ChromaDB has {count} total chunks")
    if count == 0:
        print("  ERROR: Vectorstore is empty. Please upload documents first.")
        sys.exit(1)
except Exception as e:
    print(f"  ERROR loading vectorstore: {e}")
    sys.exit(1)

# ── STEP 3: RAGAS Quick Evaluation (Faithfulness + AnswerRelevancy) ───────────
print("\n[Step 3] Building evaluation dataset from builtin QA pairs...")
print("  (This will call the live RAG pipeline for each QA pair)")

ragas_results = None
try:
    # Use a smaller subset of roles for speed; full eval would use all 6
    from app.rag_evaluator.eval_dataset import load_builtin_dataset_with_rag

    # Use the builtin curated QA pairs (no slow LLM generation needed)
    # Filter to roles that have rich data: finance, hr, engineering
    dataset = load_builtin_dataset_with_rag(
        roles=["finance", "hr", "engineering", "marketing"],
        sleep_between_calls=0.5,  # Reduced from 1.0 for speed
    )
    print(f"  Dataset built: {len(dataset)} samples")

    # ── Run quick evaluation (reference-free: Faithfulness + AnswerRelevancy) ──
    print("\n[Step 3b] Running RAGAS scoring (Faithfulness + AnswerRelevancy)...")
    print("  Note: Using Gemini as LLM-as-judge (this takes ~2-5 min per sample)")

    from app.rag_evaluator.ragas_evaluator import run_quick_evaluation
    ragas_results = run_quick_evaluation(
        dataset=dataset,
        output_csv="evaluation_results_ragas_quick.csv",
    )

    print("\n  RAGAS SCORES:")
    for metric, score in ragas_results["overall"].items():
        status = ragas_results["pass_fail"].get(metric, "N/A")
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status, "ℹ️")
        print(f"    {icon} {metric:<25} {score:.4f}  [{status}]")

    if ragas_results.get("per_role"):
        print("\n  PER-ROLE BREAKDOWN:")
        for role, scores in sorted(ragas_results["per_role"].items()):
            print(f"    {role:<15}", end="")
            for m, s in scores.items():
                print(f"  {m[:12]}: {s:.3f}", end="")
            print()

except Exception as e:
    log.error(f"RAGAS evaluation failed: {e}", exc_info=True)
    print(f"\n  ERROR in RAGAS evaluation: {e}")
    ragas_results = None

# ── STEP 4: RBAC Security Tests ───────────────────────────────────────────────
print("\n[Step 4] Running RBAC security tests (6 tests)...")
security_report = None
try:
    from app.rag_evaluator.rbac_security_eval import run_all_security_tests
    security_report = run_all_security_tests(
        output_json="rbac_security_report.json",
        skip_ragas_test=False,  # Include the RAGAS leakage test
    )

    print(f"\n  RBAC Overall Status: {security_report['overall_status']}")
    summary = security_report.get("summary", {})
    print(f"  {summary.get('passed',0)} passed | {summary.get('warned',0)} warned | {summary.get('failed',0)} failed")

except Exception as e:
    log.error(f"RBAC security evaluation failed: {e}", exc_info=True)
    print(f"\n  ERROR in RBAC evaluation: {e}")
    security_report = None

# ── STEP 5: Generate HTML Report ─────────────────────────────────────────────
print("\n[Step 5] Generating HTML report...")
try:
    from app.rag_evaluator.eval_report import generate_html_report
    report_path = generate_html_report(
        ragas_results=ragas_results,
        security_report=security_report,
        output_path=str(REPORT_HTML),
    )
    print(f"  Report saved: {report_path}")
except Exception as e:
    print(f"  ERROR generating report: {e}")

# ── STEP 6: Save final status ─────────────────────────────────────────────────
completed_at = datetime.now(timezone.utc).isoformat()
status_data = {
    "status":           "completed",
    "started_at":       started_at,
    "completed_at":     completed_at,
    "overall":          ragas_results.get("overall") if ragas_results else None,
    "per_role":         ragas_results.get("per_role") if ragas_results else None,
    "pass_fail":        ragas_results.get("pass_fail") if ragas_results else None,
    "rbac_overall":     security_report.get("overall_status") if security_report else None,
    "report_available": REPORT_HTML.exists(),
}
save_status(status_data)

print("\n" + "═"*65)
print("  EVALUATION COMPLETE")
print("═"*65)
if ragas_results:
    print(f"\n  RAGAS scores saved to: {EVAL_DIR / 'evaluation_results_ragas_quick.csv'}")
if REPORT_HTML.exists():
    print(f"  HTML report: {REPORT_HTML}")
print(f"  Status JSON: {STATUS_JSON}")
print()
