"""
app/rag/embeddings.py — Lazy Gemini Embedding 2 service (1536-dim Matryoshka + asymmetric prefixes).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Callable, Iterable

from google.genai import types
from langchain_core.documents import Document

from app.core.config import (
    EMBEDDING_DIMENSIONS,
    GEMINI_EMBEDDING_MODEL,
    get_genai_client,
)
from app.rag.errors import classify_api_error, parse_retry_delay

logger = logging.getLogger("FinSight.embeddings")


def format_document_for_embedding(doc: Document) -> str:
    """Format chunk text using Gemini Embedding 2 asymmetric document prefix."""
    title = (
        doc.metadata.get("doc_title")
        or doc.metadata.get("source")
        or "none"
    )
    return f"title: {title} | text: {doc.page_content}"


def format_query_for_embedding(query: str) -> str:
    """Format user query using Gemini Embedding 2 asymmetric QA prefix."""
    return f"task: question answering | query: {query}"


def l2_normalize(vector: list[float]) -> list[float]:
    """L2-normalize Matryoshka-truncated vectors for unit cosine distance."""
    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 0.0:
        return vector
    return [float(v / norm) for v in vector]


class GeminiEmbedding2Service:
    """
    Lazy, retry-resilient google-genai embedding service configured for
    gemini-embedding-2 at EMBEDDING_DIMENSIONS (default 1536).
    """

    _INITIAL_DELAY = 2.0
    _MAX_DELAY = 120.0
    _BATCH_SIZE = 50

    def __init__(
        self,
        model: str | None = None,
        dimensions: int | None = None,
        client_factory: Callable[[], object] | None = None,
    ):
        self.model = model or GEMINI_EMBEDDING_MODEL
        self.dimensions = dimensions or EMBEDDING_DIMENSIONS
        self._client_factory = client_factory or get_genai_client

    def _call_with_retry(self, fn, label: str):
        delay = self._INITIAL_DELAY
        for attempt in range(8):
            try:
                return fn()
            except Exception as exc:
                kind = classify_api_error(exc)
                if kind == "hard_quota":
                    raise
                if kind == "transient_rate_limit" and attempt < 7:
                    wait = min(parse_retry_delay(exc, delay), self._MAX_DELAY)
                    logger.warning(
                        f"[Embeddings] 429 on {label} — waiting {wait:.1f}s "
                        f"(attempt {attempt + 1}/8)"
                    )
                    time.sleep(wait)
                    delay = min(delay * 2.0, self._MAX_DELAY)
                    continue
                raise

    def _embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        client = self._client_factory()
        cfg = types.EmbedContentConfig(output_dimensionality=self.dimensions)
        response = client.models.embed_content(
            model=self.model,
            contents=texts,
            config=cfg,
        )
        embeddings = getattr(response, "embeddings", None) or []
        vectors: list[list[float]] = []
        for item in embeddings:
            vals = list(getattr(item, "values", []) or [])
            vectors.append(l2_normalize(vals))
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"Embedding count mismatch: sent {len(texts)}, got {len(vectors)}"
            )
        return vectors

    def embed_documents(self, docs: Iterable[Document | str]) -> list[list[float]]:
        formatted: list[str] = []
        for item in docs:
            if isinstance(item, Document):
                formatted.append(format_document_for_embedding(item))
            else:
                formatted.append(f"title: none | text: {item}")

        if not formatted:
            return []

        results: list[list[float]] = []
        for start in range(0, len(formatted), self._BATCH_SIZE):
            batch = formatted[start : start + self._BATCH_SIZE]
            batch_vecs = self._call_with_retry(
                lambda b=batch: self._embed_batch_sync(b),
                label=f"doc batch {start // self._BATCH_SIZE + 1}",
            )
            results.extend(batch_vecs)
        return results

    def embed_query(self, query: str) -> list[float]:
        formatted = format_query_for_embedding(query)
        vecs = self._call_with_retry(
            lambda: self._embed_batch_sync([formatted]),
            label="query",
        )
        return vecs[0]

    async def aembed_documents(self, docs: Iterable[Document | str]) -> list[list[float]]:
        doc_list = list(docs)
        return await asyncio.to_thread(self.embed_documents, doc_list)

    async def aembed_query(self, query: str) -> list[float]:
        return await asyncio.to_thread(self.embed_query, query)
