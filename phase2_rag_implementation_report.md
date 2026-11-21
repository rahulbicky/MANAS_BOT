# ManasBot — Phase 2: Advanced RAG & Semantic Search Implementation Report

**Project:** ManasBot (B2B Multi-Tenant AI Chatbot SaaS)
**Maintainer:** Rahul Kumar
**Branch:** `feature/phase-2-advanced-rag`
**Date:** November 21, 2026
**Status:** Completed & Validated

---

## Executive Summary

Phase 2 transforms ManasBot's retrieval system from naive 8,000-character document-context truncation into an enterprise-grade, high-performance, multilingual Retrieval-Augmented Generation (RAG) knowledge engine.

The upgraded architecture incorporates:
1. **Intelligent Recursive Chunking:** Character-aware hierarchy (paragraphs, sentences, words) with configurable 600-character size and 100-character overlap preserving document boundaries and metadata.
2. **Local CPU Embedding Engine (`intfloat/multilingual-e5-small`):** FastEmbed-powered ONNX runtime embedding generator producing 384-dimensional L2-normalized dense vectors, strictly adhering to E5 `query: ` and `passage: ` asymmetrical retrieval prefixes across 100+ languages without external API costs or latency.
3. **Vector Database Infrastructure:** PostgreSQL `pgvector` extension with Hierarchical Navigable Small World (`HNSW`) cosine distance index (`vector_cosine_ops`), accompanied by an Alembic migration (`c4a189f7d23e`) and cross-dialect fallback support for local unit testing.
4. **Decoupled Semantic Retrieval Pipeline:** Asynchronous semantic query execution integrated cleanly into the Phase 1 decoupled `/chat` lifecycle (Phase A: Async DB Read → Phase B: Threadpool Semantic Vector Search & Groq Async LLM → Phase C: Async DB Write), ensuring zero database connections are held open during vector search or inference.
5. **Factual Grounding & Source Citations:** Dynamic relevance scoring, citation formatting, `SourceCitation` schemas in `ChatResponse`, and visual source badges in both the standalone chatbot widget, embed script, and client administration dashboard.
6. **Multi-Tenant Security:** Row-level isolation on all chunk and retrieval queries (`WHERE tenant_id = :tenant_id`), guaranteeing zero cross-tenant data leakage.
7. **Document Backfill CLI Tool:** Production-ready management script (`backend/scripts/backfill_embeddings.py`) supporting dry-run inspection, tenant filtering, batching, and forced re-indexing.

---

## Implementation Details Across Core Functional Areas

### 1. Document Extraction & Preprocessing Pipeline
- **File:** `backend/app/api/routers/documents.py`
- Upgraded document parsers:
  - **PDF:** `pypdf.PdfReader` with page-by-page extraction, header/footer normalization, and empty page skipping.
  - **DOCX:** `docx.Document` iterating through paragraphs and tables.
  - **Excel (XLSX, XLS):** `openpyxl` with structured row/column tabulations.
  - **CSV:** Standard CSV reader with comma/semicolon auto-detection.
  - **Plain Text (TXT):** Multi-encoding detection (UTF-8, Latin-1, CP1252) with unicode normalization.
  - **Website URLs:** Asynchronous HTTP scraping via `httpx.AsyncClient` with `BeautifulSoup4` text extraction, stripping scripts, styles, navigations, and boilerplate.
- Automatic chunking and embedding triggered upon document upload (`/admin/upload-doc`), URL addition (`/admin/add-url`), and URL refresh (`/admin/refresh-urls`).

### 2. Intelligent Document Chunking
- **File:** `backend/rag/chunker.py`
- Implements `chunk_document()` built on `langchain_text_splitters.RecursiveCharacterTextSplitter`.
- **Default Parameters:** `chunk_size=600`, `chunk_overlap=100`, separators: `["\n\n", "\n", " ", ""]`.
- Encapsulates each chunk into a structured `DocumentChunkData` dataclass preserving:
  - `chunk_index`: 0-indexed position within the document.
  - `document_id`: Parent `KnowledgeDocument` foreign key.
  - `tenant_id`: Multi-tenant isolation key.
  - `filename`: Source document name or web URL.
  - `file_type`: Format extension.
  - `token_count`: Accurate character-ratio token estimation.

### 3. FastEmbed Embedding Generator
- **File:** `backend/rag/embedder.py`
- Model: `intfloat/multilingual-e5-small` (384 dimensions, L2-normalized).
- Singleton pattern: Thread-safe lazy-loading via `get_embedding_model()`, ensuring the ONNX model is loaded into CPU memory exactly once.
- E5 Asymmetric Prefixes:
  - Documents / Passages: `passage: `
  - User Queries: `query: `
