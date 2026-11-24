# ManasBot — System Architecture Documentation

## 1. High-Level System Architecture

ManasBot is an enterprise multi-tenant AI Chatbot SaaS platform designed for high-throughput, low-latency, and zero-data-leakage customer support operations.

The system decouples synchronous API serving, asynchronous AI model inference, multi-tenant persistence, and isolated knowledge retrieval into clear operational tiers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          CLIENT TIER (HTML5 / JS)                      │
│   Super Admin Panel        Client / Tenant Dashboard    Chatbot Widget │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ HTTPS / REST API
┌────────────────────────────────────▼───────────────────────────────────┐
│                    API GATEWAY & FASTAPI BACKEND                       │
│  - Reverse Proxy / CORS / Rate Limiting (SlowAPI)                      │
│  - Employee JWT Bearer Authentication & RBAC (super_admin, admin, ...) │
│  - Multi-tenant API Key Validation (X-Auth-Token)                     │
│  - SSRF URL Sanitization & IP Address Whitelisting                     │
│  - Request Logging, Error Tracking & Abuse Throttling                  │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
         ┌───────────────────────────┴───────────────────────────┐
         ▼                                                       ▼
┌───────────────────────────────────┐   ┌────────────────────────────────┐
│  THREE-PHASE CHAT LIFECYCLE       │   │    KNOWLEDGE MANAGEMENT        │
│  Phase A: Short-lived DB Read     │   │  - Document parser (PDF/DOCX)  │
│  Phase B: Zero-DB LangGraph       │   │  - Token-aware chunking        │
│  Phase C: Short-lived DB Write    │   │  - Multilingual FastEmbed (CPU)│
└────────────────┬──────────────────┘   └────────────────┬───────────────┘
                 │                                       │
                 ▼                                       ▼
┌───────────────────────────────────┐   ┌────────────────────────────────┐
│   LANGGRAPH STATE WORKFLOW        │   │   AGENTIC AI TOOLS             │
│  - Guard & Sanitization Node      │   │  - KnowledgeRetrievalTool      │
│  - Intent Classifier Node         │   │  - BusinessProfileTool         │
│  - FAQ Matcher Node               │   │  - LeadCaptureTool             │
│  - Conversational Rewriter Node   │   │  - SupportIncidentTool         │
│  - Semantic Vector Retriever Node │   └────────────────────────────────┘
│  - LLM Answer Generator Node      │
│  - Structured Citation Formatter  │
└────────────────┬──────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        PERSISTENCE & STORAGE                           │
│  - Central DB: PostgreSQL / Neon (Tenants, Employees, System Metrics)  │
│  - Tenant Isolated Tables: BusinessProfile, FAQs, KnowledgeDocs, Leads │
│  - Vector Storage: pgvector (HNSW cosine index) with SQLite fallback   │
│  - LangGraph Checkpoints: AsyncPostgresSaver with MemorySaver fallback │
│  - AES-GCM Fernet Encryption: At-rest encryption for sensitive data   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Three-Phase Chat Execution Architecture

To guarantee high scalability and prevent connection pool exhaustion during long LLM inference times (1–4 seconds), ManasBot strictly adheres to a three-phase connection architecture:

1. **Phase A (Database Read — Short-Lived Session)**:
   - Ingests incoming user payload (`session_id`, `question`, `tenant_id`).
   - Opens a transient database session (connection held < 5ms).
   - Validates monthly message limits and active plan status.
   - Loads tenant branding, business description, and pre-configured FAQs.
   - Retrieves the last 3–5 dialogue turns for the session; decrypts chat logs at runtime.
   - Closes the database session immediately before LangGraph execution.

2. **Phase B (LangGraph Workflow Execution — Zero DB Connections Held)**:
   - Evaluates input sanitization and regex lead extraction.
   - Executes async intent detection with fallback (Qwen 3.8B -> LLaMA 3.3 70B -> Groq 8B).
   - Resolves conversational coreference queries ("how much is it?" -> "enterprise tier - how much is it?").
   - Fetches semantic vector candidates using short-lived isolated retrieval.
   - Generates contextual answers using multi-turn conversation memory.
   - Formats source citations (`[Source: filename.pdf]`).

3. **Phase C (Database Write — Short-Lived Session)**:
   - Opens a fresh transient database session (< 5ms).
   - Encrypts user message and AI response with Fernet AES-GCM before writing to `chat_logs`.
   - Increments tenant monthly message counter and updates active session timestamp.
   - Persists detected sales leads to `leads` table and triggers async email notification.
   - Closes the database session and returns response payload to client.

---

## 3. Multi-Tenant Isolation Architecture

ManasBot implements schema-enforced and query-enforced tenant isolation:
- Every tenant entity (`KnowledgeDocument`, `DocumentChunk`, `FAQ`, `Lead`, `ChatLog`, `Incident`, `BusinessProfile`) explicitly indexes `tenant_id`.
- The database dependency `get_tenant_db` verifies either the tenant's valid `api_key` (`X-Auth-Token`) or an authenticated employee JWT with sufficient role permissions.
- In cross-tenant scenarios (e.g., Tenant A presenting Tenant B's ID), `get_tenant_db` rejects the request with HTTP `403 Forbidden`.
- Checkpointer entries (`PostgresCheckpointSaver`) namespace thread identifiers as `{tenant_id}:{session_id}`, preventing cross-session or cross-tenant state leaks.

---

## 4. Concurrency & Session Serialization

Concurrent requests sharing the same `session_id` are serialized using `LocalSessionLockRegistry`:
- An asynchronous lock pool ensures that multiple rapid clicks or queries from the same user session do not cause race conditions or corrupt conversation state.
- Distinct user sessions execute completely concurrently without blocking.
- Reference counting ensures inactive session locks are garbage collected to prevent memory leaks.
