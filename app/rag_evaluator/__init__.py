"""
app/rag_evaluator/__init__.py
──────────────────────────────
RAGAS Evaluation Package for FinSight RBAC RAG Chatbot.

Public API:
  from app.rag_evaluator.ragas_evaluator import (
      run_ragas_evaluation,
      evaluate_from_csv,
      evaluate_from_builtin,
      print_evaluation_summary,
  )

  from app.rag_evaluator.rbac_security_eval import run_all_security_tests

  from app.rag_evaluator.eval_report import generate_html_report
  from app.rag_evaluator.eval_dataset import (
      load_ragas_dataset_from_csv,
      load_builtin_dataset_with_rag,
      generate_ragas_dataset,
  )
"""
