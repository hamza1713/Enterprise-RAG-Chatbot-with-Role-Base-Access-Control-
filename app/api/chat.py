"""
app/api/chat.py — Chat endpoints (non-streaming & streaming).

Handles:
  POST /chat          — standard JSON response
  POST /chat-stream   — NDJSON streaming response
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.rag.classifier import detect_query_type_llm, is_conversational_query
from app.rag.csv_query import ask_csv
from app.rag.chain import ask_rag
from app.rag.module import get_rag_chain
from .auth import get_current_user

logger = logging.getLogger("FinSight.chat")
router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    question: str


# ════════════════════════════════════════════════════════════════════════════════
#  Role-based access guard
# ════════════════════════════════════════════════════════════════════════════════

# Maps specific compound phrases (most-to-least specific) to a department.
# Priority ordering prevents "marketing budget" from blocking Finance users.
_DEPT_PHRASES: list[tuple[str, str]] = [
    # HR
    ("hr department",       "hr"),  ("hr report",           "hr"),
    ("hr data",             "hr"),  ("hr document",         "hr"),
    ("hr file",             "hr"),  ("human resource",      "hr"),
    ("employee record",     "hr"),  ("payroll",             "hr"),
    ("recruitment",         "hr"),  ("onboarding",          "hr"),
    ("offboarding",         "hr"),  ("performance review",  "hr"),
    ("attendance record",   "hr"),  ("headcount",           "hr"),
    ("workforce data",      "hr"),
    # Finance
    ("finance report",      "finance"), ("finance document",    "finance"),
    ("finance data",        "finance"), ("financial report",    "finance"),
    ("financial statement", "finance"), ("balance sheet",       "finance"),
    ("income statement",    "finance"), ("profit and loss",     "finance"),
    ("cash flow",           "finance"), ("fiscal",              "finance"),
    ("accounting report",   "finance"),
    # Marketing
    ("marketing report",    "marketing"), ("marketing document",  "marketing"),
    ("marketing data",      "marketing"), ("campaign report",     "marketing"),
    ("campaign data",       "marketing"), ("ad report",           "marketing"),
    ("marketing analysis",  "marketing"), ("marketing strategy",  "marketing"),
    ("brand report",        "marketing"),
    # Engineering
    ("engineering report",  "engineering"), ("engineering document", "engineering"),
    ("engineering data",    "engineering"), ("technical report",    "engineering"),
    ("technical spec",      "engineering"), ("software report",     "engineering"),
    ("infrastructure report","engineering"),("architecture doc",    "engineering"),
    ("dev report",          "engineering"),
]


def _detect_query_dept(question: str) -> str | None:
    q = question.lower()
    for phrase, dept in _DEPT_PHRASES:
        if phrase in q:
            return dept
    return None


def _role_to_dept(role: str) -> str | None:
    r = role.lower()
    if "marketing"   in r: return "marketing"
    if "hr"          in r: return "hr"
    if "human"       in r: return "hr"
    if "finance"     in r: return "finance"
    if "engineering" in r: return "engineering"
    if "technical"   in r: return "engineering"
    return None


def check_cross_dept_access(question: str, role: str) -> dict | None:
    """Return a denial dict if the user is trying to access another department's data."""
    if role.lower() == "c-level":
        return None
    query_dept = _detect_query_dept(question)
    if query_dept is None:
        return None
    user_dept = _role_to_dept(role)
    if user_dept == query_dept:
        return None
    if user_dept is None:
        return {
            "denied": True,
            "reason": (
                f"**{query_dept.upper()}** department documents are not accessible "
                f"to the **{role}** role. You can only access General workspace documents."
            ),
        }
    return {
        "denied": True,
        "reason": (
            f"**{query_dept.upper()}** department data is restricted. "
            f"Your role (**{role}**) can only access **{user_dept.upper()}** "
            f"documents and General workspace resources."
        ),
    }


def build_denial_message(reason: str, role: str) -> str:
    return (
        f"🔒 **Access Restricted**\n\n"
        f"You do not have permission to access the requested information.\n\n"
        f"**Reason:** {reason}\n\n"
        f"---\n"
        f"*Your current role is **{role}**. "
        f"Contact your administrator if you need elevated access.*"
    )


# ════════════════════════════════════════════════════════════════════════════════
#  Endpoints
# ════════════════════════════════════════════════════════════════════════════════

