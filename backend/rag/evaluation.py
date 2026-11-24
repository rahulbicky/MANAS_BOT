"""
backend/rag/evaluation.py
-------------------------
Evaluation & Benchmarking harness for ManasBot RAG.
Computes standard Information Retrieval (IR) and RAG metrics:
  - Hit Rate @ K (Recall @ K)
  - Mean Reciprocal Rank (MRR @ K)
  - Context Precision @ K
  - Query Latency (P50, P95, Mean in ms)
"""
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from .retriever import aretrieve_relevant_chunks, RetrievedChunk


class BenchmarkItem(BaseModel):
    """Single test item for RAG evaluation."""
    query: str
    relevant_keywords: List[str]
    expected_doc_names: Optional[List[str]] = None


class EvaluationMetrics(BaseModel):
    """Aggregate evaluation scores."""
    total_queries: int
    hit_rate_at_k: float
    mrr_at_k: float
    context_precision_at_k: float
    avg_latency_ms: float
    p95_latency_ms: float


async def evaluate_retrieval(
    dataset: List[BenchmarkItem],
    tenant_id: str,
    top_k: int = 5,
    threshold: float = 0.55,
) -> EvaluationMetrics:
    """Runs the retrieval pipeline over a benchmark dataset and calculates IR metrics."""
    if not dataset:
        return EvaluationMetrics(
            total_queries=0,
            hit_rate_at_k=0.0,
            mrr_at_k=0.0,
            context_precision_at_k=0.0,
            avg_latency_ms=0.0,
            p95_latency_ms=0.0,
        )

    hits = 0
    reciprocal_ranks: List[float] = []
    precisions: List[float] = []
    latencies: List[float] = []

    for item in dataset:
        t0 = time.perf_counter()
        try:
            retrieved: List[RetrievedChunk] = await aretrieve_relevant_chunks(
                tenant_id=tenant_id,
                query=item.query,
                top_k=top_k,
                threshold=threshold,
            )
        except Exception:
            retrieved = []
        lat_ms = (time.perf_counter() - t0) * 1000
        latencies.append(lat_ms)

        # Check relevance
        relevant_indices = []
        for idx, chunk in enumerate(retrieved):
            content_lower = chunk.chunk_text.lower()
            fname_lower = (chunk.filename or "").lower()

            is_rel = any(kw.lower() in content_lower for kw in item.relevant_keywords)
            if item.expected_doc_names and not is_rel:
                is_rel = any(doc_name.lower() in fname_lower for doc_name in item.expected_doc_names)

            if is_rel:
                relevant_indices.append(idx)

        # 1. Hit Rate
        if relevant_indices:
            hits += 1
            # 2. Reciprocal Rank (1 / (rank + 1))
            first_rank = relevant_indices[0] + 1
            reciprocal_ranks.append(1.0 / first_rank)
        else:
            reciprocal_ranks.append(0.0)

        # 3. Context Precision
        if retrieved:
            precisions.append(len(relevant_indices) / len(retrieved))
        else:
            precisions.append(0.0)

    latencies.sort()
    p95_idx = int(0.95 * len(latencies)) if latencies else 0

    return EvaluationMetrics(
        total_queries=len(dataset),
        hit_rate_at_k=round(hits / len(dataset), 4),
        mrr_at_k=round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
        context_precision_at_k=round(sum(precisions) / len(precisions), 4),
        avg_latency_ms=round(sum(latencies) / len(latencies), 2),
        p95_latency_ms=round(latencies[p95_idx], 2) if latencies else 0.0,
    )
