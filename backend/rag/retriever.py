"""
backend/rag/retriever.py
------------------------
Semantic retrieval engine for ManasBot Advanced RAG.
Generates query embeddings with E5 'query: ' prefix, performs cosine similarity search
with strict tenant_id isolation, applies similarity thresholds, and returns top-K chunks.
"""
import re
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Tuple
import logging
import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..database import get_tenant_session, DocumentChunk, KnowledgeDocument
from .embedder import embed_query, aembed_query, EMBEDDING_DIM

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
DEFAULT_SIMILARITY_THRESHOLD = 0.65
MULTILINGUAL_ADAPTED_THRESHOLD = 0.58
RRF_K = 60


def is_cross_lingual_or_non_ascii(text: str) -> bool:
    """Check if query contains non-ASCII characters (e.g. Hindi, Arabic, Chinese, Russian, emojis)."""
    return any(ord(c) >= 128 for c in text)


def deduplicate_chunks(chunks: List["RetrievedChunk"], threshold: float = 0.90) -> List["RetrievedChunk"]:
    """Remove redundant/duplicate chunks to prevent monopolization of LLM context window."""
    unique: List[RetrievedChunk] = []
    seen_texts = set()

    for c in chunks:
        norm = " ".join(c.chunk_text.strip().lower().split())
        if norm in seen_texts:
            continue
        # Check high token overlap with already selected
        is_dup = False
        words_c = set(norm.split())
        if len(words_c) > 5:
            for u in unique:
                words_u = set(" ".join(u.chunk_text.strip().lower().split()).split())
                if words_u:
                    jaccard = len(words_c & words_u) / max(1, len(words_c | words_u))
                    if jaccard >= threshold:
                        is_dup = True
                        break
        if not is_dup:
            seen_texts.add(norm)
            unique.append(c)
    return unique


