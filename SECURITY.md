# ManasBot — Enterprise Security & Compliance Guide

## 1. Security Architecture Overview

ManasBot is architected around the Principle of Least Privilege, cryptographic data isolation, and defense-in-depth:

```
[Client / User Request]
         │
         ▼
[WAF / Reverse Proxy / SlowAPI Rate Limiting]
         │
         ▼
[CORS Origin Whitelisting]
         │
         ▼
[Authentication & Authorization Layer]
 ├── Employee: JWT Bearer Token (HS256, Expiration, Role Invalidation)
 └── Tenant: API Key (X-Auth-Token Header)
         │
         ▼
[Input Sanitization & Injection Defense]
 ├── HTML / Script Tag Escaping
 ├── SSRF URL & IP Range Validation (Blocks 127.0.0.1, 169.254.169.254, RFC 1918)
 └── Prompt Injection Boundary Wrapping
         │
         ▼
[Database / Storage Tier]
 ├── Cryptographic Tenant Separation
 └── AES-GCM Fernet Encryption at Rest for Chat Logs & Secrets
```

---

## 2. Authentication & RBAC

1. **Employee JWT Authentication**:
   - Algorithm: `HS256` signed using `JWT_SECRET`.
   - In production, minimum key length of 32 characters is strictly validated.
   - **Role-Based Access Control**:
     - `super_admin`: Full tenant provisioning, hard deletes, employee management.
     - `admin`: Client management, document uploads, metrics review.
     - `support`: Read-only tenant review, incident triage.
   - **Instant Session Invalidation**: When an employee's role or status is updated in the database, `role_changed_at` timestamps invalidate all previously issued tokens for that employee.

2. **Tenant API Key Authentication**:
   - `X-Auth-Token: <api_key>` header validation.
   - Requests targeting Tenant B with Tenant A's key are rejected with `403 Forbidden`.

---

## 3. SSRF (Server-Side Request Forgery) Protection

The document scraper (`POST /admin/add-url`) and background scheduler implement SSRF validation (`backend/app/utils/security_validation.py`):
- Verifies URL scheme is strictly `http` or `https`.
- Resolves DNS hostname to all associated IPv4 and IPv6 addresses.
- Rejects requests if any resolved IP belongs to:
  - Loopback: `127.0.0.0/8`, `::1`
  - Private networks: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
  - Link-local & Cloud Metadata: `169.254.0.0/16`, `fe80::/10` (including `169.254.169.254` AWS/GCP metadata)
  - Multicast and reserved ranges

---

## 4. Encryption at Rest & Secret Management

- **Conversational Chat Logs**: User inquiries and chatbot answers are encrypted at rest using AES-GCM Fernet symmetric encryption before being committed to PostgreSQL or SQLite.
- **Tenant API Keys**: Encrypted in the database using `ENCRYPTION_KEY`.
- **Environment Isolation**: Production deployments must inject secrets via environment variables or secret managers (e.g. AWS Secrets Manager, GCP Secret Manager, Vault). No secrets are hardcoded in the codebase.

---

## 5. Rate Limiting & Abuse Prevention

- **SlowAPI**: Enforces request rate limits per IP address on public endpoints (e.g., 5 requests/minute on login endpoints).
- **Abuse Logger**: Tracks failed authentication attempts and triggers email alerts when error spikes or abnormal traffic patterns occur.
