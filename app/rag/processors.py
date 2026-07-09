"""
app/rag/processors.py — Document loading and chunking strategies.

Renamed from `app/rag_utils/document_processors.py`.
Updated to import from `app.core.config` instead of the old secret_key module.
All strategy classes preserved exactly.
"""

import os
import re
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd
import pdfplumber
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from google import genai

from app.core.config import google_api_key, generate_content_with_fallback

_client = genai.Client(api_key=google_api_key or "DUMMY")


# ═══════════════════════════════════════════════════════════════════════════════
#  LOADING STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════════

class DocumentLoaderStrategy(ABC):
    """Abstract Strategy for loading documents from different file formats."""
    @abstractmethod
    def load(self, filepath: str, role: str) -> list[Document]:
        """Load a file and return a list of raw LangChain Documents."""
        pass


class CSVDocumentLoader(DocumentLoaderStrategy):
    def load(self, filepath: str, role: str) -> list[Document]:
        df = pd.read_csv(filepath)
        if df.empty:
            return []
        name    = Path(filepath).name
        content = df.to_csv(index=False)
        return [Document(
            page_content=content,
            metadata={"role": role.lower(), "source": name, "filepath": filepath},
        )]


class MarkdownDocumentLoader(DocumentLoaderStrategy):
    def load(self, filepath: str, role: str) -> list[Document]:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return []
        name = Path(filepath).name
        return [Document(
            page_content=content,
            metadata={"role": role.lower(), "source": name, "filepath": filepath},
        )]


class PDFDocumentLoader(DocumentLoaderStrategy):
    def load(self, filepath: str, role: str) -> list[Document]:
        name          = Path(filepath).name
        pages_content: list[str] = []
        try:
            with pdfplumber.open(filepath) as pdf:
                for idx, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text and text.strip():
                        pages_content.append(f"--- Page {idx + 1} ---\n{text}")
        except Exception as exc:
            print(f"[PDF Loader] Error parsing {name}: {exc}")
            raise
        if not pages_content:
            return []
        full_content = "\n\n".join(pages_content)
        return [Document(
            page_content=full_content,
            metadata={"role": role.lower(), "source": name, "filepath": filepath},
        )]


class DocumentLoaderFactory:
    """Factory: returns the correct loader for a given file path."""
    @staticmethod
    def get_loader(filepath: str) -> DocumentLoaderStrategy:
        ext = Path(filepath).suffix.lower()
        if ext == ".csv": return CSVDocumentLoader()
        if ext == ".md":  return MarkdownDocumentLoader()
        if ext == ".pdf": return PDFDocumentLoader()
        raise ValueError(f"Unsupported file format: {ext}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CHUNKING STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════════

class ChunkingStrategy(ABC):
    @abstractmethod
    def chunk(self, doc: Document) -> list[Document]:
        pass


class CSVSemanticChunker(ChunkingStrategy):
    """Chunks CSVs by batching rows and adding column metadata."""
    def __init__(self, rows_per_chunk: int = 20):
        self.rows_per_chunk = rows_per_chunk

    def chunk(self, doc: Document) -> list[Document]:
        filepath = doc.metadata.get("filepath", "")
        role     = doc.metadata.get("role", "general")
        name     = doc.metadata.get("source", "unknown")
        try:
            df = pd.read_csv(filepath)
        except Exception:
            from io import StringIO
            df = pd.read_csv(StringIO(doc.page_content))
        if df.empty:
            return []
        cols     = df.columns.tolist()
        cols_str = ", ".join(cols)
        chunks:  list[Document] = []

        # Row batches
        for start in range(0, len(df), self.rows_per_chunk):
            batch = df.iloc[start: start + self.rows_per_chunk]
            lines = []
            for _, row in batch.iterrows():
                lines.append("---")
                lines.extend(f"{c}: {row[c]}" for c in cols)
            content = "\n".join(lines)
            chunks.append(Document(
                page_content=(
                    f"Document: {name}\n"
                    f"Columns: {cols_str}\n"
                    f"Rows: {start+1} to {min(start+self.rows_per_chunk, len(df))} of {len(df)}\n"
                    f"Content:\n{content}"
                ),
                metadata={"role": role.lower(), "source": name, "chunk_type": "csv_rows", "doc_title": name},
            ))

        # Summary chunk
        summary_prompt = (
            f"Generate a concise summary of the CSV dataset '{name}'.\n"
            f"It has {len(df)} rows and columns: {cols_str}.\n"
            f"Preview:\n\"\"\"\n{df.head(3).to_string()}\n\"\"\"\n\n"
            f"Explain what kind of data this dataset contains and what queries it might answer. Under 4 sentences."
        )
        try:
            summary_text = generate_content_with_fallback(_client, summary_prompt)
        except Exception:
            summary_text = f"CSV dataset '{name}' containing {len(df)} rows and columns: {cols_str}."
        chunks.append(Document(
            page_content=(
                f"Document Summary: {name}\nType: CSV Dataset\n"
                f"Columns: {cols_str}\nTotal Rows: {len(df)}\nSummary:\n{summary_text}"
            ),
            metadata={"role": role.lower(), "source": name, "chunk_type": "doc_summary", "doc_title": name},
        ))
        return chunks


class MarkdownSemanticChunker(ChunkingStrategy):
    """Chunks Markdown by header sections, prepending section paths."""
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 150):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        )

    def chunk(self, doc: Document) -> list[Document]:
        content = doc.page_content
        role    = doc.metadata.get("role", "general")
        name    = doc.metadata.get("source", "unknown")

        sections: list[dict]     = []
        current_headers          = {i: "" for i in range(1, 7)}
        current_section_lines:   list[str] = []

        for line in content.split("\n"):
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                if current_section_lines:
                    sections.append({
                        "headers": [v for v in current_headers.values() if v],
                        "content": "\n".join(current_section_lines),
                    })
                    current_section_lines = []
                level = len(m.group(1))
                current_headers[level] = m.group(2).strip()
                for lv in range(level + 1, 7):
                    current_headers[lv] = ""
                current_section_lines.append(line)
            else:
                current_section_lines.append(line)
        if current_section_lines:
            sections.append({
                "headers": [v for v in current_headers.values() if v],
                "content": "\n".join(current_section_lines),
            })

        chunks:        list[Document] = []
        header_outline: list[str]     = []

        for sec in sections:
            sec_path = " > ".join(sec["headers"]) if sec["headers"] else "General Section"
            if sec_path != "General Section":
                header_outline.append(sec_path)
            for split in self.splitter.split_text(sec["content"]):
                chunks.append(Document(
                    page_content=(
                        f"Document: {name}\nSection: {sec_path}\n---\n{split}"
                    ),
                    metadata={
                        "role": role.lower(), "source": name,
                        "chunk_type": "text", "doc_title": name, "section_title": sec_path,
                    },
                ))

        outline_str  = "\n".join(f"- {h}" for h in header_outline[:15])
        if len(header_outline) > 15:
            outline_str += "\n- ... and more sections"
        summary_prompt = (
            f"Generate a concise summary of the Markdown document '{name}'.\n"
            f"Outline:\n{outline_str}\n\nFirst 1500 chars:\n\"\"\"\n{content[:1500]}\n\"\"\"\n\n"
            f"Provide a 3-4 sentence summary of main purpose and key takeaways."
        )
        try:
            summary_text = generate_content_with_fallback(_client, summary_prompt)
        except Exception:
            summary_text = f"Markdown document '{name}' covering multiple sections."
        chunks.append(Document(
            page_content=(
                f"Document Summary: {name}\nOutline:\n{outline_str}\nSummary:\n{summary_text}"
            ),
            metadata={"role": role.lower(), "source": name, "chunk_type": "doc_summary", "doc_title": name},
        ))
        return chunks


