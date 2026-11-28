"""
app/rag/contextualizer.py — Contextual Retrieval prefix generator using Gemini Light Model.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Callable

from langchain_core.documents import Document

from app.core.config import (
    CONTEXTUAL_RETRIEVAL_ENABLED,
    GEMINI_LIGHT_MODEL,
    generate_content_with_fallback,
    get_genai_client,
)
from app.rag.errors import classify_api_error

logger = logging.getLogger("FinSight.contextualizer")


def build_document_synopsis(full_text: str, filename: str, max_chars: int = 2000) -> str:
    """Build a compact synopsis of the document (headings outline + opening slice)."""
    headings = [
        line.strip()
        for line in full_text.splitlines()
        if re.match(r"^#{1,4}\s+", line.strip())
    ][:15]
    outline = "\n".join(headings)
    excerpt = full_text[:max_chars].strip()
    if outline:
        return f"Document: {filename}\nOutline:\n{outline}\n\nOpening Excerpt:\n{excerpt}"
    return f"Document: {filename}\nOpening Excerpt:\n{excerpt}"


def deterministic_context_prefix(doc: Document, filename: str) -> str:
    """Offline fallback context header using structured chunk metadata."""
    section = doc.metadata.get("section_title")
    page = doc.metadata.get("page_number")
    role = (doc.metadata.get("role") or "general").title()
    parts = [f"Document: {filename}", f"Access Role: {role}"]
    if section:
        parts.append(f"Section: {section}")
    if page:
        parts.append(f"Page: {page}")
    return " | ".join(parts)


async def contextualize_chunks(
    chunks: list[Document],
    full_text: str,
    filename: str,
    *,
    enabled: bool | None = None,
    max_concurrency: int = 4,
    client_factory: Callable[[], object] | None = None,
) -> list[Document]:
    """
    Enrich chunks concurrently (bounded by Semaphore) with short LLM-generated
    document-situating context headers. Falls back deterministically when disabled
    or when the Gemini API is unavailable/quota-exhausted.
    """
    if not chunks:
        return []

    is_enabled = (
        CONTEXTUAL_RETRIEVAL_ENABLED
        if enabled is None
        else enabled
    )
    if is_enabled:
        env_flag = os.getenv("CONTEXTUAL_RETRIEVAL_ENABLED")
        if env_flag is not None:
            is_enabled = env_flag.strip().lower() == "true"

    synopsis = build_document_synopsis(full_text, filename)
    sem = asyncio.Semaphore(max(1, max_concurrency))
    get_client = client_factory or get_genai_client
    quota_exhausted = False

    async def _enrich_one(chunk: Document) -> Document:
        nonlocal quota_exhausted
        raw_content = chunk.page_content
        chunk_type = chunk.metadata.get("chunk_type", "text")
        fallback_prefix = deterministic_context_prefix(chunk, filename)

        if not is_enabled or quota_exhausted or chunk_type == "doc_summary":
            prefix = "" if chunk_type == "doc_summary" else fallback_prefix
            meta = {
                **chunk.metadata,
                "raw_content": raw_content,
                "context_prefix": prefix,
            }
            content = f"Context: {prefix}\n\n{raw_content}" if prefix else raw_content
            return Document(page_content=content, metadata=meta)

        prompt = (
            "Write a short, concrete 1-2 sentence context prefix that situates the "
            "chunk below inside the overall document (specify department, timeframe, "
            "metric/topic, or table subject when visible). Do not answer any question "
            "and do not repeat the chunk verbatim.\n\n"
            f"<document>\n{synopsis}\n</document>\n\n"
            f"<chunk>\n{raw_content[:2000]}\n</chunk>\n\n"
            "Context:"
        )

        async with sem:
            if quota_exhausted:
                prefix = fallback_prefix
            else:
                try:
                    client = get_client()
                    generated = await asyncio.to_thread(
                        generate_content_with_fallback,
                        client,
                        prompt,
                        GEMINI_LIGHT_MODEL,
                    )
                    prefix = re.sub(r"\s+", " ", generated or "").strip() or fallback_prefix
                except Exception as exc:
                    if classify_api_error(exc) == "hard_quota":
                        quota_exhausted = True
                        logger.warning(
                            f"[Contextualizer] Quota exhausted for '{filename}'; using deterministic context fallback."
                        )
                    else:
                        logger.warning(
                            f"[Contextualizer] Context generation skipped for '{filename}' ({type(exc).__name__}); using fallback."
                        )
                    prefix = fallback_prefix

        meta = {
            **chunk.metadata,
            "raw_content": raw_content,
            "context_prefix": prefix,
        }
        return Document(page_content=f"Context: {prefix}\n\n{raw_content}", metadata=meta)

    return list(await asyncio.gather(*(_enrich_one(c) for c in chunks)))
