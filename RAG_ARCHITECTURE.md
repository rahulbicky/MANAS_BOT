# ManasBot — Advanced RAG Architecture

## 1. Document Ingestion Pipeline

The ManasBot Retrieval-Augmented Generation (RAG) subsystem ingests structured and unstructured business documents and transforms them into searchable vector embeddings:

```
[Uploaded Document / URL]
       │
       ▼
[Parser & Text Extractor]
 (PyPDF2, python-docx, pandas, BeautifulSoup)
       │
       ▼
[Normalization & Cleaning]
 (Unicode normalization, whitespace stripping)
       │
       ▼
[Intelligent Chunker]
 (Chunk size: 600 chars, Overlap: 100 chars, SHA-256 content hashing)
       │
       ▼
[Multilingual FastEmbed Embedder]
 (intfloat/multilingual-e5-small, 384 dimensions, CPU ONNX)
       │
       ▼
[Vector Store & HNSW Index]
 (pgvector with cosine distance in Postgres / JSON in SQLite)
```

---

## 2. Ingestion Parameters & Embedding Model

- **Embedding Model**: `intfloat/multilingual-e5-small`
- **Embedding Dimension**: 384 dimensions (L2-normalized)
- **FastEmbed ONNX Runtime**: Runs in-process on CPU without requiring GPU infrastructure or external third-party embedding API calls.
- **Prefixes**:
  - Ingestion passages: `"passage: "`
  - Search queries: `"query: "`
- **Chunk Size**: 600 characters (~120–150 tokens)
- **Chunk Overlap**: 100 characters (~20–25 tokens)
- **Deduplication at Ingestion**: Each chunk calculates a SHA-256 `content_hash` to detect duplicate content.

---

## 3. Retrieval, Deduplication & Reranking Pipeline

Retrieval operates in multiple stages to maximize precision while minimizing context dilution:

```
[User Query]
       │
       ▼
[Conversational Coreference Rewriter]
 (Resolves "it", "that", "cost" from recent conversation turns)
       │
       ▼
[FastEmbed Query Embedder]
 (query: <text> -> 384d vector)
       │
       ▼
[Cosine Distance Vector Search]
 (Filtered by tenant_id, top_k = 4, threshold = 0.65)
       │
       ▼
[Dynamic Multilingual Threshold Adaptation]
 (If query contains Indic / CJK / Non-ASCII, adapt threshold to 0.58)
       │
       ▼
[Jaccard Token Deduplication]
 (Filters near-duplicate chunks sharing >90% token overlap)
       │
       ▼
[Cross-Encoder Scoring & Reranking]
 (Blends vector similarity [70%], exact query match [15%], and density [15%])
       │
       ▼
[Top-N Relevant Context Chunks]
```

---

## 4. Evaluation & Benchmarking Harness

ManasBot features an automated evaluation module (`backend/rag/evaluation.py`):
- **Hit Rate @ K**: Measures the percentage of test queries where at least one ground-truth document chunk appears in the top-K retrieved results.
- **Mean Reciprocal Rank (MRR @ K)**: Evaluates the rank position of the first relevant chunk (`1 / rank`).
- **Context Precision**: The fraction of retrieved chunks that contain relevant factual keywords.
- **Latency Profiling**: Measures P50, P95, and mean query latency in milliseconds.