class PDFSemanticChunker(ChunkingStrategy):
    """Chunks PDFs by page/paragraph and adds page context."""
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        )

    def chunk(self, doc: Document) -> list[Document]:
        content = doc.page_content
        role    = doc.metadata.get("role", "general")
        name    = doc.metadata.get("source", "unknown")

        page_blocks = re.split(r"--- Page (\d+) ---", content)
        pages: list[tuple[str, str]] = []
        if len(page_blocks) > 1:
            for idx in range(1, len(page_blocks), 2):
                page_num  = page_blocks[idx].strip()
                page_text = page_blocks[idx + 1].strip() if idx + 1 < len(page_blocks) else ""
                if page_text:
                    pages.append((page_num, page_text))
        else:
            pages.append(("1", content))

        chunks: list[Document] = []
        for page_num, page_text in pages:
            for split in self.splitter.split_text(page_text):
                chunks.append(Document(
                    page_content=(
                        f"Document: {name}\nPage: {page_num}\n---\n{split}"
                    ),
                    metadata={
                        "role": role.lower(), "source": name,
                        "chunk_type": "text", "doc_title": name, "page_number": page_num,
                    },
                ))

        summary_prompt = (
            f"Generate a concise summary of the PDF document '{name}'.\n"
            f"It has {len(pages)} pages. First page text:\n\"\"\"\n"
            f"{pages[0][1][:1500] if pages else ''}\n\"\"\"\n\n"
            f"3-4 sentence summary of content, main purpose, and key takeaways."
        )
        try:
            summary_text = generate_content_with_fallback(_client, summary_prompt)
        except Exception:
            summary_text = f"PDF document '{name}' containing {len(pages)} pages."
        chunks.append(Document(
            page_content=(
                f"Document Summary: {name}\nTotal Pages: {len(pages)}\nSummary:\n{summary_text}"
            ),
            metadata={"role": role.lower(), "source": name, "chunk_type": "doc_summary", "doc_title": name},
        ))
        return chunks


class ChunkerFactory:
    """Factory: returns the correct chunker for a given file path."""
    @staticmethod
    def get_chunker(filepath: str) -> ChunkingStrategy:
        ext = Path(filepath).suffix.lower()
        if ext == ".csv": return CSVSemanticChunker()
        if ext == ".md":  return MarkdownSemanticChunker()
        if ext == ".pdf": return PDFSemanticChunker()
        raise ValueError(f"Unsupported file format: {ext}")
