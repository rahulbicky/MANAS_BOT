# ManasBot — Project Changelog

All notable changes to the ManasBot platform are documented here.

---

## [Phase 11] — Final Enterprise Productionization (2026-11-24)

### Added:
- **Agentic AI Tools Suite (`backend/rag/tools.py`)**:
  - `KnowledgeRetrievalTool`: Semantic vector retrieval with tenant isolation and execution timeouts.
  - `BusinessProfileTool`: Fast retrieval of operating hours, location, contact email, and phone.
  - `LeadCaptureTool`: Structured prospective customer data persistence.
  - `SupportIncidentTool`: Support escalation and ticketing.
  - `get_tenant_agent_tools(tenant_id)`: Tenant-scoped LangChain `StructuredTool` factory.
- **SSRF Defense (`backend/app/utils/security_validation.py`)**:
  - `validate_public_url(url)`: DNS resolution check blocking loopback, link-local, cloud metadata (`169.254.169.254`), and RFC 1918 private subnets.
  - Hardened `POST /admin/add-url` and APScheduler URL scraper against SSRF attacks.
- **Advanced RAG Enhancements**:
  - Content-based chunk deduplication using SHA-256 content hashes.
  - Multi-turn conversational coreference resolution (`resolve_conversational_query`).
  - Dynamic multilingual threshold adaptation (`MULTILINGUAL_ADAPTED_THRESHOLD = 0.58`).
  - Cross-encoder reranking blending cosine similarity, exact phrase matches, and token density.
- **RAG Evaluation Harness (`backend/rag/evaluation.py`)**:
  - Hit Rate @ K, MRR @ K, Context Precision, and latency profiling.
- **Test Automation**:
  - `test_rag_benchmarking.py` (9 tests)
  - `test_security_hardening.py` (6 tests)
  - Automated test suite expanded to **86 total passing tests**.
- **DevOps**:
  - Production `docker-compose.yml` with pgvector service.
- **Comprehensive Documentation**:
  - Added 12 architecture, security, API, database, and operational documentation guides.

---

## [Phase 3.1 & 3.0] — Reliability & Checkpointing

### Added:
- PostgreSQL-backed persistent LangGraph checkpointing (`PostgresCheckpointSaver`, `AsyncPostgresSaver`).
- In-memory `MemorySaver` graceful fallback for offline or disconnected environments.
- In-process session serialization lock (`LocalSessionLockRegistry`).
- Tenant data retention service with configurable retention windows and dry-run reporting.
- Modernized UTC timestamps (`ensure_utc`).

---

## [Phase 2.0 & 1.0] — Architectural Modernization & RAG

### Added:
- Decoupled Three-Phase Chat Execution Architecture (DB Read -> Zero-DB LangGraph -> DB Write).
- In-process FastEmbed ONNX multilingual embeddings (`intfloat/multilingual-e5-small`).
- LangGraph conversational state workflow (`backend/rag/graph.py`).
- Tenant-isolated vector indexing with pgvector and SQLite fallback.
