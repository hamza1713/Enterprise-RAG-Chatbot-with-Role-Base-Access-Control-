"""
app/rag_utils/document_processors.py — Deprecated shim.

All logic has moved to app.rag.processors.
"""
from app.rag.processors import (  # noqa: F401
    DocumentLoaderStrategy,
    CSVDocumentLoader,
    MarkdownDocumentLoader,
    PDFDocumentLoader,
    DocumentLoaderFactory,
    ChunkingStrategy,
    CSVSemanticChunker,
    MarkdownSemanticChunker,
    PDFSemanticChunker,
    ChunkerFactory,
)
