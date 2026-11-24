# ManasBot — REST API Documentation

Base URL: `http://localhost:8000` (or `https://your-domain.com`)

## 1. Authentication Schemes

ManasBot supports two distinct authentication schemes:

1. **Employee Bearer JWT**:
   - Header: `Authorization: Bearer <jwt_token>`
   - Acquired via `POST /admin/employee-login`
   - Scoped by employee roles: `super_admin`, `admin`, `support`

2. **Tenant Client API Key**:
   - Header: `X-Auth-Token: <tenant_api_key>`
   - Authenticates tenant dashboard requests and widget configuration lookups

---

## 2. Public Chat & Widget Endpoints

### POST `/chat`
Generates conversational AI responses using LangGraph, RAG vector retrieval, and FAQ matching.

**Request Body**:
```json
{
  "question": "What is your refund policy?",
  "session_id": "sess_abc123",
  "language": "en",
  "page_url": "https://example.com/pricing"
}
```

**Query Parameters**:
- `tenant_id` (string, required): Target client tenant ID.

**Response (200 OK)**:
```json
{
  "answer": "Refund requests are processed within 14 calendar days [Source: refund_policy.docx].",
  "intent": "refund_inquiry",
  "is_resolved": true,
  "sources": [
    {
      "document_id": "doc_99",
      "filename": "refund_policy.docx",
      "relevance_score": 0.8921
    }
  ],
  "session_id": "sess_abc123"
}
```

### GET `/chat/config`
Retrieves client-facing chatbot UI branding and welcome configuration.

**Query Parameters**:
- `tenant_id` (string, required): Client tenant ID.

**Response (200 OK)**:
```json
{
  "company_name": "Acme Logistics",
  "greeting": "Hi! How can I help you today?",
  "primary_color": "#2563eb",
  "logo_url": "https://example.com/logo.png"
}
```

---

## 3. Employee & Administrative Endpoints

### POST `/admin/employee-login`
Authenticates backend employees and issues an access JWT.

**Request Body**:
```json
{
  "email": "admin@manasbot.local",
  "password": "SecurePassword123!"
}
```

**Response (200 OK)**:
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "role": "super_admin",
  "email": "admin@manasbot.local"
}
```

### GET `/admin/tenants`
Lists registered client tenants (Super Admin / Admin / Support).

**Headers**: `Authorization: Bearer <token>`
**Query Parameters**: `plan_name`, `is_active`, `search_name`

### POST `/admin/tenant`
Provisions a new tenant database and registers tenant credentials (Super Admin only).

**Request Body**:
```json
{
  "name": "New Client Corp",
  "username": "client_corp",
  "email": "contact@clientcorp.com",
  "plan": "growth"
}
```

---

## 4. Document & Knowledge Base Management

### POST `/admin/upload-doc`
Uploads and indexes documents (`.pdf`, `.docx`, `.txt`, `.csv`, `.xlsx`).
Extracts text, splits into token-aware overlapping chunks, generates FastEmbed vectors, and stores chunks with content hashes.

**Headers**: `Authorization: Bearer <token>` OR `X-Auth-Token: <api_key>`
**Form Data**: `file` (binary), `tenant_id` (query)

### POST `/admin/add-url`
Scrapes an external URL, cleans HTML tags, and indexes text content. Protected by SSRF validation.

**Request Body**:
```json
{
  "url": "https://example.com/about"
}
```

### DELETE `/admin/doc/{doc_id}`
Soft-deletes a document and deletes all associated vector chunks.

---

## 5. Retention & Data Governance

### GET `/admin/retention-policy`
Retrieves chat log and lead data retention policies.

### POST `/admin/retention-policy`
Configures automated data purge windows (7 days, 30 days, 90 days, or indefinite).

### POST `/admin/retention-cleanup`
Triggers retention cleanup execution or dry-run inspection report.

**Query Parameters**: `dry_run=true|false`
