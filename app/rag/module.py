"""
app/rag/module.py — Production-grade RAG engine.

Renamed from `app/rag_utils/rag_module.py`.
All logic preserved exactly; only the import paths have been updated
to use the new `app.core.config` and `app.rag.processors` modules.

Key design points:
  - Quota vs rate-limit are correctly distinguished.
  - API retry-delay is extracted from the error message.
  - _pause_on_quota_exhaustion marks ONLY the currently-failing document.
  - expand_query is wrapped in asyncio.to_thread.
  - Vectorstore singleton is protected by a threading.Lock.
  - _reinit_vectorstore() replaces every reference in module scope.
"""

import os, time, re, threading, sqlite3, queue, asyncio
from pathlib import Path
from typing import List

# Apply RAG env-vars before any LangChain imports
import app.rag.config  # noqa: F401 — side-effect: sets GOOGLE_API_KEY etc.

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from pydantic import ConfigDict

try:
    from langchain_cohere import CohereRerank
    from langchain.retrievers import ContextualCompressionRetriever
    _COHERE_AVAILABLE = True
except ImportError:
    _COHERE_AVAILABLE = False

from app.core.config import google_api_key, cohere_api_key
from app.core.database import get_db_conn


# ════════════════════════════════════════════════════════════════════════════════
#  ERROR CLASSIFICATION  (single source of truth)
# ════════════════════════════════════════════════════════════════════════════════

def _classify_api_error(err: Exception) -> str:
    s = str(err).lower()
    hard_quota_signals = ["quota", "billing", "plan_limit", "exceeded your"]
    if any(sig in s for sig in hard_quota_signals):
        return "hard_quota"
    if "429" in s or "resource exhausted" in s or "too many requests" in s:
        return "transient_rate_limit"
    return "other"


def _parse_retry_delay(err: Exception, default: float) -> float:
    s = str(err)
    proto_match = re.search(r"retry_delay\s*\{[^}]*seconds:\s*(\d+)", s, re.IGNORECASE | re.DOTALL)
    if proto_match:
        return float(proto_match.group(1)) + 2.0
    text_match = re.search(r"retry[_ ]in\s+(\d+\.?\d*)\s*s", s, re.IGNORECASE)
    if text_match:
        return float(text_match.group(1)) + 2.0
    return default


# ════════════════════════════════════════════════════════════════════════════════
#  EMBEDDINGS — retrying wrapper
# ════════════════════════════════════════════════════════════════════════════════

class RetryingEmbeddings(GoogleGenerativeAIEmbeddings):
    """
    Wraps GoogleGenerativeAIEmbeddings with smart retry logic:
    - Transient 429 → wait the API-suggested delay, retry up to 10 times
    - Hard quota     → raise immediately (caller decides what to do)
    - Other errors   → raise immediately
    """
    _INITIAL_DELAY: float = 2.0
    _MAX_DELAY:     float = 120.0

    def _retry(self, fn, label: str):
        delay = self._INITIAL_DELAY
        for attempt in range(10):
            try:
                return fn()
            except Exception as exc:
                kind = _classify_api_error(exc)
                if kind == "hard_quota":
                    raise
                if kind == "transient_rate_limit" and attempt < 9:
                    wait = min(_parse_retry_delay(exc, delay), self._MAX_DELAY)
                    print(
                        f"[Embeddings] 429 on {label} — API says wait {wait:.1f}s "
                        f"(attempt {attempt + 1}/10)"
                    )
                    time.sleep(wait)
                    delay = min(delay * 2.0, self._MAX_DELAY)
                    continue
                raise

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        batch_size = 100
        results: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start: start + batch_size]
            embeddings = self._retry(
                lambda b=batch: super(RetryingEmbeddings, self).embed_documents(b),
                label=f"batch {start // batch_size + 1}",
            )
            results.extend(embeddings)
        return results

    def embed_query(self, text: str) -> list[float]:
        return self._retry(
            lambda: super(RetryingEmbeddings, self).embed_query(text),
            label="query",
        )


# ── Vectorstore singleton + write lock ────────────────────────────────────────
google_embeddings = RetryingEmbeddings(
    model="models/gemini-embedding-2-preview",
    google_api_key=google_api_key or "DUMMY_KEY",
    transport="rest",
    request_options={"timeout": 15.0},
)

_vs_lock = threading.Lock()

