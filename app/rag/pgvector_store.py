"""
app/rag/pgvector_store.py — Hybrid Vector + TSVector RRF store & transactional chunk commits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Iterable

from langchain_core.documents import Document
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import COHERE_RERANK_MODEL, cohere_api_key
from app.db.models import DocumentChunk, DocumentRecord
from app.db.session import async_session, sync_session
from app.rag.embeddings import GeminiEmbedding2Service

try:
    from langchain_cohere import CohereRerank

    _COHERE_AVAILABLE = True
except ImportError:
    _COHERE_AVAILABLE = False

logger = logging.getLogger("FinSight.pgvector_store")

_LEXICAL_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does",
        "for", "from", "has", "have", "how", "in", "is", "it", "its", "me",
        "my", "of", "on", "or", "our", "show", "tell", "that", "the", "their",
        "them", "there", "these", "they", "this", "to", "us", "was", "we",
        "were", "what", "when", "where", "which", "who", "whom", "why", "will",
        "with", "would", "you", "your",
    }
)


def role_predicate_clause(user_role: str) -> tuple[str, dict]:
    """
    Build a parameterized SQL WHERE predicate enforcing FinSight RBAC:
      - 'c-level' -> unrestricted
      - 'general' -> general only
      - dept role -> dept OR general
    """
    role_lower = (user_role or "general").strip().lower()
    if role_lower == "c-level":
        return "TRUE", {}
    if role_lower == "general":
        return "LOWER(role) = 'general'", {}
    return "(LOWER(role) = :role_lower OR LOWER(role) = 'general')", {"role_lower": role_lower}


def doc_ids_predicate_clause(
    user_role: str,
    allowed_doc_ids: list[int] | None = None,
) -> tuple[str, dict, bool]:
    """
    Build ReBAC-enforced doc_id WHERE predicate when `allowed_doc_ids` is provided,
    falling back to RBAC role predicates when invoked in legacy role-only mode.
    Returns `(sql_clause, params, empty_short_circuit)`.
    """
    if allowed_doc_ids is not None:
        clean_ids = sorted({int(d) for d in allowed_doc_ids})
        if not clean_ids:
            return "FALSE", {}, True
        return "doc_id = ANY(:allowed_doc_ids)", {"allowed_doc_ids": clean_ids}, False
    role_clause, role_params = role_predicate_clause(user_role)
    return role_clause, role_params, False


def has_meaningful_lexical_terms(query: str) -> bool:
    tokens = re.findall(r"\w+", query or "")
    return any(len(tok) >= 2 and tok.lower() not in _LEXICAL_STOPWORDS for tok in tokens)


def vector_to_pg_literal(vector: Iterable[float]) -> str:
    return json.dumps([float(v) for v in vector])


def build_hybrid_rrf_sql(
    user_role: str,
    include_sparse: bool = True,
    allowed_doc_ids: list[int] | None = None,
) -> tuple[str, dict]:
    """
    Construct a single PostgreSQL CTE combining pgvector cosine distance ANN search
    and TSVector GIN search merged with Reciprocal Rank Fusion (k=60).
    """
    role_clause, role_params, _ = doc_ids_predicate_clause(
        user_role, allowed_doc_ids=allowed_doc_ids
    )

    if include_sparse:
        sql = f"""
        WITH dense AS (
            SELECT
                id,
                (1.0 - (embedding <=> CAST(:qvec AS vector))) AS cosine_score,
                ROW_NUMBER() OVER (ORDER BY embedding <=> CAST(:qvec AS vector) ASC) AS rnk
            FROM document_chunks
            WHERE {role_clause}
            ORDER BY embedding <=> CAST(:qvec AS vector) ASC
            LIMIT :dense_k
        ),
        sparse AS (
            SELECT
                id,
                ts_rank_cd(search_vector, websearch_to_tsquery('english', :query_text)) AS bm25_score,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('english', :query_text)) DESC
                ) AS rnk
            FROM document_chunks
            WHERE {role_clause}
              AND search_vector @@ websearch_to_tsquery('english', :query_text)
            ORDER BY bm25_score DESC
            LIMIT :sparse_k
        ),
        fused AS (
            SELECT id, (1.0 / (60.0 + rnk)) AS rrf_part, cosine_score, 0.0::double precision AS bm25_score
            FROM dense
            UNION ALL
            SELECT id, (1.0 / (60.0 + rnk)) AS rrf_part, 0.0::double precision AS cosine_score, bm25_score
            FROM sparse
        ),
        scored AS (
            SELECT
                id,
                SUM(rrf_part) AS rrf_score,
                MAX(cosine_score) AS cosine_score,
                MAX(bm25_score) AS bm25_score
            FROM fused
            GROUP BY id
        )
        SELECT
            c.chunk_id,
            c.doc_id,
            c.chunk_index,
            c.role,
            c.source,
            c.chunk_type,
            c.page_number,
            c.section_title,
            c.raw_content,
            c.context_prefix,
            c.content,
            s.rrf_score,
            s.cosine_score,
            s.bm25_score
        FROM scored s
        JOIN document_chunks c ON c.id = s.id
        ORDER BY s.rrf_score DESC, s.cosine_score DESC
        LIMIT :limit_k
        """
    else:
        sql = f"""
        SELECT
            chunk_id,
            doc_id,
            chunk_index,
            role,
            source,
            chunk_type,
            page_number,
            section_title,
            raw_content,
            context_prefix,
            content,
            (1.0 / (60.0 + ROW_NUMBER() OVER (ORDER BY embedding <=> CAST(:qvec AS vector) ASC))) AS rrf_score,
            (1.0 - (embedding <=> CAST(:qvec AS vector))) AS cosine_score,
            0.0::double precision AS bm25_score
        FROM document_chunks
        WHERE {role_clause}
        ORDER BY embedding <=> CAST(:qvec AS vector) ASC
        LIMIT :limit_k
        """
    return sql, role_params


def _row_to_document(row) -> Document:
    return Document(
        page_content=row.content,
        metadata={
            "chunk_id": row.chunk_id,
            "doc_id": int(row.doc_id),
            "chunk_index": int(row.chunk_index),
            "role": row.role,
            "source": row.source,
            "chunk_type": row.chunk_type,
            "page_number": row.page_number,
            "section_title": row.section_title,
            "raw_content": row.raw_content,
            "context_prefix": row.context_prefix,
            "rrf_score": round(float(row.rrf_score or 0.0), 6),
            "relevance_score": round(float(row.cosine_score or 0.0), 4),
            "bm25_score": round(float(row.bm25_score or 0.0), 6),
        },
    )


def _build_chunk_models(
    doc_id: int,
    role: str,
    source: str,
    chunks: list[Document],
    vectors: list[list[float]],
) -> list[DocumentChunk]:
    if len(chunks) != len(vectors):
        raise ValueError(
            f"Chunk count ({len(chunks)}) does not match embedding count ({len(vectors)})"
        )
    models: list[DocumentChunk] = []
    for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
        meta = chunk.metadata or {}
        raw_content = str(meta.get("raw_content") or chunk.page_content)
        context_prefix = str(meta.get("context_prefix") or "")
        models.append(
            DocumentChunk(
                chunk_id=f"{doc_id}_{idx}",
                doc_id=doc_id,
                chunk_index=idx,
                role=(meta.get("role") or role).lower(),
                source=str(meta.get("source") or source),
                chunk_type=str(meta.get("chunk_type") or "text"),
                page_number=(
                    str(meta["page_number"])
                    if meta.get("page_number") is not None
                    else None
                ),
                section_title=(
                    str(meta["section_title"])
                    if meta.get("section_title") is not None
                    else None
                ),
                raw_content=raw_content,
                context_prefix=context_prefix,
                content=chunk.page_content,
                embedding=[float(v) for v in vec],
            )
        )
    return models


class PgVectorHybridStore:
    """
    Role-isolated PostgreSQL 17 + pgvector/pgvectorscale + TSVector hybrid store.
    """

    def __init__(self, embeddings: GeminiEmbedding2Service | None = None):
        self.embeddings = embeddings or GeminiEmbedding2Service()

    def _rerank_if_configured(
        self,
        query: str,
        candidates: list[Document],
        top_n: int,
        cohere_key: str | None = None,
    ) -> list[Document]:
        key = cohere_key or cohere_api_key
        if key and _COHERE_AVAILABLE and len(candidates) > 1:
            try:
                reranker = CohereRerank(
                    cohere_api_key=key,
                    model=COHERE_RERANK_MODEL,
                    top_n=min(top_n, len(candidates)),
                )
                return list(reranker.compress_documents(documents=candidates, query=query))
            except Exception as exc:
                logger.warning(f"[Retrieval] Cohere rerank skipped ({type(exc).__name__})")
        return candidates[:top_n]

    async def asearch(
        self,
        query: str,
        user_role: str,
        *,
        limit: int = 6,
        dense_k: int = 30,
        sparse_k: int = 25,
        cohere_key: str | None = None,
        rerank: bool = True,
        query_vector: list[float] | None = None,
        allowed_doc_ids: list[int] | None = None,
        session: AsyncSession | None = None,
    ) -> list[Document]:
        if allowed_doc_ids is not None and len(allowed_doc_ids) == 0:
            return []
        qvec = query_vector if query_vector is not None else await self.embeddings.aembed_query(query)
        use_sparse = has_meaningful_lexical_terms(query)
        sql_str, role_params = build_hybrid_rrf_sql(
            user_role, include_sparse=use_sparse, allowed_doc_ids=allowed_doc_ids
        )
        params = {
            **role_params,
            "qvec": vector_to_pg_literal(qvec),
            "query_text": query,
            "dense_k": dense_k,
            "sparse_k": sparse_k,
            "limit_k": max(limit, 30 if rerank else limit),
        }

        if session is not None:
            rows = (await session.execute(text(sql_str), params)).all()
        else:
            async with async_session() as db:
                rows = (await db.execute(text(sql_str), params)).all()

        candidates = [_row_to_document(row) for row in rows]
        if not candidates:
            return []
        if rerank:
            return await asyncio.to_thread(
                self._rerank_if_configured, query, candidates, limit, cohere_key
            )
        return candidates[:limit]

    def search(
        self,
        query: str,
        user_role: str,
        *,
        limit: int = 6,
        dense_k: int = 30,
        sparse_k: int = 25,
        cohere_key: str | None = None,
        rerank: bool = True,
        query_vector: list[float] | None = None,
        allowed_doc_ids: list[int] | None = None,
        session: Session | None = None,
    ) -> list[Document]:
        if allowed_doc_ids is not None and len(allowed_doc_ids) == 0:
            return []
        qvec = query_vector if query_vector is not None else self.embeddings.embed_query(query)
        use_sparse = has_meaningful_lexical_terms(query)
        sql_str, role_params = build_hybrid_rrf_sql(
            user_role, include_sparse=use_sparse, allowed_doc_ids=allowed_doc_ids
        )
        params = {
            **role_params,
            "qvec": vector_to_pg_literal(qvec),
            "query_text": query,
            "dense_k": dense_k,
            "sparse_k": sparse_k,
            "limit_k": max(limit, 30 if rerank else limit),
        }

        if session is not None:
            rows = session.execute(text(sql_str), params).all()
        else:
            with sync_session() as db:
                rows = db.execute(text(sql_str), params).all()

        candidates = [_row_to_document(row) for row in rows]
        if not candidates:
            return []
        if rerank:
            return self._rerank_if_configured(query, candidates, limit, cohere_key)
        return candidates[:limit]

    def lexical_search(
        self,
        query: str,
        user_role: str,
        *,
        limit: int = 25,
        allowed_doc_ids: list[int] | None = None,
        session: Session | None = None,
    ) -> list[Document]:
        """Run ReBAC/role-scoped PostgreSQL TSVector GIN lexical search cleanly."""
        if not has_meaningful_lexical_terms(query):
            return []
        if allowed_doc_ids is not None and len(allowed_doc_ids) == 0:
            return []
        role_clause, role_params, empty_sc = doc_ids_predicate_clause(
            user_role, allowed_doc_ids=allowed_doc_ids
        )
        if empty_sc:
            return []
        sql_str = f"""
        SELECT
            chunk_id,
            doc_id,
            chunk_index,
            role,
            source,
            chunk_type,
            page_number,
            section_title,
            raw_content,
            context_prefix,
            content,
            0.0::double precision AS rrf_score,
            0.0::double precision AS cosine_score,
            ts_rank_cd(search_vector, websearch_to_tsquery('english', :query_text)) AS bm25_score
        FROM document_chunks
        WHERE {role_clause}
          AND search_vector @@ websearch_to_tsquery('english', :query_text)
        ORDER BY bm25_score DESC
        LIMIT :limit_k
        """
        params = {**role_params, "query_text": query, "limit_k": limit}
        if session is not None:
            rows = session.execute(text(sql_str), params).all()
        else:
            with sync_session() as db:
                rows = db.execute(text(sql_str), params).all()
        return [_row_to_document(row) for row in rows]

    async def replace_document_chunks(
        self,
        doc_id: int,
        role: str,
        source: str,
        chunks: list[Document],
        vectors: list[list[float]],
        *,
        parser_used: str | None = None,
        session: AsyncSession | None = None,
    ) -> int:
        """
        Atomically replace all chunks for doc_id inside one PostgreSQL transaction
        and mark the parent DocumentRecord embedded=1. Live readers never see
        partial or empty intermediate state.
        """
        models = _build_chunk_models(doc_id, role, source, chunks, vectors)

        async def _apply(db: AsyncSession) -> None:
            await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id))
            db.add_all(models)
            values: dict = {
                "embedded": 1,
                "total_chunks": len(models),
                "embedded_chunks": len(models),
                "last_error": None,
            }
            if parser_used is not None:
                values["parser_used"] = parser_used
            await db.execute(
                update(DocumentRecord)
                .where(DocumentRecord.id == doc_id)
                .values(**values)
            )

        if session is not None:
            await _apply(session)
            await session.flush()
        else:
            async with async_session() as db:
                async with db.begin():
                    await _apply(db)

        return len(models)

    def replace_document_chunks_sync(
        self,
        doc_id: int,
        role: str,
        source: str,
        chunks: list[Document],
        vectors: list[list[float]],
        *,
        parser_used: str | None = None,
        session: Session | None = None,
    ) -> int:
        models = _build_chunk_models(doc_id, role, source, chunks, vectors)

        def _apply(db: Session) -> None:
            db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id))
            db.add_all(models)
            values: dict = {
                "embedded": 1,
                "total_chunks": len(models),
                "embedded_chunks": len(models),
                "last_error": None,
            }
            if parser_used is not None:
                values["parser_used"] = parser_used
            db.execute(
                update(DocumentRecord)
                .where(DocumentRecord.id == doc_id)
                .values(**values)
            )

        if session is not None:
            _apply(session)
            session.flush()
        else:
            with sync_session() as db:
                with db.begin():
                    _apply(db)

        return len(models)

    async def count_chunks(self) -> int:
        async with async_session() as db:
            return int(await db.scalar(select(func.count()).select_from(DocumentChunk)) or 0)
