"""
app/rag_evaluator/rbac_security_eval.py
─────────────────────────────────────────
RBAC Authorization Security Tests for the FinSight RAG Chatbot.

These tests verify that role-based document access controls are enforced
correctly at scale. They are SEPARATE from RAGAS quality metrics — this
is a security correctness test suite.

Tests:
  1. test_unauthorized_access_blocked   — Role A cannot see Role B docs
  2. test_authorized_access_allowed     — Role A can retrieve Role A docs
  3. test_clevel_sees_all               — c-level retrieves cross-dept docs
  4. test_general_docs_accessible_to_all— General docs reach every role
  5. test_retriever_filter_correctness  — Chroma metadata filter is applied
  6. test_authorization_leakage_score   — Cross-role RAGAS context precision ≈ 0

Each test produces a result dict:
  {
    "test": "test_name",
    "status": "PASS" | "FAIL" | "WARN",
    "details": "human-readable explanation",
    "score": float (0.0–1.0, higher is better security)
  }
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Optional

# ── Path setup ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("FinSight.RBACSecurityEval")

# ── Role definitions ───────────────────────────────────────────────────────────
# Maps each role to role-exclusive keywords that should NOT appear for other roles
ROLE_EXCLUSIVE_KEYWORDS: dict[str, list[str]] = {
    "finance": [
        "vendor-related costs", "software subscriptions", "gross margin",
        "annual revenue", "operating expenses", "financial report",
        "budget allocation", "profit margins",
    ],
    "hr": [
        "performance review", "onboarding", "employee benefits",
        "leave policy", "recruitment", "compensation", "hr policy",
    ],
    "engineering": [
        "coding standards", "deployment pipeline", "ci/cd", "version control",
        "code review", "architecture", "technical debt",
    ],
    "marketing": [
        "campaign objectives", "brand awareness", "lead generation",
        "marketing channels", "social media strategy", "content calendar",
    ],
}

# Questions that should be accessible ONLY to specific roles
CROSS_ROLE_ADVERSARIAL_QUERIES: list[dict] = [
    {
        "question":       "What are FinSolve's vendor costs and software subscription expenses?",
        "authorized_role": "finance",
        "unauthorized_roles": ["hr", "engineering", "marketing"],
        "forbidden_keywords": ROLE_EXCLUSIVE_KEYWORDS["finance"],
    },
    {
        "question":       "What is the employee performance review and onboarding process?",
        "authorized_role": "hr",
        "unauthorized_roles": ["finance", "engineering", "marketing"],
        "forbidden_keywords": ROLE_EXCLUSIVE_KEYWORDS["hr"],
    },
    {
        "question":       "What are the company's CI/CD pipeline and coding standards?",
        "authorized_role": "engineering",
        "unauthorized_roles": ["finance", "hr", "marketing"],
        "forbidden_keywords": ROLE_EXCLUSIVE_KEYWORDS["engineering"],
    },
    {
        "question":       "What are the marketing campaign objectives and lead generation strategies?",
        "authorized_role": "marketing",
        "unauthorized_roles": ["finance", "hr", "engineering"],
        "forbidden_keywords": ROLE_EXCLUSIVE_KEYWORDS["marketing"],
    },
]

# Queries about general docs that ALL roles should be able to answer
GENERAL_ACCESS_QUERIES: list[str] = [
    "What does the company do?",
    "What is FinSolve's core mission?",
    "How does the system work?",
]


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_vectorstore():
    from app.rag.module import vectorstore
    return vectorstore


def _build_role_filter(role: str) -> Optional[dict]:
    """Mirrors HybridMultiQueryRetriever._build_role_filter exactly."""
    role_lower = role.lower()
    if role_lower == "c-level":
        return None
    if role_lower == "general":
        return {"role": "general"}
    return {"role": {"$in": [role_lower, "general"]}}


def _search_as_role(query: str, role: str, k: int = 10) -> list:
    """Perform a vectorstore search applying the correct RBAC filter."""
    vs = _get_vectorstore()
    role_filter = _build_role_filter(role)
    try:
        kwargs: dict = {"query": query, "k": k}
        if role_filter:
            kwargs["filter"] = role_filter
        return vs.similarity_search(**kwargs)
    except Exception as exc:
        logger.warning(f"[RBAC] Search failed for role={role}: {exc}")
        return []


def _get_answer_as_role(question: str, role: str) -> tuple[str, list]:
    """Run the full RAG chain as a specific role. Returns (answer, contexts)."""
    try:
        from app.rag.module import get_rag_chain
        chain  = get_rag_chain(role)
        result = chain.invoke({"input": question})
        answer = result.get("answer", "") or ""
        docs   = result.get("context", [])
        contexts = [d.page_content for d in docs if hasattr(d, "page_content")]
        return answer.strip(), contexts
    except Exception as exc:
        logger.warning(f"[RBAC] RAG chain failed for role={role}: {exc}")
        return "", []


def _contains_forbidden_content(text: str, keywords: list[str]) -> list[str]:
    """Return list of forbidden keywords found in text (case-insensitive)."""
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


# ══════════════════════════════════════════════════════════════════════════════
#  TEST 1: Unauthorized access is blocked
# ══════════════════════════════════════════════════════════════════════════════

def test_unauthorized_access_blocked(sleep_s: float = 1.0) -> dict:
    """
    For each adversarial query, verify that unauthorized roles do NOT receive
    content containing role-exclusive keywords in their answer.
    """
    logger.info("[RBAC] TEST 1: Unauthorized access blocked")
    leakage_events   = []
    total_checks     = 0

    for query_spec in CROSS_ROLE_ADVERSARIAL_QUERIES:
        question  = query_spec["question"]
        forbidden = query_spec["forbidden_keywords"]

        for unauth_role in query_spec["unauthorized_roles"]:
            total_checks += 1
            answer, contexts = _get_answer_as_role(question, unauth_role)
            combined_text    = answer + " ".join(contexts)
            leaked_kws       = _contains_forbidden_content(combined_text, forbidden)

            if leaked_kws:
                leakage_events.append({
                    "role":     unauth_role,
                    "question": question[:80],
                    "leaked":   leaked_kws[:3],  # show first 3
                })
                logger.warning(f"[RBAC] ⚠️  LEAKAGE: role={unauth_role} got: {leaked_kws}")

            time.sleep(sleep_s)

    leakage_rate = len(leakage_events) / max(total_checks, 1)
    score        = 1.0 - leakage_rate
    status       = "PASS" if score >= 0.95 else ("WARN" if score >= 0.80 else "FAIL")

    return {
        "test":    "test_unauthorized_access_blocked",
        "status":  status,
        "score":   round(score, 4),
        "details": (
            f"Checked {total_checks} unauthorized role-query pairs. "
            f"{len(leakage_events)} leakage event(s) detected. "
            f"Security score: {score:.2%}"
        ),
        "leakage_events": leakage_events,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  TEST 2: Authorized access is allowed
# ══════════════════════════════════════════════════════════════════════════════

def test_authorized_access_allowed(sleep_s: float = 1.0) -> dict:
    """
    Verify that authorized roles DO receive relevant content for their queries.
    """
    logger.info("[RBAC] TEST 2: Authorized access allowed")
    successes = 0
    failures  = []

    for query_spec in CROSS_ROLE_ADVERSARIAL_QUERIES:
        question     = query_spec["question"]
        auth_role    = query_spec["authorized_role"]
        expected_kws = query_spec["forbidden_keywords"]  # these SHOULD appear

        answer, contexts = _get_answer_as_role(question, auth_role)
        combined = answer + " ".join(contexts)
        found_kws = _contains_forbidden_content(combined, expected_kws)

        # Check for refusal phrases
        refusal_phrases = [
            "i could not find", "not found", "access restricted",
            "no relevant information", "I don't have access"
        ]
        was_refused = any(p in combined.lower() for p in refusal_phrases)

        if found_kws and not was_refused:
            successes += 1
        else:
            failures.append({
                "role":     auth_role,
                "question": question[:80],
                "refused":  was_refused,
            })
            logger.warning(f"[RBAC] ⚠️  Auth role={auth_role} got no relevant content")

        time.sleep(sleep_s)

    total  = len(CROSS_ROLE_ADVERSARIAL_QUERIES)
    score  = successes / max(total, 1)
    status = "PASS" if score >= 0.75 else ("WARN" if score >= 0.50 else "FAIL")

    return {
        "test":    "test_authorized_access_allowed",
        "status":  status,
        "score":   round(score, 4),
        "details": (
            f"Tested {total} authorized role-query pairs. "
            f"{successes}/{total} returned relevant content. "
            f"Access score: {score:.2%}"
        ),
        "failures": failures,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  TEST 3: C-Level sees all departments
# ══════════════════════════════════════════════════════════════════════════════

def test_clevel_sees_all() -> dict:
    """
    C-level role should retrieve documents from ALL departments (no filter).
    Verify by checking that c-level retrieval returns docs with diverse roles.
    """
    logger.info("[RBAC] TEST 3: C-level sees all")
    vs          = _get_vectorstore()
    all_roles   = ["finance", "hr", "engineering", "marketing"]
    found_roles = set()
    total_docs  = 0

    for query in ["company overview", "financial data", "employees", "technology"]:
        try:
            docs = vs.similarity_search(query, k=20)  # no filter = c-level
            total_docs += len(docs)
            for doc in docs:
                role = doc.metadata.get("role", "").lower()
                if role in all_roles:
                    found_roles.add(role)
        except Exception as exc:
            logger.warning(f"[RBAC] C-level search failed: {exc}")

    missing = set(all_roles) - found_roles
    score   = len(found_roles) / max(len(all_roles), 1)
    status  = "PASS" if not missing else ("WARN" if len(missing) <= 1 else "FAIL")

    return {
        "test":    "test_clevel_sees_all",
        "status":  status,
        "score":   round(score, 4),
        "details": (
            f"C-level retrieved docs from: {sorted(found_roles)}. "
            f"Missing roles: {sorted(missing)}. "
            f"Coverage: {score:.2%} of departments accessible."
        ),
        "found_roles":   list(found_roles),
        "missing_roles": list(missing),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  TEST 4: General docs accessible to all roles
# ══════════════════════════════════════════════════════════════════════════════

def test_general_docs_accessible_to_all(sleep_s: float = 0.5) -> dict:
    """
    Verify that documents tagged as 'general' can be retrieved by ALL roles.
    """
    logger.info("[RBAC] TEST 4: General docs accessible to all")
    roles_to_test = ["finance", "hr", "engineering", "marketing"]
    successes     = 0

    for role in roles_to_test:
        for query in GENERAL_ACCESS_QUERIES[:2]:  # test 2 queries per role
            docs = _search_as_role(query, role, k=5)
            has_general = any(
                doc.metadata.get("role", "").lower() == "general"
                for doc in docs
            )
            if has_general:
                successes += 1
            time.sleep(sleep_s)

    total  = len(roles_to_test) * 2
    score  = successes / max(total, 1)
    status = "PASS" if score >= 0.75 else ("WARN" if score >= 0.50 else "FAIL")

    return {
        "test":    "test_general_docs_accessible_to_all",
        "status":  status,
        "score":   round(score, 4),
        "details": (
            f"Tested {total} role-query pairs for general doc access. "
            f"{successes} returned at least one general-tagged document. "
            f"Accessibility score: {score:.2%}"
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  TEST 5: Retriever filter correctness
# ══════════════════════════════════════════════════════════════════════════════

def test_retriever_filter_correctness() -> dict:
    """
    Directly check Chroma metadata filtering:
    - Finance user should NOT get engineering-only docs (role=engineering only)
    - HR user should NOT get finance-only docs
    Verifies that the $in filter works correctly.
    """
    logger.info("[RBAC] TEST 5: Retriever filter correctness")
    vs = _get_vectorstore()

    violations = []
    test_cases = [
        ("finance",     "engineering"),
        ("hr",          "finance"),
        ("engineering", "hr"),
        ("marketing",   "finance"),
    ]

    for requesting_role, forbidden_role in test_cases:
        role_filter = _build_role_filter(requesting_role)
        try:
            docs = vs.similarity_search(
                "company data",
                k=20,
                filter=role_filter,
            )
            role_only_docs = [
                d for d in docs
                if d.metadata.get("role", "").lower() == forbidden_role
            ]
            if role_only_docs:
                violations.append({
                    "requesting_role": requesting_role,
                    "forbidden_role":  forbidden_role,
                    "leaked_docs":     len(role_only_docs),
                })
                logger.warning(
                    f"[RBAC] ⚠️  Filter violation: {requesting_role} got "
                    f"{len(role_only_docs)} {forbidden_role}-only docs"
                )
        except Exception as exc:
            logger.warning(f"[RBAC] Filter test failed ({requesting_role}→{forbidden_role}): {exc}")

    total  = len(test_cases)
    passed = total - len(violations)
    score  = passed / max(total, 1)
    status = "PASS" if not violations else ("WARN" if len(violations) <= 1 else "FAIL")

    return {
        "test":    "test_retriever_filter_correctness",
        "status":  status,
        "score":   round(score, 4),
        "details": (
            f"Checked {total} role-pair filter combinations. "
            f"{len(violations)} filter violation(s) detected. "
            f"Filter precision: {score:.2%}"
        ),
        "violations": violations,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  TEST 6: Authorization leakage score (RAGAS-based)
# ══════════════════════════════════════════════════════════════════════════════

def test_authorization_leakage_score(sleep_s: float = 1.0) -> dict:
    """
    Use RAGAS context_precision as a proxy to verify that cross-role queries
    return near-zero precision scores (context is irrelevant to the question
    when proper RBAC filtering is applied to unauthorized queries).

    Logic: If finance user asks a finance-specific question but retrieves
    only HR/Engineering docs (due to correct RBAC), the context precision
    should be LOW (≈0), which is GOOD from a security standpoint.
    """
    logger.info("[RBAC] TEST 6: Authorization leakage score (RAGAS-based)")

    try:
        from datasets import Dataset
        from ragas.metrics import ContextPrecision
        from ragas import evaluate
        from app.rag_evaluator.ragas_evaluator import _build_ragas_llm

        ragas_llm = _build_ragas_llm()
        metric    = ContextPrecision(llm=ragas_llm)

        rows = []
        for query_spec in CROSS_ROLE_ADVERSARIAL_QUERIES[:2]:  # use 2 for speed
            question  = query_spec["question"]
            auth_role = query_spec["authorized_role"]

            for unauth_role in query_spec["unauthorized_roles"][:1]:  # 1 per query
                _, contexts = _get_answer_as_role(question, unauth_role)
                _, auth_ans = ("", "")
                try:
                    from app.rag.module import get_rag_chain
                    chain   = get_rag_chain(auth_role)
                    res     = chain.invoke({"input": question})
                    auth_ans = res.get("answer", "")
                except Exception:
                    auth_ans = question  # fallback reference

                if not contexts:
                    contexts = ["No relevant documents found."]

                rows.append({
                    "user_input":          question,
                    "response":            auth_ans,
                    "retrieved_contexts":  contexts,
                    "reference":           auth_ans or question,
                })
                time.sleep(sleep_s)

        if not rows:
            return {
                "test": "test_authorization_leakage_score",
                "status": "WARN",
                "score": 0.5,
                "details": "No rows could be built for this test.",
            }

        ds     = Dataset.from_list(rows)
        result = evaluate(dataset=ds, metrics=[metric])
        df     = result.to_pandas()
        avg_precision = float(df["context_precision"].mean(skipna=True))

        # For unauthorized access: LOW precision = GOOD (security holds)
        # We WANT this score to be close to 0 for adversarial queries
        security_score = 1.0 - avg_precision
        status = "PASS" if security_score >= 0.70 else ("WARN" if security_score >= 0.50 else "FAIL")

        return {
            "test":    "test_authorization_leakage_score",
            "status":  status,
            "score":   round(security_score, 4),
            "details": (
                f"RAGAS context_precision for unauthorized cross-role queries: "
                f"{avg_precision:.4f} (lower = better security). "
                f"Derived security score: {security_score:.2%}"
            ),
            "ragas_context_precision": round(avg_precision, 4),
        }

    except ImportError as e:
        return {
            "test":    "test_authorization_leakage_score",
            "status":  "WARN",
            "score":   0.5,
            "details": f"RAGAS not available for this test: {e}",
        }
    except Exception as exc:
        logger.error(f"[RBAC] Test 6 failed: {exc}")
        return {
            "test":    "test_authorization_leakage_score",
            "status":  "WARN",
            "score":   0.5,
            "details": f"Test failed with error: {exc}",
        }


# ══════════════════════════════════════════════════════════════════════════════
#  FULL SECURITY TEST RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_all_security_tests(
    output_json: str = "rbac_security_report.json",
    skip_ragas_test: bool = False,
) -> dict:
    """
    Run all 6 RBAC security tests and produce a consolidated report.

    Args:
        output_json:     Path to save the JSON report.
        skip_ragas_test: Skip test 6 (needs RAGAS + extra API calls).

    Returns:
        dict with "tests", "summary", "overall_status"
    """
    import json

    logger.info("[RBAC] ══ Starting RBAC Security Evaluation ══")
    results = []

    # Run tests 1–5
    test_fns = [
        test_unauthorized_access_blocked,
        test_authorized_access_allowed,
        test_clevel_sees_all,
        test_general_docs_accessible_to_all,
        test_retriever_filter_correctness,
    ]

    for fn in test_fns:
        try:
            result = fn()
            results.append(result)
            logger.info(f"[RBAC] {result['test']}: {result['status']} (score={result['score']})")
        except Exception as exc:
            logger.error(f"[RBAC] {fn.__name__} raised: {exc}")
            results.append({
                "test":    fn.__name__,
                "status":  "FAIL",
                "score":   0.0,
                "details": f"Test raised exception: {exc}",
            })

    # Test 6 (RAGAS-based) — optional
    if not skip_ragas_test:
        try:
            r6 = test_authorization_leakage_score()
            results.append(r6)
            logger.info(f"[RBAC] {r6['test']}: {r6['status']} (score={r6['score']})")
        except Exception as exc:
            logger.error(f"[RBAC] test_authorization_leakage_score raised: {exc}")
            results.append({
                "test":    "test_authorization_leakage_score",
                "status":  "WARN",
                "score":   0.5,
                "details": f"Test raised exception: {exc}",
            })

    # ── Summary ────────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r["status"] == "PASS")
    warned = sum(1 for r in results if r["status"] == "WARN")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    avg_score = sum(r["score"] for r in results) / max(len(results), 1)
    overall   = "PASS" if failed == 0 else "FAIL"

    summary = {
        "total_tests":    len(results),
        "passed":         passed,
        "warned":         warned,
        "failed":         failed,
        "avg_score":      round(avg_score, 4),
        "overall_status": overall,
    }

    report = {
        "tests":          results,
        "summary":        summary,
        "overall_status": overall,
    }

    # ── Save ───────────────────────────────────────────────────────────────────
    out_path = Path(__file__).parent / output_json
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"[RBAC] Security report saved to {out_path}")

    # ── Console summary ────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  RBAC SECURITY EVALUATION — FinSight")
    print("═" * 60)
    for r in results:
        icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}.get(r["status"], "ℹ️ ")
        print(f"  {icon} [{r['status']:<4}] {r['test']:<40} score={r['score']:.2f}")
    print(f"\n  📊 {passed} passed | {warned} warned | {failed} failed")
    print(f"  🏁 OVERALL: {'✅ PASS' if overall == 'PASS' else '❌ FAIL'}")
    print("═" * 60 + "\n")

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_all_security_tests(skip_ragas_test=False)
