# ManasBot — Database Architecture & Schema Documentation

## 1. Relational & Vector Persistence Model

ManasBot supports both **PostgreSQL (with pgvector)** for production scale and **SQLite** for zero-dependency local development and testing.

Connection pooling is configured via `create_engine`:
- `pool_size`: 10
- `max_overflow`: 20
- `pool_recycle`: 1800 (prevents stale Neon connection drops)
- `pool_pre_ping`: True (validates connections before checkout)

---

## 2. Central Database Schema

The Central Database manages global SaaS state, tenant accounts, employees, and billing plans.

### `central_tenants`
Stores registered client companies and subscription parameters.
- `id` (VARCHAR PK): UUID primary key
- `name` (VARCHAR): Business legal/operating name
- `username` (VARCHAR UNIQUE): Tenant slug / username
- `email` (VARCHAR): Primary contact email
- `password_hash` (VARCHAR): Encrypted bcrypt credential
- `api_key` (VARCHAR INDEX): Secret API key for client dashboard & API
- `db_url` (VARCHAR): Custom per-tenant database URL (empty = central DB)
- `current_plan` (VARCHAR): Free, Starter, Growth, Enterprise
- `monthly_messages` (INTEGER): Message usage counter in current billing cycle
- `is_active` (BOOLEAN): Soft-delete toggle
- `is_demo_account` (BOOLEAN): Read-only sandbox toggle
- `created_at` (DATETIME UTC): Account provisioning timestamp

### `employees`
System administrators, support engineers, and operators.
- `id` (VARCHAR PK): UUID primary key
- `email` (VARCHAR UNIQUE): Employee login email
- `password_hash` (VARCHAR): Bcrypt hash
- `role` (VARCHAR): `super_admin`, `admin`, `support`
- `role_changed_at` (DATETIME UTC): Timestamp of last role modification (for token revocation)
- `is_active` (BOOLEAN): Active status

### `plans`
Subscription tier definitions and rate limits.
- `name` (VARCHAR PK): Plan tier name
- `max_messages` (INTEGER): Monthly message cap
- `max_docs` (INTEGER): Maximum uploadable documents
- `price_usd` (FLOAT): Monthly recurring fee

---

## 3. Tenant Knowledge & Operations Schema

Tables partitioned or filtered by `tenant_id`:

### `knowledge_documents`
Tracks source files and scraped URLs.
- `id` (VARCHAR PK): Document UUID
- `tenant_id` (VARCHAR INDEX): Owner tenant
- `filename` (VARCHAR): Original filename or source URL
- `file_type` (VARCHAR): `pdf`, `docx`, `txt`, `csv`, `xlsx`, `url`
- `file_size_bytes` (INTEGER): Size in bytes
- `content` (TEXT): Normalized extracted plain text
- `is_active` (BOOLEAN): Active toggle
- `created_at` (DATETIME UTC): Ingestion timestamp

### `document_chunks`
Vector store chunks.
- `id` (VARCHAR PK): Chunk UUID
- `document_id` (VARCHAR FK -> knowledge_documents.id): Parent document
- `tenant_id` (VARCHAR INDEX): Tenant isolation index
- `chunk_index` (INTEGER): Sequential order inside document
- `chunk_text` (TEXT): Passage content
- `token_count` (INTEGER): Estimated token count
- `content_hash` (VARCHAR): SHA-256 hash of text for deduplication
- `embedding` (VECTOR(384) in Postgres / JSON TEXT in SQLite): Dense vector embedding
- **Indexes**:
  - `ix_doc_chunks_tenant_id` (`tenant_id`)
  - `ix_doc_chunks_doc_id` (`document_id`)
  - HNSW Index on `embedding` using cosine distance operator (`vector_cosine_ops`)

### `chat_logs`
Historical conversation records.
- `id` (VARCHAR PK): Log UUID
- `tenant_id` (VARCHAR INDEX): Tenant identifier
- `session_id` (VARCHAR INDEX): Multi-turn session ID
- `question` (TEXT): Encrypted user question
- `answer` (TEXT): Encrypted chatbot response
- `intent` (VARCHAR): Detected intent classification
- `is_resolved` (BOOLEAN): Resolution flag
- `timestamp` (DATETIME UTC): Message timestamp

### `leads`
Prospective customer inquiries captured by regex or Agentic tools.
- `id` (VARCHAR PK): Lead UUID
- `tenant_id` (VARCHAR INDEX): Target tenant
- `session_id` (VARCHAR INDEX): Chat session
- `name` (VARCHAR): Customer name
- `phone` (VARCHAR): Contact phone
- `email` (VARCHAR): Contact email
- `raw_message` (TEXT): Inquiry details
- `is_notified` (BOOLEAN): Email alert dispatch status
- `created_at` (DATETIME UTC): Capture timestamp

### `incidents`
Operational support tickets and escalations.
- `id` (VARCHAR PK): Incident UUID
- `tenant_id` (VARCHAR INDEX): Tenant ID
- `title` (VARCHAR): Summary
- `description` (TEXT): Issue details
- `severity` (VARCHAR): low, medium, high, critical
- `status` (VARCHAR): open, in_progress, resolved
- `created_at` (DATETIME UTC): Creation timestamp