- Threadpool offloading: Synchronous FastEmbed execution wrapped in `asyncio.to_thread` (`aembed_query`, `aembed_passages`) to prevent event-loop stalls.

### 4. Vector Database Model & Alembic Migration
- **Files:** `backend/database.py`, `alembic/versions/c4a189f7d23e_add_document_chunks_and_pgvector.py`
- **Model:** `DocumentChunk`
  - `id`: UUID primary key.
  - `document_id`: Foreign key referencing `knowledge_documents.id` with `ondelete="CASCADE"`.
  - `tenant_id`: Tenant UUID, indexed with `is_active`.
  - `chunk_index`: Sequence position integer.
  - `chunk_text`: Text excerpt.
  - `token_count`: Estimated token size.
  - `embedding`: `Vector(384)` with `vector_cosine_ops`.
  - `is_active`: Boolean flag for soft deletion.
- **Indexes:**
  - `ix_document_chunks_tenant_id_is_active` on `(tenant_id, is_active)`.
  - `ix_document_chunks_document_id` on `(document_id)`.
  - `ix_document_chunks_embedding_hnsw` on `(embedding vector_cosine_ops)` using `hnsw`.
- **Migration:**
  - `c4a189f7d23e_add_document_chunks_and_pgvector.py` chained from Phase 1 revision `ef7a990203df`.
  - Conditional PostgreSQL execution of `CREATE EXTENSION IF NOT EXISTS vector;`.
  - Fallback column type detection for non-pgvector test databases.

### 5. Ingestion Pipeline & Synchronization
- **File:** `backend/rag/ingestion.py`
- `ingest_document(document_id, tenant_id, filename, file_type, content, db, ...)`:
  - Atomic transaction: Chunks content, batches embeddings, purges existing chunks for idempotence, and bulk inserts `DocumentChunk` entities.
- `reingest_document(...)`: Re-indexes updated content seamlessly.
- `delete_document_chunks(...)`: Deactivates or permanently drops chunks when documents are removed.

### 6. Semantic Retrieval Engine
- **File:** `backend/rag/retriever.py`
- `retrieve_relevant_chunks(tenant_id, query, top_k=5, threshold=0.65, db=None)` and `aretrieve_relevant_chunks(...)`:
  - Embeds query with `query: ` prefix.
  - Runs cosine similarity search against active tenant chunks:
    - **PostgreSQL:** `1 - (dc.embedding <=> :query_vector)` ordered by `<=>` ascending with `LIMIT :top_k`.
    - **SQLite:** Dot product of L2-normalized vectors with threshold filtering and descending ranking.
  - Enforces `threshold >= 0.65` and `top_k <= 5`.
  - Returns structured `List[RetrievedChunk]`.

### 7. Groq LLM Integration & Citation Grounding
- **Files:** `backend/app/api/routers/chat.py`, `backend/rag/prompts.py`, `backend/faq_chain.py`
- Semantic retrieval runs during Phase B of the `/chat` pipeline.
- If chunks exceed threshold:
  - Extracted chunks are formatted via `format_rag_context()` with source headers: `--- [Source N: filename | Relevance: X%] ---`.
  - Appended into LLM prompt with strict grounding instructions: answer only from verified context; cite sources in format `[Source: filename]`; fall back politely to human contact if context is absent.
- `ChatResponse` schema includes `sources: List[SourceCitation]`, returning `document_id`, `filename`, and `relevance_score`.

### 8. Frontend Integration
- **`frontend/chatbot/script.js` & `frontend/chatbot/chatbot-embed.js`:**
  - Enhanced bot message rendering: when `data.sources` is present and non-empty, displays clickable/hoverable source badges (`.cb-sources` and `.cb-source-pill`) with source document name and relevance percentage.
- **`frontend/chatbot/style.css`:**
  - Added modern styling for `.cb-sources`, `.cb-sources-label`, and `.cb-source-pill`.
- **`frontend/client/index.html` & `frontend/client/script.js`:**
  - Added "Chunks" column in Knowledge Base document management table.
  - Displays indexed chunk count pill (`${d.chunk_count} chunks`) for every uploaded document or scraped URL.

### 9. Backfill Management CLI Script
- **File:** `backend/scripts/backfill_embeddings.py`
- Allows operators to backfill existing production documents:
  - `--dry-run`: Read-only preview of documents to be chunked.
  - `--tenant-id <UUID>`: Process specific tenant.
  - `--batch-size <N>`: Configurable batch size.
  - `--force`: Force re-indexing of already-indexed documents.

