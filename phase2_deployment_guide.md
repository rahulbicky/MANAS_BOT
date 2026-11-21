# ManasBot — Phase 2: Production Deployment & Migration Guide

**Project:** ManasBot (B2B AI Chatbot SaaS)
**Target Environment:** Neon PostgreSQL + Render / Cloud Hosting
**Maintainer:** Rahul Kumar

---

## 1. Prerequisites & Environment Variables

### 1.1 Python Virtual Environment & Dependencies
Ensure your production virtual environment has all required packages installed from `requirements.txt`:

```bash
pip install -r requirements.txt
```

Key Phase 2 dependencies:
- `pgvector>=0.3.0`
- `fastembed>=0.4.0`
- `langchain-text-splitters>=0.2.0`

### 1.2 Environment Variables
Ensure the following environment variables are configured in your production `.env` or Render environment settings:

```ini
# PostgreSQL connection string (Neon Serverless PostgreSQL with pgvector support)
CENTRAL_DB_URL=postgresql://user:password@ep-cool-project.us-east-2.aws.neon.tech/neondb?sslmode=require

# Groq API Key for LLM inference
GROQ_API_KEY=gsk_...

# Secret key for JWT and Fernet encryption
JWT_SECRET=your-32-byte-base64-secret-key-here
SECRET_KEY=your-32-byte-base64-secret-key-here

# Optional: FastEmbed cache directory (defaults to user home/.cache/fastembed)
FASTEMBED_CACHE_PATH=/app/.cache/fastembed
```

---

## 2. PostgreSQL `pgvector` Setup on Neon

Neon PostgreSQL supports `pgvector` natively.

### 2.1 Enable pgvector Extension
Connect to your Neon database via `psql` or the Neon SQL Editor console and execute:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Verify extension installation:
```sql
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
```

---

## 3. Database Migration Execution

ManasBot uses Alembic to manage database schema evolutions. The Phase 2 migration is:
- **Revision ID:** `c4a189f7d23e`
- **Down Revision:** `ef7a990203df` (Phase 1 indexes)
- **Description:** `add_document_chunks_and_pgvector`

### 3.1 Inspect Pending Migrations
```bash
alembic current
alembic history
```

### 3.2 Run Migration Upgrade to Head
```bash
alembic upgrade head
```

This will safely:
1. Ensure the `vector` extension exists in PostgreSQL.
2. Create the `document_chunks` table with column `embedding vector(384)`.
3. Create relational indexes:
   - `ix_document_chunks_tenant_id_is_active` on `(tenant_id, is_active)`
   - `ix_document_chunks_document_id` on `(document_id)`
4. Create the HNSW vector cosine index:
   - `ix_document_chunks_embedding_hnsw` using `hnsw (embedding vector_cosine_ops)`

### 3.3 Verify Created Indexes in PostgreSQL
```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'document_chunks';
```

---

## 4. Backfilling Existing Knowledge Documents

For existing production tenants who previously uploaded documents or URLs under Phase 1, their `knowledge_documents` records currently have no corresponding `document_chunks`.

ManasBot includes an automated, idempotent backfill CLI script: `backend/scripts/backfill_embeddings.py`.

### 4.1 Step 1: Perform a Dry-Run
Preview the documents that will be chunked and embedded without modifying database state:

```bash
python -m backend.scripts.backfill_embeddings --dry-run
```

Output will display:
```
Found 12 active documents matching criteria (tenant=ALL, force=False, dry_run=True).
[1/12] DRY-RUN: Would chunk 'employee_handbook.pdf' (14520 chars).
[2/12] DRY-RUN: Would chunk 'pricing_policy.docx' (4200 chars).
...
```

### 4.2 Step 2: Execute Backfill Across All Tenants
Process all un-indexed documents:

```bash
python -m backend.scripts.backfill_embeddings --batch-size 32
```

### 4.3 Step 3: Backfill a Specific Tenant (Optional)
If onboarding or re-indexing a single client:

```bash
python -m backend.scripts.backfill_embeddings --tenant-id <TENANT_UUID>
```

### 4.4 Step 4: Force Re-indexing (Optional)
To regenerate all embeddings and chunks from scratch:

```bash
python -m backend.scripts.backfill_embeddings --force
```

---

## 5. FastEmbed Model Pre-caching in Docker / Containerized Deployments

To prevent the container from downloading the ~180MB model weights on cold boot:
In your `Dockerfile` or deployment build step, pre-download the model:

```dockerfile
# Pre-download multilingual-e5-small model during build phase
RUN python -c "from fastembed import TextEmbedding; \
TextEmbedding.add_custom_model('intfloat/multilingual-e5-small'); \
m = TextEmbedding('intfloat/multilingual-e5-small')"
```

---

## 6. Health Checks & Verification

After deployment, verify that the system is operating normally:

### 6.1 Application Health Check
```bash
curl -f https://your-domain.com/health
```
Expected response:
```json
{"status": "healthy", "service": "manasbot-backend"}
```

### 6.2 Test Chat Query with Citations
```bash
curl -X POST https://your-domain.com/chat \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the return policy?",
    "session_id": "test_verification_001",
    "tenant_id": "<VALID_TENANT_ID>",
    "language": "en"
  }'
```
Verify that the JSON response contains:
- `answer`: Grounded response with `[Source: ...]` citations.
- `sources`: Non-empty list containing `filename` and `relevance_score`.

---

## 7. Rollback Procedure

If any issues arise in production, rollback is simple and non-destructive:

### 7.1 Downgrade Alembic Migration
To cleanly remove `document_chunks` and restore the schema to Phase 1 head:

```bash
alembic downgrade ef7a990203df
```

This drops `document_chunks` while leaving all Phase 1 tables (`knowledge_documents`, `tenants`, `business_profile`, `faqs`, `chat_logs_v2`) 100% intact.

### 7.2 Fallback Ingestion Behavior
The application gracefully falls back to legacy document text retrieval if `document_chunks` table is dropped or empty.
