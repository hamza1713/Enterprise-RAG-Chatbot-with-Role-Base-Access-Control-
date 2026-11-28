"""
app/rag/processors.py — Document loading (Docling-Serve + pdfplumber/MD/CSV bytes) and chunking.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from io import BytesIO, StringIO
import json
import logging
import os
from pathlib import Path
import re

import httpx
import pandas as pd
import pdfplumber
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import (
    DOCLING_SERVE_URL,
    DOCLING_TIMEOUT_SECONDS,
    GEMINI_LIGHT_MODEL,
    generate_content_with_fallback,
    get_genai_client,
)

logger = logging.getLogger("FinSight.processors")


# ═══════════════════════════════════════════════════════════════════════════════
#  LOADING STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════════


class DocumentLoaderStrategy(ABC):
    """Abstract Strategy for loading documents from file paths or raw bytes."""

    @abstractmethod
    def load(self, filepath: str, role: str) -> list[Document]:
        """Load a file from local disk and return a list of LangChain Documents."""

    def load_bytes(self, data: bytes, filename: str, role: str) -> list[Document]:
        """Load a document directly from raw bytes."""
        raise NotImplementedError


class CSVDocumentLoader(DocumentLoaderStrategy):
    def load(self, filepath: str, role: str) -> list[Document]:
        return self.load_bytes(Path(filepath).read_bytes(), Path(filepath).name, role, filepath=filepath)

    def load_bytes(
        self,
        data: bytes,
        filename: str,
        role: str,
        filepath: str = "",
    ) -> list[Document]:
        df = pd.read_csv(BytesIO(data))
        if df.empty:
            return []
        content = df.to_csv(index=False)
        return [
            Document(
                page_content=content,
                metadata={
                    "role": role.lower(),
                    "source": filename,
                    "filepath": filepath or filename,
                    "parser_used": "csv",
                },
            )
        ]


class MarkdownDocumentLoader(DocumentLoaderStrategy):
    def load(self, filepath: str, role: str) -> list[Document]:
        return self.load_bytes(Path(filepath).read_bytes(), Path(filepath).name, role, filepath=filepath)

    def load_bytes(
        self,
        data: bytes,
        filename: str,
        role: str,
        filepath: str = "",
    ) -> list[Document]:
        content = data.decode("utf-8", errors="replace")
        if not content.strip():
            return []
        return [
            Document(
                page_content=content,
                metadata={
                    "role": role.lower(),
                    "source": filename,
                    "filepath": filepath or filename,
                    "parser_used": "markdown",
                },
            )
        ]


def _format_table_as_markdown(table: list[list[str | None]]) -> str:
    """Convert a 2D list of cells from pdfplumber into a clean GitHub Flavored Markdown table."""
    if not table or not any(row for row in table):
        return ""
    cleaned_rows = []
    for row in table:
        cleaned_row = [re.sub(r"\s+", " ", str(cell or "").strip()) for cell in row]
        if any(cleaned_row):
            cleaned_rows.append(cleaned_row)
    if not cleaned_rows:
        return ""
    num_cols = max(len(r) for r in cleaned_rows)
    norm_rows = [r + [""] * (num_cols - len(r)) for r in cleaned_rows]
    headers = [col or f"Col_{i+1}" for i, col in enumerate(norm_rows[0])]
    separator = ["---"] * num_cols
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in norm_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


class PDFDocumentLoader(DocumentLoaderStrategy):
    def load(self, filepath: str, role: str) -> list[Document]:
        return self.load_bytes(
            Path(filepath).read_bytes(),
            Path(filepath).name,
            role,
            filepath=filepath,
        )

    def load_bytes(
        self,
        data: bytes,
        filename: str,
        role: str,
        filepath: str = "",
    ) -> list[Document]:
        pages_content: list[str] = []
        scanned_pages: list[int] = []
        has_tables = False
        try:
            with pdfplumber.open(BytesIO(data)) as pdf:
                for idx, page in enumerate(pdf.pages):
                    page_num = idx + 1
                    text = page.extract_text() or ""
                    tables = page.extract_tables() or []

                    formatted_tables = []
                    for t in tables:
                        md_table = _format_table_as_markdown(t)
                        if md_table:
                            formatted_tables.append(md_table)
                            has_tables = True

                    page_body = text.strip()
                    if formatted_tables:
                        tables_block = (
                            f"\n\n**Structured Tables (Page {page_num}):**\n"
                            + "\n\n".join(formatted_tables)
                        )
                        page_body = (
                            (page_body + "\n\n" + tables_block).strip()
                            if page_body
                            else tables_block
                        )

                    if not page_body and getattr(page, "images", None):
                        scanned_pages.append(page_num)
                        page_body = (
                            f"[Notice: Page {page_num} contains image content with no extractable text layer. "
                            "Scanned PDF document.]"
                        )

                    if page_body:
                        pages_content.append(f"--- Page {page_num} ---\n{page_body}")
        except Exception as exc:
            logger.error(f"[PDF Loader] Error parsing {filename}: {exc}")
            raise
        if not pages_content:
            return []
        full_content = "\n\n".join(pages_content)
        metadata: dict = {
            "role": role.lower(),
            "source": filename,
            "filepath": filepath or filename,
            "has_tables": has_tables,
            "has_scanned_pages": len(scanned_pages) > 0,
            "parser_used": "pdfplumber",
            "format": "pdf_pages",
        }
        if scanned_pages:
            metadata["scanned_pages"] = ",".join(str(p) for p in scanned_pages)
        return [Document(page_content=full_content, metadata=metadata)]


class DoclingServePDFParser:
    """
    Client for the docling-serve-cpu sidecar (/v1/convert/file) with automatic
    fallback to PDFDocumentLoader (pdfplumber) when unavailable or misconfigured.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.base_url = (
            (base_url if base_url is not None else os.getenv("DOCLING_SERVE_URL", DOCLING_SERVE_URL))
            .strip()
            .rstrip("/")
        )
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("DOCLING_TIMEOUT_SECONDS", str(DOCLING_TIMEOUT_SECONDS))
        )

    @staticmethod
    def _extract_markdown(payload: dict) -> str:
        if not isinstance(payload, dict):
            return ""
        doc_obj = payload.get("document")
        if isinstance(doc_obj, dict):
            md = doc_obj.get("md_content") or doc_obj.get("markdown") or ""
            if isinstance(md, str) and md.strip():
                return md.strip()
        for key in ("md_content", "markdown"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    async def parse_bytes(
        self,
        data: bytes,
        filename: str,
        role: str,
    ) -> list[Document]:
        if self.base_url:
            endpoint = f"{self.base_url}/v1/convert/file"
            options = json.dumps({"to_formats": ["md"], "do_ocr": True})
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.post(
                        endpoint,
                        files={"files": (filename, data, "application/pdf")},
                        data={"options": options},
                    )
                    resp.raise_for_status()
                    md_content = self._extract_markdown(resp.json())
                    if md_content:
                        return [
                            Document(
                                page_content=md_content,
                                metadata={
                                    "role": role.lower(),
                                    "source": filename,
                                    "filepath": filename,
                                    "parser_used": "docling",
                                    "format": "markdown",
                                },
                            )
                        ]
                    logger.warning(
                        f"[Docling] Empty Markdown response for '{filename}'; falling back to pdfplumber."
                    )
            except Exception as exc:
                logger.warning(
                    f"[Docling] Sidecar unavailable/failed for '{filename}' ({exc}); falling back to pdfplumber."
                )

        fallback_loader = PDFDocumentLoader()
        return await asyncio.to_thread(fallback_loader.load_bytes, data, filename, role)


class DocumentLoaderFactory:
    """Factory: returns the correct loader for a given file path or filename."""

    @staticmethod
    def get_loader(filepath: str) -> DocumentLoaderStrategy:
        ext = Path(filepath).suffix.lower()
        if ext == ".csv":
            return CSVDocumentLoader()
        if ext == ".md":
            return MarkdownDocumentLoader()
        if ext == ".pdf":
            return PDFDocumentLoader()
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
        role = doc.metadata.get("role", "general")
        name = doc.metadata.get("source", "unknown")
        df = None
        if filepath and Path(filepath).is_file():
            try:
                df = pd.read_csv(filepath)
            except Exception:
                df = None
        if df is None:
            df = pd.read_csv(StringIO(doc.page_content))
        if df.empty:
            return []
        cols = df.columns.tolist()
        cols_str = ", ".join(str(c) for c in cols)
        chunks: list[Document] = []

        for start in range(0, len(df), self.rows_per_chunk):
            batch = df.iloc[start : start + self.rows_per_chunk]
            lines = []
            for _, row in batch.iterrows():
                lines.append("---")
                lines.extend(f"{c}: {row[c]}" for c in cols)
            content = "\n".join(lines)
            chunks.append(
                Document(
                    page_content=(
                        f"Document: {name}\n"
                        f"Columns: {cols_str}\n"
                        f"Rows: {start+1} to {min(start+self.rows_per_chunk, len(df))} of {len(df)}\n"
                        f"Content:\n{content}"
                    ),
                    metadata={
                        "role": role.lower(),
                        "source": name,
                        "chunk_type": "csv_rows",
                        "doc_title": name,
                    },
                )
            )

        summary_prompt = (
            f"Generate a concise summary of the CSV dataset '{name}'.\n"
            f"It has {len(df)} rows and columns: {cols_str}.\n"
            f"Preview:\n\"\"\"\n{df.head(3).to_string()}\n\"\"\"\n\n"
            f"Explain what kind of data this dataset contains and what queries it might answer. Under 4 sentences."
        )
        try:
            summary_text = generate_content_with_fallback(
                get_genai_client(), summary_prompt, preferred_model=GEMINI_LIGHT_MODEL
            )
        except Exception:
            summary_text = (
                f"CSV dataset '{name}' containing {len(df)} rows and columns: {cols_str}."
            )
        chunks.append(
            Document(
                page_content=(
                    f"Document Summary: {name}\nType: CSV Dataset\n"
                    f"Columns: {cols_str}\nTotal Rows: {len(df)}\nSummary:\n{summary_text}"
                ),
                metadata={
                    "role": role.lower(),
                    "source": name,
                    "chunk_type": "doc_summary",
                    "doc_title": name,
                },
            )
        )
        return chunks


class MarkdownSemanticChunker(ChunkingStrategy):
    """Chunks Markdown by header sections while keeping Markdown tables intact where possible."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        self.chunk_size = chunk_size
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

    def _split_preserving_tables(self, section_text: str) -> list[str]:
        """Split narrative text cleanly while keeping contiguous Markdown table blocks whole."""
        blocks: list[tuple[bool, list[str]]] = []
        current_lines: list[str] = []
        current_is_table: bool | None = None

        for line in section_text.splitlines():
            is_table_line = line.lstrip().startswith("|")
            if current_is_table is None:
                current_is_table = is_table_line
                current_lines.append(line)
            elif is_table_line == current_is_table:
                current_lines.append(line)
            else:
                blocks.append((current_is_table, current_lines))
                current_is_table = is_table_line
                current_lines = [line]
        if current_lines and current_is_table is not None:
            blocks.append((current_is_table, current_lines))

        results: list[str] = []
        for is_table, lines in blocks:
            text_block = "\n".join(lines).strip()
            if not text_block:
                continue
            if is_table and len(text_block) <= max(self.chunk_size * 2, 1800):
                results.append(text_block)
            else:
                results.extend(self.splitter.split_text(text_block))
        return results

    def chunk(self, doc: Document) -> list[Document]:
        content = doc.page_content
        role = doc.metadata.get("role", "general")
        name = doc.metadata.get("source", "unknown")

        sections: list[dict] = []
        current_headers = {i: "" for i in range(1, 7)}
        current_section_lines: list[str] = []

        for line in content.split("\n"):
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                if current_section_lines:
                    sections.append(
                        {
                            "headers": [v for v in current_headers.values() if v],
                            "content": "\n".join(current_section_lines),
                        }
                    )
                    current_section_lines = []
                level = len(m.group(1))
                current_headers[level] = m.group(2).strip()
                for lv in range(level + 1, 7):
                    current_headers[lv] = ""
                current_section_lines.append(line)
            else:
                current_section_lines.append(line)
        if current_section_lines:
            sections.append(
                {
                    "headers": [v for v in current_headers.values() if v],
                    "content": "\n".join(current_section_lines),
                }
            )

        chunks: list[Document] = []
        header_outline: list[str] = []

        for sec in sections:
            sec_path = " > ".join(sec["headers"]) if sec["headers"] else "General Section"
            if sec_path != "General Section":
                header_outline.append(sec_path)
            for split in self._split_preserving_tables(sec["content"]):
                chunks.append(
                    Document(
                        page_content=f"Document: {name}\nSection: {sec_path}\n---\n{split}",
                        metadata={
                            "role": role.lower(),
                            "source": name,
                            "chunk_type": "text",
                            "doc_title": name,
                            "section_title": sec_path,
                        },
                    )
                )

        outline_str = "\n".join(f"- {h}" for h in header_outline[:15])
        if len(header_outline) > 15:
            outline_str += "\n- ... and more sections"
        summary_prompt = (
            f"Generate a concise summary of the Markdown document '{name}'.\n"
            f"Outline:\n{outline_str}\n\nFirst 1500 chars:\n\"\"\"\n{content[:1500]}\n\"\"\"\n\n"
            f"Provide a 3-4 sentence summary of main purpose and key takeaways."
        )
        try:
            summary_text = generate_content_with_fallback(
                get_genai_client(), summary_prompt, preferred_model=GEMINI_LIGHT_MODEL
            )
        except Exception:
            summary_text = f"Markdown document '{name}' covering multiple sections."
        chunks.append(
            Document(
                page_content=(
                    f"Document Summary: {name}\nOutline:\n{outline_str}\nSummary:\n{summary_text}"
                ),
                metadata={
                    "role": role.lower(),
                    "source": name,
                    "chunk_type": "doc_summary",
                    "doc_title": name,
                },
            )
        )
        return chunks


class PDFSemanticChunker(ChunkingStrategy):
    """Chunks PDFs by page/paragraph and adds page context."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

    def chunk(self, doc: Document) -> list[Document]:
        # When Docling converted the PDF to layout-aware Markdown, delegate to MarkdownSemanticChunker.
        if doc.metadata.get("format") == "markdown":
            return MarkdownSemanticChunker(chunk_size=1000, chunk_overlap=150).chunk(doc)

        content = doc.page_content
        role = doc.metadata.get("role", "general")
        name = doc.metadata.get("source", "unknown")

        page_blocks = re.split(r"--- Page (\d+) ---", content)
        pages: list[tuple[str, str]] = []
        if len(page_blocks) > 1:
            for idx in range(1, len(page_blocks), 2):
                page_num = page_blocks[idx].strip()
                page_text = page_blocks[idx + 1].strip() if idx + 1 < len(page_blocks) else ""
                if page_text:
                    pages.append((page_num, page_text))
        else:
            pages.append(("1", content))

        chunks: list[Document] = []
        for page_num, page_text in pages:
            for split in self.splitter.split_text(page_text):
                chunks.append(
                    Document(
                        page_content=f"Document: {name}\nPage: {page_num}\n---\n{split}",
                        metadata={
                            "role": role.lower(),
                            "source": name,
                            "chunk_type": "text",
                            "doc_title": name,
                            "page_number": page_num,
                        },
                    )
                )

        summary_prompt = (
            f"Generate a concise summary of the PDF document '{name}'.\n"
            f"It has {len(pages)} pages. First page text:\n\"\"\"\n"
            f"{pages[0][1][:1500] if pages else ''}\n\"\"\"\n\n"
            f"3-4 sentence summary of content, main purpose, and key takeaways."
        )
        try:
            summary_text = generate_content_with_fallback(
                get_genai_client(), summary_prompt, preferred_model=GEMINI_LIGHT_MODEL
            )
        except Exception:
            summary_text = f"PDF document '{name}' containing {len(pages)} pages."
        chunks.append(
            Document(
                page_content=(
                    f"Document Summary: {name}\nTotal Pages: {len(pages)}\nSummary:\n{summary_text}"
                ),
                metadata={
                    "role": role.lower(),
                    "source": name,
                    "chunk_type": "doc_summary",
                    "doc_title": name,
                },
            )
        )
        return chunks


class ChunkerFactory:
    """Factory: returns the correct chunker for a given file path or filename."""

    @staticmethod
    def get_chunker(filepath: str) -> ChunkingStrategy:
        ext = Path(filepath).suffix.lower()
        if ext == ".csv":
            return CSVSemanticChunker()
        if ext == ".md":
            return MarkdownSemanticChunker()
        if ext == ".pdf":
            return PDFSemanticChunker()
        raise ValueError(f"Unsupported file format: {ext}")