def rerank_chunks(query: str, candidates: List["RetrievedChunk"], top_n: int = DEFAULT_TOP_K) -> List["RetrievedChunk"]:
    """
    Cross-encoder style re-ranking combining bi-encoder cosine similarity,
    exact phrase matching, and token overlap density.
    """
    if not candidates:
        return []

    q_words = [w.lower() for w in re.findall(r'\w+', query) if len(w) >= 2]
    q_lower = query.lower().strip()

    scored: List[Tuple[float, RetrievedChunk]] = []
    for c in candidates:
        text_lower = c.chunk_text.lower()
        base_score = c.similarity_score

        # Exact phrase bonus
        phrase_bonus = 0.15 if len(q_lower) > 5 and q_lower in text_lower else 0.0

        # Keyword term density bonus
        if q_words:
            matched_terms = sum(1 for w in q_words if w in text_lower)
            term_bonus = 0.15 * (matched_terms / len(q_words))
        else:
            term_bonus = 0.0

        final_score = min(1.0, round(base_score * 0.70 + phrase_bonus + term_bonus, 4))
        scored.append((final_score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    reranked = []
    for score, chunk in scored:
        chunk.similarity_score = max(chunk.similarity_score, score)
        reranked.append(chunk)

    return deduplicate_chunks(reranked)[:top_n]


@dataclass
class RetrievedChunk:
    """Structured representation of a semantically retrieved document chunk."""
    chunk_id: str
    document_id: str
    filename: str
    chunk_text: str
    chunk_index: int
    similarity_score: float

    def to_dict(self) -> dict:
        return asdict(self)


def retrieve_relevant_chunks(
    tenant_id: str,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    db: Optional[Session] = None,
) -> List[RetrievedChunk]:
    """
    Retrieve top-K most semantically relevant document chunks for a query.
    Enforces strict row-level tenant isolation (WHERE tenant_id = :tenant_id).

    Args:
        tenant_id: Tenant UUID.
        query: User's question or search query.
        top_k: Maximum number of chunks to return (default: 5).
        threshold: Minimum cosine similarity score (0.0 to 1.0, default: 0.65).
        db: Optional existing SQLAlchemy session. If None, opens a short-lived session.

    Returns:
        List of RetrievedChunk objects ordered by descending similarity score.
    """
    if not query or not query.strip():
        return []

    effective_threshold = MULTILINGUAL_ADAPTED_THRESHOLD if is_cross_lingual_or_non_ascii(query) else threshold

    # 1. Generate query embedding (prefixes with 'query: ')
    query_vector = embed_query(query)
    if not query_vector or len(query_vector) != EMBEDDING_DIM:
        logger.warning(f"[retriever] Failed to generate valid query vector for query: {query[:50]}")
        return []

    # 2. Database query with session management
    should_close = False
    if db is None:
        try:
            db = get_tenant_session(tenant_id)
            should_close = True
        except ValueError:
            logger.warning(f"[retriever] Tenant '{tenant_id}' not found or is inactive.")
            return []

    try:
        dialect_name = db.bind.dialect.name if db.bind else "postgresql"

        # ── PostgreSQL with pgvector (Production Neon) ───────────────────
        if dialect_name == "postgresql":
            # pgvector <=> is cosine distance; cosine similarity = 1 - (embedding <=> query_vec)
            sql = text("""
                SELECT
                    dc.id AS chunk_id,
                    dc.document_id,
                    kd.filename,
                    dc.chunk_text,
                    dc.chunk_index,
                    1 - (dc.embedding <=> CAST(:query_vector AS vector)) AS similarity_score
                FROM document_chunks dc
                JOIN knowledge_documents kd ON dc.document_id = kd.id
                WHERE dc.tenant_id = :tenant_id
                  AND dc.is_active = TRUE
                  AND kd.is_active = TRUE
                ORDER BY dc.embedding <=> CAST(:query_vector AS vector)
                LIMIT :limit;
            """)
            vector_str = f"[{','.join(str(x) for x in query_vector)}]"
            rows = db.execute(
                sql,
                {
                    "query_vector": vector_str,
                    "tenant_id": tenant_id,
                    "limit": top_k * 2,  # Fetch slightly more candidates to apply threshold
                }
            ).fetchall()

            results: List[RetrievedChunk] = []
            for row in rows:
                score = float(row.similarity_score)
                if score >= effective_threshold:
                    results.append(
                        RetrievedChunk(
                            chunk_id=str(row.chunk_id),
                            document_id=str(row.document_id),
                            filename=str(row.filename),
                            chunk_text=str(row.chunk_text),
                            chunk_index=int(row.chunk_index),
                            similarity_score=round(score, 4),
                        )
                    )
            return rerank_chunks(query, results, top_n=top_k)

        # ── SQLite Fallback (In-memory testing & offline local dev) ───────
        else:
            chunks = (
                db.query(DocumentChunk, KnowledgeDocument.filename)
                .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
                .filter(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.is_active == True,
                    KnowledgeDocument.is_active == True,
                )
                .all()
            )

            if not chunks:
                return []

            q_arr = np.array(query_vector, dtype=np.float32)
            candidates: List[RetrievedChunk] = []

            for chunk, filename in chunks:
                raw_emb = chunk.embedding
                if raw_emb is None:
                    continue
                c_arr = np.array(raw_emb, dtype=np.float32)
                # Both q_arr and c_arr are L2 normalized, so dot product = cosine similarity
                score = float(np.dot(q_arr, c_arr))
                if score >= effective_threshold:
                    candidates.append(
                        RetrievedChunk(
                            chunk_id=str(chunk.id),
                            document_id=str(chunk.document_id),
                            filename=str(filename),
                            chunk_text=str(chunk.chunk_text),
                            chunk_index=int(chunk.chunk_index),
                            similarity_score=round(score, 4),
                        )
                    )

            return rerank_chunks(query, candidates, top_n=top_k)

    except Exception as e:
        logger.error(f"[retriever] Semantic retrieval error for tenant {tenant_id}: {e}", exc_info=True)
        return []
    finally:
        if should_close and db:
            db.close()


async def aretrieve_relevant_chunks(
    tenant_id: str,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    db: Optional[Session] = None,
) -> List[RetrievedChunk]:
    """Asynchronously retrieve relevant chunks via worker threadpool."""
    return await run_in_threadpool(
        retrieve_relevant_chunks,
        tenant_id=tenant_id,
        query=query,
        top_k=top_k,
        threshold=threshold,
        db=db,
    )