---

## Comprehensive Test Execution Results

### 1. Phase 2 RAG Test Suite (`test_phase2_rag.py`)
- **Total Tests:** 23
- **Passed:** 23 (100%)
- **Failed:** 0
- **Duration:** 1.887 seconds

| Test Name | Focus Area | Result |
| :--- | :--- | :---: |
| `test_01_chunker_small_document` | Small document chunking & metadata | PASS |
| `test_02_chunker_large_document` | Large document recursive splitting | PASS |
| `test_03_chunker_unicode_multilingual` | Hindi, Spanish, Chinese, Emojis | PASS |
| `test_04_chunker_overlap_boundaries` | Consecutive chunk overlap integrity | PASS |
| `test_05_chunker_empty_and_whitespace` | Empty & whitespace document safety | PASS |
| `test_06_embedder_model_singleton` | FastEmbed singleton pattern | PASS |
| `test_07_embed_query_dimension_and_normalization` | 384 dimensions & L2 unit norm | PASS |
| `test_08_embed_deterministic_behavior` | Deterministic vector reproducibility | PASS |
| `test_09_embed_passages_batch` | Batch passage embedding generation | PASS |
| `test_10_embed_multilingual_semantic_similarity` | Cross-lingual cosine similarity (Hindi/Eng) | PASS |
| `test_11_async_embed_threadpool` | Async threadpool worker execution | PASS |
| `test_12_e5_prefix_handling` | E5 `query: ` and `passage: ` prefixing | PASS |
| `test_13_database_document_chunk_model` | SQLAlchemy model & cascading deletes | PASS |
| `test_14_database_indexes_declared_on_model` | Relational & HNSW vector indexes | PASS |
| `test_15_alembic_migration_upgrade_and_downgrade` | Alembic upgrade head & downgrade | PASS |
| `test_16_ingest_document_pipeline_and_idempotence` | Document ingestion & re-ingestion | PASS |
| `test_17_semantic_retrieval_and_threshold_filtering` | Cosine similarity ranking & threshold | PASS |
| `test_18_multi_tenant_isolation_security` | Strict cross-tenant leak prevention | PASS |
| `test_19_format_rag_context_and_prompts` | Prompt formatting & token budgeting | PASS |
| `test_20_end_to_end_chat_rag_sources` | End-to-end `POST /chat` with `sources` | PASS |
| `test_21_backfill_embeddings_script` | CLI backfill dry-run & execution | PASS |
| `test_22_delete_document_chunks_sync` | Hard/soft chunk deletion sync | PASS |
| `test_23_unsupported_or_empty_retrieval_fallback` | Edge-case empty query fallback | PASS |

### 2. Phase 1 Performance & Stability Regression Suite (`test_async_chat_performance.py`)
- **Total Tests:** 19
- **Passed:** 19 (100%)
- **Failed:** 0
- **Duration:** 6.72 seconds
- **Key Validations:** Zero DB connections held during LLM/embedding awaiting, event loop unblocked during heavy load, pagination on chat logs and leads, Groq model fallback hierarchy intact.

---

## Deliverables Summary

1. `backend/rag/` module (`__init__.py`, `chunker.py`, `embedder.py`, `retriever.py`, `ingestion.py`, `prompts.py`).
2. `alembic/versions/c4a189f7d23e_add_document_chunks_and_pgvector.py`.
3. `backend/database.py` updated with `DocumentChunk` and pgvector indexing.
4. `backend/app/schemas/models.py` updated with `SourceCitation` and `chunk_count`.
5. `backend/app/api/routers/documents.py` updated with complete ingestion pipeline.
6. `backend/app/api/routers/chat.py` updated with semantic RAG retrieval and source attribution.
7. `backend/faq_chain.py` updated with grounded RAG context prompt builder.
8. `backend/scripts/backfill_embeddings.py` management script.
9. `frontend/chatbot/script.js`, `frontend/chatbot/chatbot-embed.js`, and `frontend/chatbot/style.css` updated with source citation pill rendering.
10. `frontend/client/index.html` and `frontend/client/script.js` updated with indexed chunk count display.
11. `requirements.txt` updated with `pgvector>=0.3.0`, `fastembed>=0.4.0`, and `langchain-text-splitters>=0.2.0`.
12. Comprehensive test suites `test_phase2_rag.py` (23 tests) and `test_async_chat_performance.py` (19 tests).
13. Complete documentation: `phase2_rag_implementation_report.md`, `phase2_rag_architecture.md`, `phase2_deployment_guide.md`.