@router.post("/chat")
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    role     = user["role"]
    username = user["username"]
    question = req.question

    denial = check_cross_dept_access(question, role)
    if denial:
        return {
            "user": username, "role": role, "mode": "DENIED",
            "fallback": False,
            "answer": build_denial_message(denial["reason"], role),
            "sources": [],
        }

    # ── Conversational / greeting short-circuit ─────────────────────────────
    if is_conversational_query(question):
        greeting_answer = (
            "Hello! I'm **FinSight**, your enterprise AI assistant. "
            "I'm here to help you work smarter across your organization — whether that's "
            "analyzing business data, querying HR, Finance, Marketing, Engineering records, "
            "summarizing documents, or surfacing insights from your workspace.\n\n"
            "What can I help you with today?"
        )
        return {
            "user": username, "role": role, "mode": "GREETING",
            "fallback": False,
            "answer": greeting_answer,
            "sources": [],
        }

    mode          = detect_query_type_llm(question)
    result:  dict = {}
    fallback_used = False

    if mode == "SQL":
        try:
            result = await ask_csv(question, role, username, return_sql=True)
            if result.get("error"):
                if result.get("type") == "security":
                    return {
                        "user": username, "role": role, "mode": mode,
                        "fallback": False,
                        "answer": build_denial_message(result.get("answer", "Table not accessible."), role),
                        "sources": [],
                    }
                raise ValueError(result.get("answer", "SQL failed"))
            if not result.get("answer", "").strip():
                raise ValueError("SQL returned empty result")
        except Exception as exc:
            logger.warning(f"[SQL Fallback] {exc}")
            result        = await ask_rag(question, role)
            fallback_used = True
            mode          = "SQL → fallback to RAG"
    else:
        result = await ask_rag(question, role)

    return {
        "user":     username,
        "role":     role,
        "mode":     mode,
        "fallback": fallback_used,
        "answer":   result.get("answer", ""),
        "sources":  result.get("sources", []),
        **( {"sql": result["sql"]} if "sql" in result else {} ),
    }


@router.post("/chat-stream")
async def chat_stream(req: ChatRequest, user: dict = Depends(get_current_user)):
    role     = user["role"]
    username = user["username"]
    question = req.question

    denial        = check_cross_dept_access(question, role)
    is_greeting   = (not denial) and is_conversational_query(question)
    mode          = "DENIED" if denial else ("GREETING" if is_greeting else detect_query_type_llm(question))

    async def event_generator():
        yield json.dumps({"type": "init", "user": username, "role": role, "mode": mode}) + "\n"

        if denial:
            msg = build_denial_message(denial["reason"], role)
            for i in range(0, len(msg), 25):
                yield json.dumps({"type": "token", "content": msg[i:i+25]}) + "\n"
                await asyncio.sleep(0.008)
            yield json.dumps({"type": "metadata", "sources": [], "fallback": False}) + "\n"
            return

        # ── Greeting / conversational short-circuit ─────────────────────────────
        if is_greeting:
            msg = (
                "Hello! I'm **FinSight**, your enterprise AI assistant. "
                "I'm here to help you work smarter across your organization — whether that's "
                "analyzing business data, querying HR, Finance, Marketing, Engineering records, "
                "summarizing documents, or surfacing insights from your workspace.\n\n"
                "What can I help you with today?"
            )
            for i in range(0, len(msg), 30):
                yield json.dumps({"type": "token", "content": msg[i:i+30]}) + "\n"
                await asyncio.sleep(0.008)
            yield json.dumps({"type": "metadata", "sources": [], "fallback": False}) + "\n"
            return


        fallback_used = False

        if mode == "SQL":
            try:
                result = await ask_csv(question, role, username, return_sql=True)
                if result.get("error"):
                    if result.get("type") == "security":
                        msg = build_denial_message(result.get("answer", "Table not accessible."), role)
                        for i in range(0, len(msg), 25):
                            yield json.dumps({"type": "token", "content": msg[i:i+25]}) + "\n"
                            await asyncio.sleep(0.008)
                        yield json.dumps({"type": "metadata", "sources": [], "fallback": False}) + "\n"
                        return
                    raise ValueError(result.get("answer", "SQL failed"))

                answer = result.get("answer", "")
                sql    = result.get("sql",    "")
                for i in range(0, len(answer), 30):
                    yield json.dumps({"type": "token", "content": answer[i:i+30]}) + "\n"
                    await asyncio.sleep(0.01)
                yield json.dumps({
                    "type": "metadata", "sql": sql,
                    "sources": result.get("sources", []), "fallback": False,
                }) + "\n"
                return
            except Exception as exc:
                logger.warning(f"[SQL Fallback] {exc}")
                fallback_used = True
                yield json.dumps({"type": "fallback", "mode": "SQL → fallback to RAG"}) + "\n"

        # RAG streaming
        try:
            chain   = get_rag_chain(user_role=role)
            sources: list[str] = []
            full_answer = ""

            async for chunk in chain.astream({"input": question}):
                if "context" in chunk:
                    for doc in chunk["context"]:
                        src = doc.metadata.get("source")
                        if src and src not in sources:
                            sources.append(src)
                if "answer" in chunk:
                    token = chunk["answer"]
                    if token:
                        full_answer += token
                        yield json.dumps({"type": "token", "content": token}) + "\n"
                        await asyncio.sleep(0.002)

            if "could not find relevant information" in full_answer.lower():
                sources = []

            yield json.dumps({
                "type": "metadata", "sources": sources, "fallback": fallback_used,
            }) + "\n"

        except Exception as exc:
            s = str(exc).lower()
            if "429" in s or "resource exhausted" in s:
                msg = "⚠️ **Rate Limited** — The AI service is temporarily rate-limited. Please try again in a moment."
            elif "quota" in s or "billing" in s:
                msg = "⚠️ **Quota Exceeded** — The API quota is exhausted. Please contact your administrator."
            elif "404" in s:
                msg = "⚠️ **Service Unavailable** — The AI model is temporarily offline. Please try again."
            else:
                msg = f"⚠️ **Error** — {exc}"
            yield json.dumps({"type": "token",    "content": msg}) + "\n"
            yield json.dumps({"type": "metadata", "sources": [], "fallback": fallback_used}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