vectorstore = Chroma(
    collection_name="my_collection",
    persist_directory="chroma_db",
    embedding_function=google_embeddings,
)


# ── Self-healing: dimension mismatch ─────────────────────────────────────────

def _reset_databases(reason: str) -> None:
    """Wipe Chroma on disk and reset SQLite embed flags. Call _reinit_vectorstore() after."""
    import shutil
    print(f"[Chroma] Resetting DB ({reason})…")
    shutil.rmtree("chroma_db", ignore_errors=True)
    os.makedirs("chroma_db", exist_ok=True)
    Path("chroma_db/.semantic_chunking_migrated").unlink(missing_ok=True)
    try:
        conn = get_db_conn()
        conn.execute("UPDATE documents SET embedded=0, total_chunks=0, embedded_chunks=0")
        conn.commit()
        conn.close()
        print("[Chroma] SQLite reset — all files will be re-indexed.")
    except Exception as exc:
        print(f"[Chroma] SQLite reset error: {exc}")


def _reinit_vectorstore() -> None:
    """Re-instantiate the global vectorstore singleton. Must be called after _reset_databases()."""
    global vectorstore
    with _vs_lock:
        vectorstore = Chroma(
            collection_name="my_collection",
            persist_directory="chroma_db",
            embedding_function=google_embeddings,
        )
    try:
        Path("chroma_db/.semantic_chunking_migrated").touch()
    except Exception:
        pass
    print("[Chroma] Vectorstore singleton re-initialised.")


# Dimension-mismatch self-heal on startup
try:
    vectorstore.similarity_search("test", k=1)
except Exception as _e:
    if "dimension" in str(_e).lower():
        _reset_databases(f"dimension mismatch: {_e}")
        _reinit_vectorstore()

# Semantic-chunking migration check
_mig_flag = Path("chroma_db/.semantic_chunking_migrated")
if not _mig_flag.exists():
    _reset_databases("migrating to semantic chunking")
    _reinit_vectorstore()


# ════════════════════════════════════════════════════════════════════════════════
#  DOCUMENT INDEXER — single background worker via Queue
# ════════════════════════════════════════════════════════════════════════════════

from app.rag.processors import DocumentLoaderFactory, ChunkerFactory

_index_queue:    queue.Queue    = queue.Queue()
_worker_started: bool           = False
_worker_lock:    threading.Lock = threading.Lock()


def start_indexer_worker() -> None:
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            t = threading.Thread(target=_indexer_worker, daemon=True, name="IndexerWorker")
            t.start()
            _worker_started = True
            print("[Indexer] Background worker thread started.")


def trigger_indexing() -> None:
    start_indexer_worker()
    _index_queue.put(True)


def run_indexer() -> None:
    """Public compatibility shim for lifespan / upload endpoints."""
    trigger_indexing()


def trigger_retry_pending() -> None:
    """Reset failed docs back to pending and re-trigger the worker."""
    try:
        conn = get_db_conn()
        conn.execute("UPDATE documents SET embedded=0, embedded_chunks=0 WHERE embedded=-1")
        conn.commit()
        conn.close()
        print("[Indexer] Failed documents reset to pending for retry.")
    except Exception as exc:
        print(f"[Indexer] Error resetting failed docs: {exc}")
    trigger_indexing()


def _indexer_worker() -> None:
    while True:
        try:
            _index_queue.get()
            _run_indexing_loop()
            _index_queue.task_done()
        except Exception as exc:
            print(f"[IndexerWorker] Unexpected error: {exc}")
            time.sleep(2.0)


def _mark_failed(doc_id: int) -> None:
    try:
        conn = get_db_conn()
        conn.execute("UPDATE documents SET embedded=-1 WHERE id=?", (doc_id,))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[Indexer] Error marking doc {doc_id} failed: {exc}")


def _mark_embedded(doc_id: int) -> None:
    try:
        conn = get_db_conn()
        conn.execute("UPDATE documents SET embedded=1 WHERE id=?", (doc_id,))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[Indexer] Error marking doc {doc_id} embedded: {exc}")


