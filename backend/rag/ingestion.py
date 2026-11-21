"""
backend/rag/ingestion.py
------------------------
Safe, transactional, and idempotent document ingestion pipeline for ManasBot Advanced RAG.
Orchestrates text chunking, batch embedding generation, and atomic persistence into PostgreSQL + pgvector.
"""
from typing import List, Optional
import logging
from sqlalchemy.orm import Session

from ..database import get_tenant_session, DocumentChunk, KnowledgeDocument
from .chunker import chunk_document, DocumentChunkData, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP
from .embedder import embed_passages

logger = logging.getLogger(__name__)


def ingest_document(
    document_id: str,
    tenant_id: str,
    filename: str,
    file_type: str,
    content: str,
    db: Optional[Session] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    batch_size: int = 32,
) -> int:
    """
    Ingest a document: chunk text, generate 384-d embeddings in batches, and save chunks.
    Ensures idempotence by clearing any existing chunks for document_id first.

    Args:
        document_id: KnowledgeDocument primary key ID.
        tenant_id: Tenant UUID.
        filename: Human-readable file name or URL.
        file_type: Source file extension/type.
        content: Extracted raw text content.
        db: Optional existing SQLAlchemy session. If None, creates a short-lived session.
        chunk_size: Max characters per chunk (default: 600).
        chunk_overlap: Overlap between consecutive chunks (default: 100).
        batch_size: Embedding generation batch size (default: 32).

    Returns:
        Total number of chunks successfully created and stored.
    """
    if not content or not content.strip():
        logger.warning(f"[ingestion] Empty content provided for document_id={document_id}; skipping chunking.")
        return 0

    # 1. Chunk document
    chunk_data_list: List[DocumentChunkData] = chunk_document(
        content=content,
        document_id=document_id,
        tenant_id=tenant_id,
        filename=filename,
        file_type=file_type,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    if not chunk_data_list:
        return 0

    # 2. Batch generate embeddings (with E5 'passage: ' prefix)
    passages = [c.chunk_text for c in chunk_data_list]
    embeddings = embed_passages(passages, batch_size=batch_size)

    if len(embeddings) != len(chunk_data_list):
        raise RuntimeError(
            f"Embedding count mismatch: expected {len(chunk_data_list)}, got {len(embeddings)}"
        )

    # 3. Transactional persistence
    should_close = False
    if db is None:
        db = get_tenant_session(tenant_id)
        should_close = True

    try:
        # Clear existing chunks for this document (idempotence)
        db.query(DocumentChunk).filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
        ).delete(synchronize_session=False)

        # Create chunk entities
        db_chunks = []
        for cdata, emb in zip(chunk_data_list, embeddings):
            chunk_entity = DocumentChunk(
                document_id=document_id,
                tenant_id=tenant_id,
                chunk_index=cdata.chunk_index,
                chunk_text=cdata.chunk_text,
                token_count=cdata.token_count,
                embedding=emb,
                is_active=True,
            )
            db_chunks.append(chunk_entity)

        db.add_all(db_chunks)
        db.commit()
        logger.info(
            f"[ingestion] Successfully ingested document '{filename}' "
            f"({len(db_chunks)} chunks embedded & persisted for tenant {tenant_id})."
        )
        return len(db_chunks)

    except Exception as e:
        db.rollback()
        logger.error(f"[ingestion] Failed to ingest document {document_id} for tenant {tenant_id}: {e}", exc_info=True)
        raise
    finally:
        if should_close and db:
            db.close()


def delete_document_chunks(
    document_id: str,
    tenant_id: str,
    db: Optional[Session] = None,
    soft_delete: bool = True,
) -> int:
    """
    Deactivate or remove all chunks associated with a document.

    Args:
        document_id: KnowledgeDocument primary key ID.
        tenant_id: Tenant UUID.
        db: Optional existing SQLAlchemy session.
        soft_delete: If True, sets is_active=False; if False, deletes rows.

    Returns:
        Number of chunks affected.
    """
    should_close = False
    if db is None:
        db = get_tenant_session(tenant_id)
        should_close = True

    try:
        q = db.query(DocumentChunk).filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
        )

        if soft_delete:
            count = q.update({"is_active": False}, synchronize_session=False)
        else:
            count = q.delete(synchronize_session=False)

        db.commit()
        logger.info(f"[ingestion] {'Soft-deleted' if soft_delete else 'Hard-deleted'} {count} chunks for doc {document_id}")
        return count
    except Exception as e:
        db.rollback()
        logger.error(f"[ingestion] Failed to delete chunks for doc {document_id}: {e}")
        raise
    finally:
        if should_close and db:
            db.close()


def reingest_document(
    document_id: str,
    tenant_id: str,
    filename: str,
    file_type: str,
    content: Optional[str] = None,
    new_content: Optional[str] = None,
    db: Optional[Session] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    batch_size: int = 32,
) -> int:
    """
    Rebuild chunks and embeddings when document content changes (e.g. URL re-scrape).
    Accepts either `content` or `new_content`.
    """
    text_content = content if content is not None else (new_content or "")
    return ingest_document(
        document_id=document_id,
        tenant_id=tenant_id,
        filename=filename,
        file_type=file_type,
        content=text_content,
        db=db,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        batch_size=batch_size,
    )
