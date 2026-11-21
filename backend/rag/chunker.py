"""
backend/rag/chunker.py
----------------------
Intelligent document chunking engine for ManasBot Advanced RAG.
Splits text into semantically coherent chunks using RecursiveCharacterTextSplitter,
preserving paragraph and sentence boundaries, metadata, and token estimates.
"""
from dataclasses import dataclass, asdict
from typing import List, Optional
import logging
import math

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


@dataclass
class DocumentChunkData:
    """Structured representation of an individual document chunk."""
    chunk_index: int
    chunk_text: str
    token_count: int
    document_id: str
    tenant_id: str
    filename: str
    file_type: str

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_token_count(text: str) -> int:
    """
    Estimate token count for text.
    For standard multilingual text, average word to token ratio is ~1.3.
    For CJK/Asian scripts without whitespace, character length is used.
    """
    if not text:
        return 0
    words = text.split()
    if len(words) > 0:
        return max(1, math.ceil(len(words) * 1.3))
    return max(1, math.ceil(len(text) / 2))


def chunk_document(
    content: str,
    document_id: str,
    tenant_id: str,
    filename: str,
    file_type: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    separators: Optional[List[str]] = None,
) -> List[DocumentChunkData]:
    """
    Split a document's content into overlapping chunks with associated metadata.

    Args:
        content: Raw text content of the document.
        document_id: Foreign key ID of the parent KnowledgeDocument.
        tenant_id: Tenant UUID for strict multi-tenant isolation.
        filename: Human-readable original filename or URL.
        file_type: File extension or source type (pdf, docx, txt, url, etc.).
        chunk_size: Maximum character count per chunk (default: 600).
        chunk_overlap: Character overlap between consecutive chunks (default: 100).
        separators: Custom hierarchy of separator strings.

    Returns:
        List of DocumentChunkData objects ordered by chunk_index.
    """
    if not content or not content.strip():
        logger.debug(f"[chunker] Document {filename} (id={document_id}) is empty or whitespace; returning 0 chunks.")
        return []

    if separators is None:
        separators = DEFAULT_SEPARATORS

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators,
        keep_separator=True,
    )

    raw_chunks = splitter.split_text(content.strip())
    chunks: List[DocumentChunkData] = []

    for idx, chunk_str in enumerate(raw_chunks):
        cleaned_str = chunk_str.strip()
        if not cleaned_str:
            continue

        tokens = estimate_token_count(cleaned_str)
        chunks.append(
            DocumentChunkData(
                chunk_index=idx,
                chunk_text=cleaned_str,
                token_count=tokens,
                document_id=document_id,
                tenant_id=tenant_id,
                filename=filename,
                file_type=file_type,
            )
        )

    logger.info(
        f"[chunker] Split document '{filename}' ({len(content)} chars) "
        f"into {len(chunks)} chunks (size={chunk_size}, overlap={chunk_overlap})."
    )
    return chunks
