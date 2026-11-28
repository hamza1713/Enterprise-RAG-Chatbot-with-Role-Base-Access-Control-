"""
app/agents/schemas.py — Structured Pydantic outputs & typed LangGraph state definitions.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class RouteDecision(BaseModel):
    """Structured routing & query-rewriting decision from Gemini."""

    mode: Literal["greeting", "sql", "rag", "hybrid"] = "rag"
    standalone_question: str = Field(
        default="",
        description="Self-contained rewritten user query resolving conversation pronouns.",
    )
    sub_queries: list[str] = Field(
        default_factory=list,
        max_length=2,
        description="At most 2 focused retrieval sub-queries when mode is rag or hybrid.",
    )
    reasoning: str = ""


class ChunkRelevanceGrade(BaseModel):
    """Structured retrieval relevance assessment."""

    sufficient: bool = True
    rewritten_query: str = ""
    reason: str = ""


class SqlPlanOutput(BaseModel):
    """Structured DuckDB SQL + visualization hint returned by NL2SQL."""

    sql: str
    chart_hint: Literal["bar", "line", "area", "pie", "none"] = "none"
    title: str = "Query Results"


class AgentStepEvent(TypedDict, total=False):
    node: str
    label: str
    status: str  # "running" | "done" | "error"
    detail: str


class CitationItem(TypedDict, total=False):
    index: int
    chunk_id: str
    doc_id: int
    source: str
    page_number: str | None
    section_title: str | None
    chunk_type: str | None
    parser_used: str | None
    snippet: str


class FinSightAgentState(TypedDict, total=False):
    question: str
    username: str
    user_role: str
    thread_id: str
    history: list[dict[str, str]]
    allowed_doc_ids: list[int]
    allowed_datasets: list[dict[str, Any]]
    acl_fingerprint: str
    blocked_reason: str | None
    mode: str
    standalone_question: str
    sub_queries: list[str]
    retrieved_chunks: list[dict[str, Any]]
    loop_count: int
    max_loops: int
    reroute_requested: bool
    sql_result: dict[str, Any] | None
    answer: str
    citations: list[CitationItem]
    sources: list[str]
    chart_spec: dict[str, Any] | None
    agent_steps: list[AgentStepEvent]
    guardrail_warnings: list[str]
    model_fallback_used: bool
    input_tokens: int
    output_tokens: int