def _run_indexing_loop() -> None:
    """Process every unembedded (embedded=0) document in order."""
    while True:
        try:
            conn = get_db_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, filepath, role FROM documents WHERE embedded=0"
            ).fetchall()
            conn.close()
        except Exception as exc:
            print(f"[Indexer] Failed to query SQLite: {exc}")
            time.sleep(2.0)
            break

        if not rows:
            break

        for row in rows:
            doc_id   = row["id"]
            filepath = row["filepath"]
            role     = row["role"]
            name     = Path(filepath).name
            print(f"[Indexer] ▶ {name} (role={role}, id={doc_id})")

            # 1. Load
            try:
                loader = DocumentLoaderFactory.get_loader(filepath)
                docs   = loader.load(filepath, role)
            except Exception as load_err:
                kind = _classify_api_error(load_err)
                print(f"[Indexer] ✗ Load failed for {name}: {load_err}")
                if kind == "hard_quota":
                    _handle_hard_quota(doc_id, "load")
                    return
                _mark_failed(doc_id)
                continue

            if not docs:
                print(f"[Indexer] ⚠ {name} loaded empty.")
                _mark_failed(doc_id)
                continue

            # 2. Chunk
            try:
                chunker = ChunkerFactory.get_chunker(filepath)
                splits: list[Document] = []
                for doc in docs:
                    splits.extend(chunker.chunk(doc))
            except Exception as chunk_err:
                kind = _classify_api_error(chunk_err)
                print(f"[Indexer] ✗ Chunk failed for {name}: {chunk_err}")
                if kind == "hard_quota":
                    _handle_hard_quota(doc_id, "chunking")
                    return
                _mark_failed(doc_id)
                continue

            if not splits:
                print(f"[Indexer] ⚠ {name} produced no chunks.")
                _mark_failed(doc_id)
                continue

            # 3. Embed & write to vectorstore
            try:
                _embed_chunks_to_vectorstore(splits, doc_id=doc_id)
                _mark_embedded(doc_id)
                print(f"[Indexer] ✓ {name} — {len(splits)} chunks indexed.")
            except Exception as embed_err:
                kind = _classify_api_error(embed_err)
                print(f"[Indexer] ✗ Embed failed for {name}: {embed_err}")
                if kind == "hard_quota":
                    _handle_hard_quota(doc_id, "embedding")
                    return
                if kind == "transient_rate_limit":
                    wait = _parse_retry_delay(embed_err, 30.0)
                    print(f"[Indexer] Rate-limit on {name} — waiting {wait:.0f}s before next doc.")
                    _mark_failed(doc_id)
                    time.sleep(wait)
                    continue
                _mark_failed(doc_id)


def _handle_hard_quota(current_doc_id: int, phase: str) -> None:
    print(
        f"[Indexer] 🛑 Hard quota exhaustion during '{phase}' "
        f"(doc_id={current_doc_id}). "
        f"Marking this doc failed; other pending docs untouched — "
        f"use 'Retry Failed/Pending' when quota is restored."
    )
    _mark_failed(current_doc_id)


_CHROMA_BATCH = 100


def _embed_chunks_to_vectorstore(splits: list[Document], doc_id: int) -> None:
    """Embed in batches of 100, updating SQLite chunk progress after each batch."""
    total = len(splits)
    try:
        conn = get_db_conn()
        conn.execute(
            "UPDATE documents SET total_chunks=?, embedded_chunks=0 WHERE id=?",
            (total, doc_id),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[Indexer] Warning: couldn't set total_chunks: {exc}")

    done = 0
    for start in range(0, total, _CHROMA_BATCH):
        batch = splits[start: start + _CHROMA_BATCH]
        with _vs_lock:
            vectorstore.add_documents(batch)
        done += len(batch)
        try:
            conn = get_db_conn()
            conn.execute(
                "UPDATE documents SET embedded_chunks=? WHERE id=?",
                (min(done, total), doc_id),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"[Indexer] Warning: couldn't update embedded_chunks: {exc}")


# ════════════════════════════════════════════════════════════════════════════════
#  PROMPT & MODEL
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


model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    google_api_key=google_api_key or "DUMMY_KEY",
    transport="rest",
).with_fallbacks([
    ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0.2,
                           google_api_key=google_api_key or "DUMMY_KEY", transport="rest"),
])


# ════════════════════════════════════════════════════════════════════════════════
#  QUERY EXPANSION
# ════════════════════════════════════════════════════════════════════════════════

def expand_query(question: str) -> list[str]:
    """Generate up to 3 semantic variants of the user query."""
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
        response = model.invoke(prompt)
        for line in response.content.strip().split("\n"):
            cleaned = re.sub(r"^[-*•\d\.\s]+", "", line).strip()
            if cleaned and cleaned not in queries and len(queries) < 4:
                queries.append(cleaned)
    except Exception as exc:
        print(f"[QueryExpansion] Skipped ({type(exc).__name__})")
    return queries


