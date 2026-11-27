"""
app/rag/chain.py — High-level async ask_rag() helper.
"""

from __future__ import annotations

from .module import get_rag_chain

_NOT_FOUND_SIGNAL = "could not find relevant information"


async def ask_rag(question: str, role: str, cohere_api_key: str | None = None) -> dict:
    """
    Invoke the RAG chain asynchronously and return the answer + source documents.
    Access control (cross-department denial) is enforced BEFORE calling this helper.
    """
    try:
        chain = get_rag_chain(user_role=role, cohere_api_key=cohere_api_key)
        result = await chain.ainvoke({"input": question})

        answer = (result.get("answer") or "").strip()
        if not answer:
            answer = (
                "I could not find relevant information about this topic "
                "in your accessible documents."
            )

        sources: list[str] = []
        for doc in result.get("context") or []:
            src = doc.metadata.get("source")
            if src and src not in sources:
                sources.append(src)

        if _NOT_FOUND_SIGNAL in answer.lower():
            sources = []

        return {"answer": answer, "sources": sources}

    except Exception as exc:
        err = str(exc).lower()
        if "429" in err or "resource exhausted" in err:
            answer = (
                "⚠️ **API Quota Limit Reached** — The AI service is temporarily "
                "rate-limited. Please try again in a moment."
            )
        elif "404" in err or "not found" in err:
            answer = (
                "⚠️ **Service Temporarily Unavailable** — The AI model is "
                "currently unavailable. Please try again shortly."
            )
        else:
            answer = (
                "⚠️ **Retrieval Error** — An unexpected error occurred while "
                "processing your request. Please try again."
            )
        return {"answer": answer, "sources": []}
