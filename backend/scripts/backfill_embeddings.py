"""
backend/scripts/backfill_embeddings.py
--------------------------------------
Idempotent management CLI script to chunk and embed existing KnowledgeDocument records.

Usage Examples:
    # 1. Dry run across all tenants (read-only preview):
    python -m backend.scripts.backfill_embeddings --dry-run

    # 2. Process a specific tenant:
    python -m backend.scripts.backfill_embeddings --tenant-id <tenant_uuid>

    # 3. Force re-indexing of all documents:
    python -m backend.scripts.backfill_embeddings --force

    # 4. Custom batch size:
    python -m backend.scripts.backfill_embeddings --batch-size 25
"""
import argparse
import logging
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

from backend.database import get_tenant_session, _get_central_session, KnowledgeDocument, DocumentChunk, CentralTenant
from backend.rag.ingestion import ingest_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_embeddings")


def backfill_documents(
    tenant_id: str = None,
    batch_size: int = 10,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Backfill embeddings for active knowledge documents that lack chunks.
    """
    session = _get_central_session()
    stats = {
        "total_documents": 0,
        "already_indexed": 0,
        "processed_documents": 0,
        "total_chunks_created": 0,
        "failed_documents": 0,
    }

    try:
        # Build query for target documents
        query = session.query(KnowledgeDocument).filter(KnowledgeDocument.is_active == True)
        if tenant_id:
            query = query.filter(KnowledgeDocument.tenant_id == tenant_id)

        docs = query.order_by(KnowledgeDocument.created_at.asc()).all()
        stats["total_documents"] = len(docs)

        logger.info(
            f"Found {len(docs)} active documents matching criteria "
            f"(tenant={tenant_id or 'ALL'}, force={force}, dry_run={dry_run})."
        )

        for idx, doc in enumerate(docs, 1):
            doc_id = doc.id
            doc_tenant = doc.tenant_id
            doc_filename = doc.filename or "unknown"
            doc_type = doc.file_type or "txt"
            content = doc.content or ""

            # Check existing chunks count
            existing_chunks_count = (
                session.query(DocumentChunk)
                .filter(DocumentChunk.document_id == doc_id, DocumentChunk.is_active == True)
                .count()
            )

            if existing_chunks_count > 0 and not force:
                logger.info(f"[{idx}/{len(docs)}] SKIP: '{doc_filename}' (id={doc_id}) already has {existing_chunks_count} chunks.")
                stats["already_indexed"] += 1
                continue

            if not content.strip():
                logger.warning(f"[{idx}/{len(docs)}] SKIP: '{doc_filename}' (id={doc_id}) has empty content.")
                continue

            if dry_run:
                logger.info(f"[{idx}/{len(docs)}] DRY-RUN: Would chunk '{doc_filename}' ({len(content)} chars).")
                stats["processed_documents"] += 1
                continue

            try:
                chunks_created = ingest_document(
                    document_id=doc_id,
                    tenant_id=doc_tenant,
                    filename=doc_filename,
                    file_type=doc_type,
                    content=content,
                    db=session,
                    batch_size=batch_size,
                )
                stats["processed_documents"] += 1
                stats["total_chunks_created"] += chunks_created
                logger.info(f"[{idx}/{len(docs)}] SUCCESS: '{doc_filename}' -> {chunks_created} chunks.")
            except Exception as e:
                stats["failed_documents"] += 1
                logger.error(f"[{idx}/{len(docs)}] FAILED to index '{doc_filename}': {e}")

        logger.info(
            f"\n=== BACKFILL COMPLETE ===\n"
            f"Total Documents: {stats['total_documents']}\n"
            f"Already Indexed: {stats['already_indexed']}\n"
            f"Processed: {stats['processed_documents']}\n"
            f"Chunks Created: {stats['total_chunks_created']}\n"
            f"Failed: {stats['failed_documents']}\n"
        )
        return stats
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Backfill vector embeddings for ManasBot knowledge base documents.")
    parser.add_argument("--tenant-id", type=str, default=None, help="Specific tenant ID to process.")
    parser.add_argument("--batch-size", type=int, default=10, help="Embedding generation batch size (default: 10).")
    parser.add_argument("--force", action="store_true", help="Force re-indexing even if chunks exist.")
    parser.add_argument("--dry-run", action="store_true", help="Preview documents to index without writing to DB.")

    args = parser.parse_args()
    backfill_documents(
        tenant_id=args.tenant_id,
        batch_size=args.batch_size,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