# ════════════════════════════════════════════════════════════════════════════════
#  HYBRID MULTI-QUERY RETRIEVER
# ════════════════════════════════════════════════════════════════════════════════

class HybridMultiQueryRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_role:            str
    cohere_key:           str | None = None
    min_relevance_score:  float = 0.15

    def _build_role_filter(self) -> dict | None:
        role_lower = self.user_role.lower()
        if role_lower == "c-level":   return None
        if role_lower == "general":   return {"role": "general"}
        return {"role": {"$in": [role_lower, "general"]}}

    def _search_with_scores(self, query: str, role_filter: dict | None, k: int = 15) -> list[tuple]:
        try:
            kwargs: dict = {"query": query, "k": k}
            if role_filter:
                kwargs["filter"] = role_filter
            return vectorstore.similarity_search_with_relevance_scores(**kwargs)
        except Exception:
            search_kwargs: dict = {"k": k}
            if role_filter:
                search_kwargs["filter"] = role_filter
            docs = vectorstore.similarity_search(query, **search_kwargs)
            return [(doc, 1.0) for doc in docs]

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun = None,
    ) -> List[Document]:
        role_filter = self._build_role_filter()
        queries     = expand_query(query)
        print(f"[Retrieval] Multi-Query: {queries}")

        all_docs: list[Document] = []
        seen:     set[int]       = set()

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def search_single(q):
            try:
                return self._search_with_scores(q, role_filter, k=20)
            except Exception as exc:
                print(f"[Retrieval] Search failed for variant '{q}': {exc}")
                return []

        with ThreadPoolExecutor(max_workers=len(queries)) as executor:
            futures = {executor.submit(search_single, q): q for q in queries}
            for future in as_completed(futures):
                for doc, score in future.result():
                    if score >= self.min_relevance_score:
                        h = hash(doc.page_content)
                        if h not in seen:
                            seen.add(h)
                            doc.metadata["relevance_score"] = round(score, 4)
                            all_docs.append(doc)

        summary_docs = [d for d in all_docs if d.metadata.get("chunk_type") == "doc_summary"]
        content_docs = [d for d in all_docs if d.metadata.get("chunk_type") != "doc_summary"]
        summary_docs.sort(key=lambda d: d.metadata.get("relevance_score", 0), reverse=True)
        content_docs.sort(key=lambda d: d.metadata.get("relevance_score", 0), reverse=True)
        candidates = (summary_docs + content_docs)[:30]

        print(
            f"[Retrieval] {len(candidates)} candidates "
            f"({len(summary_docs)} summaries + {len(content_docs)} chunks)"
        )

        if not candidates:
            return []

        cohere_key_to_use = self.cohere_key or cohere_api_key
        if cohere_key_to_use and _COHERE_AVAILABLE and len(candidates) > 1:
            try:
                reranker = CohereRerank(
                    cohere_api_key=cohere_key_to_use,
                    model="rerank-english-v3.0",
                    top_n=min(6, len(candidates)),
                )
                reranked = reranker.compress_documents(documents=candidates, query=query)
                print(f"[Retrieval] Cohere → top {len(reranked)} docs")
                return list(reranked)
            except Exception as exc:
                print(f"[Retrieval] Rerank skipped ({type(exc).__name__})")

        return candidates[:6]


# ════════════════════════════════════════════════════════════════════════════════
#  RAG CHAIN
# ════════════════════════════════════════════════════════════════════════════════

def get_rag_chain(user_role: str, cohere_api_key: str | None = None):
    from langchain.prompts import PromptTemplate

    prompt = ChatPromptTemplate.from_messages([
        ("system", build_system_prompt(user_role)),
        ("human", "{input}"),
    ])

    doc_prompt = PromptTemplate.from_template(
        "--- SOURCE: {source} ---\n{page_content}\n--- END SOURCE ---"
    )

    qa_chain = create_stuff_documents_chain(
        model,
        prompt,
        document_prompt=doc_prompt,
        document_separator="\n\n",
    )

    retriever = HybridMultiQueryRetriever(
        user_role=user_role,
        cohere_key=cohere_api_key,
    )

    return create_retrieval_chain(retriever, qa_chain)
