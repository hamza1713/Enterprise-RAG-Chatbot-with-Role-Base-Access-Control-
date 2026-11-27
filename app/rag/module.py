"""
app/rag/module.py — Production RAG Engine backed by PostgreSQL 17 + pgvector,
Docling-Serve PDF/OCR parsing, Contextual Retrieval, and Gemini Embedding 2.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from typing import Callable, List

# Apply RAG env-vars lazily before LangChain imports
import app.rag.config  # noqa: F401

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import ConfigDict
from sqlalchemy import func, select, update

from app.core.config import (
    GEMINI_CHAT_MODEL,
    GEMINI_LIGHT_MODEL,
    cohere_api_key,
    google_api_key,
)
from app.db.models import DocumentRecord
from app.db.session import async_session, sync_session
from app.rag.contextualizer import contextualize_chunks
from app.rag.embeddings import GeminiEmbedding2Service
from app.rag.pgvector_store import PgVectorHybridStore
from app.rag.processors import (
    CSVDocumentLoader,
    CSVSemanticChunker,
    DoclingServePDFParser,
    MarkdownDocumentLoader,
    MarkdownSemanticChunker,
    PDFSemanticChunker,
)
from app.storage import get_storage_backend

logger = logging.getLogger("FinSight.rag")

# Testable lazy singletons (zero DUMMY_KEY instantiation at import time)
_factory_lock = threading.Lock()
model = None
hybrid_store: PgVectorHybridStore | None = None
embeddings_service: GeminiEmbedding2Service | None = None


def get_embeddings_service() -> GeminiEmbedding2Service:
    global embeddings_service
    if embeddings_service is None:
        with _factory_lock:
            if embeddings_service is None:
                embeddings_service = GeminiEmbedding2Service()
    return embeddings_service


def get_hybrid_store() -> PgVectorHybridStore:
    global hybrid_store
    if hybrid_store is None:
        with _factory_lock:
            if hybrid_store is None:
                hybrid_store = PgVectorHybridStore(embeddings=get_embeddings_service())
    return hybrid_store


def _build_chat_model(api_key: str):
    fallback_names = [
        m for m in [GEMINI_LIGHT_MODEL, "gemini-2.5-flash"] if m and m != GEMINI_CHAT_MODEL
    ]
    return ChatGoogleGenerativeAI(
        model=GEMINI_CHAT_MODEL,
        temperature=0.2,
        google_api_key=api_key,
        transport="rest",
        max_retries=1,
    ).with_fallbacks(
        [
            ChatGoogleGenerativeAI(
                model=fallback_name,
                temperature=0.2,
                google_api_key=api_key,
                transport="rest",
                max_retries=1,
            )
            for fallback_name in dict.fromkeys(fallback_names)
        ]
    )


def get_chat_model():
    """Return lazily constructed Gemini chat model (or patched module.model override)."""
    global model
    if model is not None:
        return model
    with _factory_lock:
        if model is None:
            key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or google_api_key
            if not key:
                raise RuntimeError("GOOGLE_API_KEY is not configured")
            model = _build_chat_model(key)
    return model


# ════════════════════════════════════════════════════════════════════════════════
#  DOCUMENT INGESTION PIPELINE (Docling/MD/CSV -> Chunk -> Contextualize -> Embed -> Postgres)
# ════════════════════════════════════════════════════════════════════════════════


async def ingest_single_document(
    doc_id: int,
    *,
    cancel_check: Callable[[], asyncio.Future | object] | None = None,
    progress_callback: Callable[[int, int, str], object] | None = None,
) -> dict:
    """
    Execute full ingestion pipeline for one DocumentRecord:
      1. Fetch file bytes from ObjectStorageBackend
      2. Parse (PDF -> DoclingServePDFParser with pdfplumber fallback; MD/CSV -> loaders)
      3. Chunk + Contextual Retrieval enrichment (gemini-3.5-flash-lite, Semaphore=4)
      4. Batch embed via GeminiEmbedding2Service (1536 dims, title: ... | text: ...)
      5. Atomically commit chunks + mark embedded=1 inside one Postgres transaction
    """
    async with async_session() as db:
        doc_row = await db.scalar(select(DocumentRecord).where(DocumentRecord.id == doc_id))
        if doc_row is None:
            raise ValueError(f"Document {doc_id} not found")
        filename = doc_row.filename
        role = doc_row.role
        object_key = doc_row.object_key

    if cancel_check is not None:
        await cancel_check()

    storage = get_storage_backend()
    raw_bytes = await storage.aget_bytes(object_key)
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == ".pdf":
        loaded_docs = await DoclingServePDFParser().parse_bytes(raw_bytes, filename, role)
        parser_used = (
            loaded_docs[0].metadata.get("parser_used", "pdfplumber")
            if loaded_docs
            else "pdfplumber"
        )
    elif ext == ".md":
        loaded_docs = await asyncio.to_thread(
            MarkdownDocumentLoader().load_bytes, raw_bytes, filename, role
        )
        parser_used = "markdown"
    elif ext == ".csv":
        loaded_docs = await asyncio.to_thread(
            CSVDocumentLoader().load_bytes, raw_bytes, filename, role
        )
        parser_used = "csv"
    else:
        raise ValueError(f"Unsupported file format for indexing: {filename}")

    if not loaded_docs:
        raise ValueError(f"Document '{filename}' produced empty text during extraction")

    if cancel_check is not None:
        await cancel_check()

    if progress_callback is not None:
        await progress_callback(1, 4, f"Parsed '{filename}' via {parser_used}; chunking…")

    if ext == ".csv":
        chunker = CSVSemanticChunker()
    elif ext == ".md" or loaded_docs[0].metadata.get("format") == "markdown":
        chunker = MarkdownSemanticChunker()
    else:
        chunker = PDFSemanticChunker()

    splits: list[Document] = []
    for doc in loaded_docs:
        splits.extend(await asyncio.to_thread(chunker.chunk, doc))

    if not splits:
        raise ValueError(f"Document '{filename}' produced zero chunks")

    full_text = "\n\n".join(doc.page_content for doc in loaded_docs)

    async with async_session() as db:
        await db.execute(
            update(DocumentRecord)
            .where(DocumentRecord.id == doc_id)
            .values(total_chunks=len(splits), embedded_chunks=0, parser_used=parser_used)
        )
        await db.commit()

    if progress_callback is not None:
        await progress_callback(2, 4, f"Generating contextual headers for {len(splits)} chunks…")

    enriched_chunks = await contextualize_chunks(splits, full_text, filename)

    if cancel_check is not None:
        await cancel_check()

    if progress_callback is not None:
        await progress_callback(3, 4, f"Embedding {len(enriched_chunks)} chunks (1536d)…")

    vectors = await get_embeddings_service().aembed_documents(enriched_chunks)

    if cancel_check is not None:
        await cancel_check()

    store = get_hybrid_store()
    committed_count = await store.replace_document_chunks(
        doc_id=doc_id,
        role=role,
        source=filename,
        chunks=enriched_chunks,
        vectors=vectors,
        parser_used=parser_used,
    )

    if progress_callback is not None:
        await progress_callback(4, 4, f"Committed {committed_count} chunks.")

    return {
        "doc_id": doc_id,
        "filename": filename,
        "role": role,
        "parser_used": parser_used,
        "chunks_committed": committed_count,
    }


def _sync_dispatch_taskiq(coro_fn, *args) -> None:
    """Best-effort dispatch helper for sync compatibility shims."""
    try:
        asyncio.get_running_loop()
        # Caller is inside an active loop; API routes should call broker tasks directly.
        return
    except RuntimeError:
        asyncio.run(coro_fn(*args))


def run_indexer() -> None:
    """Queue indexing jobs for all unembedded documents (embedded=0)."""
    from app.workers.tasks import enqueue_pending_documents

    _sync_dispatch_taskiq(enqueue_pending_documents)


def trigger_retry_pending() -> None:
    """Reset failed documents to pending (embedded=0) and enqueue durable worker jobs."""
    from app.workers.tasks import enqueue_retry_failed_job

    _sync_dispatch_taskiq(enqueue_retry_failed_job)


def trigger_full_reindex() -> dict:
    """Mark active docs pending (preserving live chunks until committed) and enqueue full reindex."""
    with sync_session() as db:
        total = int(db.scalar(select(func.count()).select_from(DocumentRecord)) or 0)
        db.execute(update(DocumentRecord).values(embedded=0, embedded_chunks=0, last_error=None))
        db.commit()
    return {"queued_docs": total, "pruned_orphan_docs": 0}


# ════════════════════════════════════════════════════════════════════════════════
#  PROMPT & QUERY EXPANSION
# ════════════════════════════════════════════════════════════════════════════════


def build_system_prompt(user_role: str) -> str:
    return (
        f"You are FinSight, an enterprise-grade AI assistant built to help organizations "
        f"manage and analyze their business data across all departments — including HR, "
        f"Finance, Marketing, Engineering, Operations, and more.\n"
        f"The user has role: **{user_role.title()}**.\n\n"
        "STRICT RULES — YOU MUST FOLLOW ALL OF THESE:\n"
        "1. Answer ONLY using information explicitly stated in the Context below. "
        "DO NOT use external knowledge, assumptions, or information from your training data.\n"
        "2. If the Context does not contain enough information to answer the question, "
        "respond exactly with: 'I could not find relevant information about this topic "
        "in your accessible documents.'\n"
        "3. DO NOT include inline citations, source tags, or file references (such as [source: filename.ext]) in your response. "
        "Keep the text clean, natural, and highly readable. The user interface will automatically present the source documents separately.\n"
        "5. If the user asks about a specific document that is NOT present in the Context, "
        "clearly state that the document was not found. Do NOT make up content.\n"
        "6. Structure your response with Markdown: headers (##), **bold**, bullet points, "
        "and tables where appropriate.\n"
        "7. For data or statistics, use well-formatted markdown tables with clear column headers.\n"
        "8. Be concise and precise. Do not add filler or repeat information unnecessarily.\n"
        "\nContext:\n{context}"
    )


def expand_query(question: str) -> list[str]:
    """Generate semantic query variants cleanly using lazy get_chat_model()."""
    queries = [question]
    try:
        prompt = (
            "You are a search query expansion assistant. Generate 3 alternative "
            "versions of the user's search query to improve document retrieval.\n"
            "Rules:\n"
            "- Each query should capture a different semantic angle.\n"
            "- Output exactly 3 lines, one query per line. No numbering, no explanation.\n"
            f"User Query: {question}"
        )
        response = get_chat_model().invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        for line in content.strip().split("\n"):
            cleaned = re.sub(r"^[-*•\d\.\s]+", "", line).strip()
            if cleaned and cleaned not in queries and len(queries) < 4:
                queries.append(cleaned)
    except Exception as exc:
        logger.debug(f"[QueryExpansion] Skipped ({type(exc).__name__})")
    return queries


# ════════════════════════════════════════════════════════════════════════════════
#  HYBRID PGVECTOR + TSVECTOR RETRIEVER
# ════════════════════════════════════════════════════════════════════════════════


class HybridMultiQueryRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_role: str
    cohere_key: str | None = None
    min_relevance_score: float = 0.15

    def _search_fts5(self, query: str, limit: int = 25) -> list[Document]:
        """Run role-scoped PostgreSQL TSVector lexical search."""
        return get_hybrid_store().lexical_search(query, self.user_role, limit=limit)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun = None,
    ) -> List[Document]:
        store = get_hybrid_store()
        queries = expand_query(query)
        logger.info(f"[Retrieval] Multi-Query variants={len(queries)} role={self.user_role}")

        candidates_map: dict[str, Document] = {}
        rrf_scores: dict[str, float] = {}

        for variant in queries:
            try:
                docs = store.search(
                    variant,
                    self.user_role,
                    limit=12,
                    rerank=False,
                    cohere_key=self.cohere_key,
                )
            except Exception as exc:
                logger.warning(f"[Retrieval] Hybrid variant search failed: {exc}")
                docs = []

            for rank, doc in enumerate(docs):
                key = str(doc.metadata.get("chunk_id") or hash(doc.page_content))
                if key not in candidates_map:
                    candidates_map[key] = doc
                rrf_scores[key] = rrf_scores.get(key, 0.0) + float(
                    doc.metadata.get("rrf_score") or (1.0 / (60.0 + rank + 1))
                )

        fused = sorted(
            candidates_map.values(),
            key=lambda d: rrf_scores.get(str(d.metadata.get("chunk_id") or hash(d.page_content)), 0.0),
            reverse=True,
        )[:30]

        if not fused:
            return []

        return store._rerank_if_configured(
            query=query,
            candidates=fused,
            top_n=6,
            cohere_key=self.cohere_key or cohere_api_key,
        )

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager=None,
    ) -> List[Document]:
        store = get_hybrid_store()
        queries = await asyncio.to_thread(expand_query, query)

        async def _run_variant(q: str) -> list[Document]:
            try:
                return await store.asearch(
                    q,
                    self.user_role,
                    limit=12,
                    rerank=False,
                    cohere_key=self.cohere_key,
                )
            except Exception as exc:
                logger.warning(f"[Retrieval] Async hybrid variant search failed: {exc}")
                return []

        variant_results = await asyncio.gather(*(_run_variant(q) for q in queries))
        candidates_map: dict[str, Document] = {}
        rrf_scores: dict[str, float] = {}

        for docs in variant_results:
            for rank, doc in enumerate(docs):
                key = str(doc.metadata.get("chunk_id") or hash(doc.page_content))
                if key not in candidates_map:
                    candidates_map[key] = doc
                rrf_scores[key] = rrf_scores.get(key, 0.0) + float(
                    doc.metadata.get("rrf_score") or (1.0 / (60.0 + rank + 1))
                )

        fused = sorted(
            candidates_map.values(),
            key=lambda d: rrf_scores.get(str(d.metadata.get("chunk_id") or hash(d.page_content)), 0.0),
            reverse=True,
        )[:30]

        if not fused:
            return []

        return await asyncio.to_thread(
            store._rerank_if_configured,
            query,
            fused,
            6,
            self.cohere_key or cohere_api_key,
        )


# ════════════════════════════════════════════════════════════════════════════════
#  RAG CHAIN
# ════════════════════════════════════════════════════════════════════════════════


class _DynamicModelAnswerRunnable(Runnable):
    """Stream tokens through LCEL StrOutputParser while keeping lazy/patchable model lookup."""

    def invoke(self, input, config=None, **kwargs):
        active_model = get_chat_model()
        if isinstance(active_model, Runnable):
            return (active_model | StrOutputParser()).invoke(input, config=config)
        response = active_model.invoke(input)
        return response.content if hasattr(response, "content") else str(response)

    async def astream(self, input, config=None, **kwargs):
        active_model = get_chat_model()
        if isinstance(active_model, Runnable):
            async for chunk in (active_model | StrOutputParser()).astream(input, config=config):
                if chunk:
                    yield chunk
        else:
            response = await asyncio.to_thread(active_model.invoke, input)
            text_out = response.content if hasattr(response, "content") else str(response)
            if text_out:
                yield text_out


def get_rag_chain(user_role: str, cohere_api_key: str | None = None):
    """
    Build a composable LCEL RAG chain supporting sync .invoke() and async .astream().
    """
    retriever = HybridMultiQueryRetriever(
        user_role=user_role,
        cohere_key=cohere_api_key,
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", build_system_prompt(user_role)),
            ("human", "{input}"),
        ]
    )

    def format_docs(docs: list[Document]) -> str:
        parts = []
        for doc in docs:
            src = doc.metadata.get("source", "unknown")
            parts.append(f"--- SOURCE: {src} ---\n{doc.page_content}\n--- END SOURCE ---")
        return "\n\n".join(parts)

    async def _aretrieve(x):
        return await retriever._aget_relevant_documents(x["input"])

    retrieval = RunnablePassthrough.assign(
        context=RunnableLambda(
            func=lambda x: retriever.invoke(x["input"]),
            afunc=_aretrieve,
        )
    )
    answer_chain = (
        RunnableLambda(
            lambda x: prompt.format_messages(
                input=x["input"], context=format_docs(x["context"])
            )
        )
        | _DynamicModelAnswerRunnable()
    )
    return retrieval.assign(answer=answer_chain)
