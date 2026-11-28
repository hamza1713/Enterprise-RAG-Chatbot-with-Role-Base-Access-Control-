"""
app/rag/classifier.py — LLM-based query type classifier.

Decides whether a user question should be answered via SQL (structured
data in DuckDB), RAG (unstructured document retrieval), or is a
conversational/greeting message that should be handled directly.

Renamed from `app/rag_utils/query_classifier.py`.
"""

import re

from app.core.config import (
    GEMINI_LIGHT_MODEL,
    generate_content_with_fallback,
    get_genai_client,
)

# ── Conversational intent patterns ────────────────────────────────────────────

_GREETING_PATTERNS = {
    # greetings
    "hi", "hello", "hey", "howdy", "greetings", "hiya", "yo",
    # farewells
    "bye", "goodbye", "see you", "see ya", "later", "farewell",
    # thanks
    "thanks", "thank you", "thank you so much", "thx", "ty",
    "many thanks", "appreciate it", "appreciated",
    # how are you
    "how are you", "how are you doing", "how's it going", "how do you do",
    "what's up", "whats up", "sup",
    # small talk / meta
    "good morning", "good afternoon", "good evening", "good night",
    "morning", "afternoon", "evening",
    # bot identity
    "who are you", "what are you", "what can you do",
    "what is finsight", "tell me about yourself",
    "introduce yourself", "what do you do",
    # help / start
    "help", "get started", "start", "begin",
    # ok / cool / nice
    "ok", "okay", "sure", "cool", "nice", "great", "awesome",
    "got it", "understood", "alright", "all right",
}


_CONVERSATIONAL_OPENER_RE = re.compile(
    r"^(?:"
    r"(?:hi|hello|hey|howdy|greetings|hiya|yo|good morning|good afternoon|good evening)"
    r"(?:[,!\s]+(?:there|everyone|folks|all|team|finsight|bot|ai))*"
    r"(?:[,!.\s]+(?:how are you|how's it going|what's up|whats up|nice to meet you))?"
    r"|(?:thanks|thank you)(?:\s+(?:so much|very much|a lot))?(?:[,!\s]+(?:everyone|team|finsight))?"
    r")$"
)


def is_conversational_query(question: str) -> bool:
    """
    Return True if the question is a greeting, farewell, thank-you,
    or other conversational small-talk that should NOT go through RAG/SQL.

    Uses strict exact + greeting-opener matching so domain queries such as
    'history of 2024', 'types of...', 'okr...', or 'help me list...' are never swallowed.
    """
    q = re.sub(r"\s+", " ", question.strip().lower()).rstrip("!?.,; ")
    if not q:
        return False
    if q in _GREETING_PATTERNS:
        return True
    if len(q.split()) <= 8 and _CONVERSATIONAL_OPENER_RE.match(q):
        return True
    return False


def detect_query_type_llm(question: str) -> str:
    """
    Classify a user question as 'SQL' or 'RAG'.

    Returns 'SQL' if the question targets tabular/structured data,
    or 'RAG' if it targets unstructured documents/policies/reports.
    """
    prompt = f"""
You are a classifier that decides if a user's question should be handled by structured SQL query logic on CSV/spreadsheet tables or by unstructured document search (RAG).

Classify as "SQL" if the question asks to:
- Show, list, explore, retrieve, or query tabular/spreadsheet data (e.g., "show customer data", "retrieve employee details", "explore HR records", "can you show me some finance data", "give employees details", "list all HR records", "show payroll data").
- Perform calculations, counts, filtering, or aggregations (e.g., "average salary", "total sales", "how many users", "salary greater than 80000", "count employees", "total revenue").
- Filter rows by values or list columns (e.g., "show rows where department is Marketing", "filter by age less than 30", "employees with salary above X").

Classify as "RAG" if the question:
- Asks to "summarize", "explain", "describe", "analyze" or requests a high-level overview (e.g., "summarize the marketing report", "explain our HR policy", "what does the financial summary say").
- Uses words like "report", "summary", "analysis", "plan", "strategy", "document", "policy", "handbook", "overview".
- Asks about company policies, guidelines, best practices, or strategic decisions.
- Cannot be answered from structured tabular data.

Critical disambiguation rules:
- "show/list/retrieve/give me employee records" → SQL
- "summarize the HR report" or "what is in the marketing report" → RAG
- "how many employees are in department X" → SQL
- "explain the marketing strategy" or "marketing plan" → RAG
- "give me finance data" or "list financial records" → SQL
- "what does the financial summary say" or "financial report overview" → RAG
- "show HR data" or "retrieve payroll" → SQL
- "HR policy" or "HR guidelines" → RAG

Respond with only one word: either SQL or RAG.

Here is the question:
"{question}"

Answer:
    """
    result = generate_content_with_fallback(
        get_genai_client(),
        prompt,
        preferred_model=GEMINI_LIGHT_MODEL,
    )
    classified = result.strip().upper()
    return "SQL" if "SQL" in classified else "RAG"
